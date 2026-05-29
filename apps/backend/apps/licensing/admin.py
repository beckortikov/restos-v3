from datetime import timedelta

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
)

from .models import License, LicensePlan


class LicenseStatusFilter(admin.SimpleListFilter):
    """Логичный фильтр по вычисляемому статусу лицензии."""

    title = "Статус"
    parameter_name = "lic_status"

    def lookups(self, request, model_admin):
        return (
            ("active", "Активна"),
            ("grace", "Grace-период"),
            ("expired", "Истекла"),
            ("blocked", "Заблокирована"),
            ("expiring_soon", "Истекает в ближайшие 7 дн."),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        val = self.value()
        if val == "blocked":
            return queryset.filter(is_blocked=True)
        if val == "expired":
            return queryset.filter(
                is_blocked=False,
                expires_at__lt=now - timedelta(days=License.GRACE_DAYS),
            )
        if val == "grace":
            return queryset.filter(
                is_blocked=False,
                expires_at__lt=now,
                expires_at__gte=now - timedelta(days=License.GRACE_DAYS),
            )
        if val == "active":
            return queryset.filter(is_blocked=False, expires_at__gte=now)
        if val == "expiring_soon":
            return queryset.filter(
                is_blocked=False,
                expires_at__gte=now,
                expires_at__lte=now + timedelta(days=7),
            )
        return queryset


@admin.register(License)
class LicenseAdmin(ModelAdmin):
    """Управление лицензиями ресторанов — dropdown-фильтры + bulk-actions."""

    list_display = (
        "restaurant",
        "plan",
        "status_badge",
        "expires_at",
        "days_left_col",
        "last_heartbeat_col",
        "is_bound_col",
        "is_blocked",
    )
    list_filter = (
        LicenseStatusFilter,
        ("plan", ChoicesDropdownFilter),
        ("expires_at", RangeDateFilter),
        ("created_at", RangeDateFilter),
        "is_blocked",
    )
    list_filter_submit = False
    autocomplete_fields = ("restaurant",)
    date_hierarchy = "expires_at"
    search_fields = ("restaurant__name", "license_key", "notes")
    readonly_fields = (
        "license_key",
        "created_at",
        "updated_at",
        "status_badge",
        "days_left_col",
        "last_heartbeat_col",
    )
    fieldsets = (
        ("Ресторан", {"fields": ("restaurant",)}),
        ("Лицензия", {
            "fields": (
                "plan", "started_at", "expires_at",
                "is_blocked", "block_reason",
                "license_key",
            ),
        }),
        ("Состояние", {
            "fields": (
                "status_badge", "days_left_col", "last_heartbeat_col",
            ),
        }),
        ("Привязка к машине (SA-7)", {
            "fields": ("hardware_uuid", "activated_at"),
            "description": (
                "Windows BIOS UUID привязанной POS-машины. "
                "Очистите поле hardware_uuid (или используйте action «Сбросить "
                "привязку») чтобы разрешить переактивацию на новой машине."
            ),
        }),
        ("Заметки", {"fields": ("notes",)}),
        ("Метаданные", {"fields": ("created_at", "updated_at")}),
    )
    actions = (
        "renew_30_days",
        "renew_90_days",
        "renew_365_days",
        "block_unpaid",
        "unblock",
        "reset_machine_binding",
    )

    # ---- formatted columns ----

    def status_badge(self, obj: License):
        colors = {
            "active": "green",
            "grace": "orange",
            "expired": "red",
            "blocked": "darkred",
        }
        st = obj.status
        return format_html(
            '<span style="color:{}; font-weight:700">{}</span>',
            colors.get(st, "gray"), st.upper(),
        )
    status_badge.short_description = "Статус"

    def days_left_col(self, obj: License):
        d = obj.days_left
        color = "green" if d > 7 else ("orange" if d > 0 else "red")
        return format_html(
            '<span style="color:{}">{} дн</span>', color, d,
        )
    days_left_col.short_description = "Осталось"

    def last_heartbeat_col(self, obj: License):
        rest = obj.restaurant
        if not rest.last_heartbeat_at:
            return "—"
        delta = timezone.now() - rest.last_heartbeat_at
        if delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            return format_html(
                '<span style="color:green">{} мин назад</span>', mins,
            )
        hours = int(delta.total_seconds() / 3600)
        if hours < 24:
            return format_html(
                '<span style="color:orange">{} ч назад</span>', hours,
            )
        days = delta.days
        return format_html(
            '<span style="color:red">{} дн назад</span>', days,
        )
    last_heartbeat_col.short_description = "Heartbeat"

    # ---- actions ----

    @admin.action(description="Продлить на 30 дней")
    def renew_30_days(self, request, queryset):
        self._renew(request, queryset, 30)

    @admin.action(description="Продлить на 90 дней")
    def renew_90_days(self, request, queryset):
        self._renew(request, queryset, 90)

    @admin.action(description="Продлить на 1 год")
    def renew_365_days(self, request, queryset):
        self._renew(request, queryset, 365)

    def _renew(self, request, queryset, days):
        n = 0
        for lic in queryset:
            lic.renew(days=days)
            n += 1
        self.message_user(
            request, f"Продлено лицензий: {n} на {days} дней",
            level=messages.SUCCESS,
        )

    @admin.action(description="Заблокировать (за неуплату)")
    def block_unpaid(self, request, queryset):
        n = queryset.update(is_blocked=True, block_reason="Неуплата")
        self.message_user(
            request, f"Заблокировано: {n}", level=messages.WARNING,
        )

    @admin.action(description="Разблокировать")
    def unblock(self, request, queryset):
        n = queryset.update(is_blocked=False, block_reason="")
        self.message_user(
            request, f"Разблокировано: {n}", level=messages.SUCCESS,
        )

    @admin.action(description="Сбросить привязку к машине (SA-7)")
    def reset_machine_binding(self, request, queryset):
        n = queryset.update(hardware_uuid="", activated_at=None)
        self.message_user(
            request,
            f"Привязка сброшена для {n} лицензий — теперь можно активировать заново.",
            level=messages.SUCCESS,
        )

    def is_bound_col(self, obj: License):
        if obj.hardware_uuid:
            short = obj.hardware_uuid[:8] + "…"
            return format_html(
                '<span style="color:green; font-family:monospace">{}</span>', short,
            )
        return format_html('<span style="color:gray">—</span>')
    is_bound_col.short_description = "Машина"

    def save_model(self, request, obj, form, change):
        # Автогенерация license_key для новых записей
        if not obj.license_key:
            import uuid

            obj.license_key = uuid.uuid4().hex
        # Дефолт expires_at = now + 30 дней (триал) если не задано
        if not obj.expires_at:
            obj.expires_at = timezone.now() + timedelta(days=30)
        super().save_model(request, obj, form, change)
