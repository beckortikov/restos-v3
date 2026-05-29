import secrets
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline
from unfold.decorators import action
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.contrib.forms.widgets import WysiwygWidget  # noqa: F401  (готово к использованию)
from unfold.widgets import UnfoldAdminTextInputWidget

from apps.licensing.models import License
from apps.orders.models import Order, OrderStatus

from .models import PinSession, Restaurant, User


class HasApiKeyFilter(admin.SimpleListFilter):
    title = "API-ключ"
    parameter_name = "has_api_key"

    def lookups(self, request, model_admin):
        return (("yes", "Установлен"), ("no", "Не установлен"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(api_key="")
        if self.value() == "no":
            return queryset.filter(api_key="")
        return queryset


class HeartbeatFreshnessFilter(admin.SimpleListFilter):
    title = "Heartbeat"
    parameter_name = "heartbeat"

    def lookups(self, request, model_admin):
        return (
            ("live", "Жив (< 1 ч)"),
            ("idle", "Idle (1–24 ч)"),
            ("offline", "Offline (> 24 ч)"),
            ("never", "Никогда не пинговал"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        val = self.value()
        if val == "live":
            return queryset.filter(last_heartbeat_at__gte=now - timedelta(hours=1))
        if val == "idle":
            return queryset.filter(
                last_heartbeat_at__gte=now - timedelta(hours=24),
                last_heartbeat_at__lt=now - timedelta(hours=1),
            )
        if val == "offline":
            return queryset.filter(last_heartbeat_at__lt=now - timedelta(hours=24))
        if val == "never":
            return queryset.filter(last_heartbeat_at__isnull=True)
        return queryset


class LicenseInline(StackedInline):
    """License-блок прямо на странице ресторана. Один OneToOne — max_num=1."""

    model = License
    extra = 0
    max_num = 1
    can_delete = False
    readonly_fields = ("license_key", "created_at", "updated_at")
    fieldsets = (
        ("Лицензия", {
            "fields": (
                ("plan", "started_at", "expires_at"),
                ("is_blocked", "block_reason"),
                "license_key", "notes",
                ("created_at", "updated_at"),
            ),
        }),
    )


@admin.register(Restaurant)
class RestaurantAdmin(ModelAdmin):
    """Centralized restaurant management with embedded license + revenue stats."""

    list_display = (
        "id",
        "name_col",
        "license_badge",
        "plan_col",
        "expires_col",
        "heartbeat_col",
        "today_revenue_col",
        "app_version",
        "api_key_status",
    )
    list_display_links = ("name_col",)
    search_fields = ("name", "phone", "address")
    list_filter = (
        ("license__plan", ChoicesDropdownFilter),
        "license__is_blocked",
        HeartbeatFreshnessFilter,
        HasApiKeyFilter,
        ("currency", ChoicesDropdownFilter),
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    inlines = (LicenseInline,)
    list_per_page = 25
    ordering = ("name",)
    readonly_fields = ("api_key_display", "created_at", "last_heartbeat_at")
    fieldsets = (
        ("Основное", {
            "fields": (("name", "currency"), ("address", "phone")),
        }),
        ("Чек / печать", {
            "fields": (
                "receipt_header_extra", "receipt_footer",
                "auto_open_cash_drawer", "receipt_copies",
            ),
            "classes": ("collapse",),
        }),
        ("Настройки заведения", {
            "fields": (
                "pin_lock_timeout_min",
                "kitchen_enabled",
                "manager_override_threshold_tjs",
            ),
            "classes": ("collapse",),
        }),
        ("Heartbeat / телеметрия", {
            "fields": ("last_heartbeat_at", "app_version"),
        }),
        ("API-ключ (M2M auth)", {
            "fields": ("api_key_display",),
            "description": (
                "Секрет для аутентификации ресторанного сервера в облаке. "
                "Кнопка «Ротейтить api_key» — справа сверху на странице ресторана."
            ),
        }),
        ("Системное", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
    actions = (
        "extend_license_30",
        "extend_license_90",
        "extend_license_365",
        "block_licenses",
        "unblock_licenses",
        "rotate_api_keys",
    )
    # Unfold action_buttons на detail-странице ресторана
    actions_detail = ("rotate_api_key_detail",)

    # ---- columns ----

    def name_col(self, obj: Restaurant):
        return format_html(
            '<strong>{}</strong><br/><small style="color:#94A3B8">{}</small>',
            obj.name, obj.address or "",
        )
    name_col.short_description = "Ресторан"
    name_col.admin_order_field = "name"

    def license_badge(self, obj: Restaurant):
        lic = getattr(obj, "license", None)
        if lic is None:
            return format_html('<span style="color:#94A3B8">—</span>')
        st = lic.status
        colors = {
            "active": ("#16A34A", "#DCFCE7"),
            "grace": ("#CA8A04", "#FEF9C3"),
            "expired": ("#DC2626", "#FEE2E2"),
            "blocked": ("#7F1D1D", "#FECACA"),
        }
        fg, bg = colors.get(st, ("#475569", "#F1F5F9"))
        return format_html(
            '<span style="background:{};color:{};padding:2px 10px;'
            'border-radius:999px;font-size:11px;font-weight:700;'
            'text-transform:uppercase">{}</span>',
            bg, fg, st,
        )
    license_badge.short_description = "Лицензия"

    def plan_col(self, obj: Restaurant):
        lic = getattr(obj, "license", None)
        return lic.plan if lic else "—"
    plan_col.short_description = "Тариф"

    def expires_col(self, obj: Restaurant):
        lic = getattr(obj, "license", None)
        if not lic:
            return "—"
        d = lic.days_left
        color = "#16A34A" if d > 7 else ("#CA8A04" if d > 0 else "#DC2626")
        return format_html(
            '{}<br/><small style="color:{}">{} дн.</small>',
            lic.expires_at.strftime("%d.%m.%Y"), color, d,
        )
    expires_col.short_description = "Истекает"

    def heartbeat_col(self, obj: Restaurant):
        if not obj.last_heartbeat_at:
            return format_html('<span style="color:#94A3B8">никогда</span>')
        delta = timezone.now() - obj.last_heartbeat_at
        secs = delta.total_seconds()
        if secs < 3600:
            return format_html(
                '<span style="color:#16A34A">●</span> {} мин назад',
                int(secs / 60),
            )
        if secs < 86400:
            return format_html(
                '<span style="color:#CA8A04">●</span> {} ч назад',
                int(secs / 3600),
            )
        return format_html(
            '<span style="color:#DC2626">●</span> {} дн назад',
            delta.days,
        )
    heartbeat_col.short_description = "Heartbeat"

    def today_revenue_col(self, obj: Restaurant):
        from datetime import datetime, time
        from datetime import timezone as tz

        today_start = datetime.combine(
            timezone.now().date(), time.min, tzinfo=tz.utc,
        )
        rev = Decimal("0.00")
        for o in Order.objects.filter(
            restaurant=obj, status=OrderStatus.DONE,
            closed_at__gte=today_start,
        ).only("id"):
            rev += o.total
        return f"{rev:.2f} {obj.currency}"
    today_revenue_col.short_description = "Выручка сегодня"

    def api_key_status(self, obj: Restaurant):
        if obj.api_key:
            return format_html(
                '<code style="font-size:11px">{}…</code>',
                obj.api_key[:8],
            )
        return format_html('<span style="color:#94A3B8">—</span>')
    api_key_status.short_description = "API-ключ"

    def api_key_display(self, obj: Restaurant):
        if not obj.api_key:
            return format_html(
                '<span style="color:#94A3B8">не установлен — '
                'нажмите action «Ротейтить api_key» в списке</span>'
            )
        return format_html(
            '<code>{}</code>'
            '<br/><small style="color:#94A3B8">'
            'Записан в env-конфиг ресторанного сервера как RESTAURANT_API_KEY.'
            '</small>',
            obj.api_key,
        )
    api_key_display.short_description = "API-ключ (read-only)"

    # ---- actions ----

    @admin.action(description="Продлить лицензию на 30 дней")
    def extend_license_30(self, request, queryset):
        self._extend(request, queryset, 30)

    @admin.action(description="Продлить лицензию на 90 дней")
    def extend_license_90(self, request, queryset):
        self._extend(request, queryset, 90)

    @admin.action(description="Продлить лицензию на 1 год")
    def extend_license_365(self, request, queryset):
        self._extend(request, queryset, 365)

    def _extend(self, request, queryset, days):
        n = 0
        for r in queryset:
            lic = getattr(r, "license", None)
            if lic is None:
                continue
            base = max(lic.expires_at, timezone.now())
            lic.expires_at = base + timedelta(days=days)
            lic.save(update_fields=["expires_at", "updated_at"])
            n += 1
        self.message_user(
            request, f"Продлено лицензий: {n} на {days} дн.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Заблокировать лицензии (за неуплату)")
    def block_licenses(self, request, queryset):
        n = 0
        for r in queryset:
            lic = getattr(r, "license", None)
            if lic is None:
                continue
            lic.is_blocked = True
            lic.block_reason = "Неуплата"
            lic.save(update_fields=["is_blocked", "block_reason", "updated_at"])
            n += 1
        self.message_user(
            request, f"Заблокировано: {n}", level=messages.WARNING,
        )

    @admin.action(description="Разблокировать лицензии")
    def unblock_licenses(self, request, queryset):
        n = 0
        for r in queryset:
            lic = getattr(r, "license", None)
            if lic is None:
                continue
            lic.is_blocked = False
            lic.block_reason = ""
            lic.save(update_fields=["is_blocked", "block_reason", "updated_at"])
            n += 1
        self.message_user(
            request, f"Разблокировано: {n}", level=messages.SUCCESS,
        )

    @action(description="🔑 Сгенерировать api_key", url_path="rotate-api-key")
    def rotate_api_key_detail(self, request, object_id: int):
        """Detail-action: кнопка прямо на странице ресторана (unfold action)."""
        from django.shortcuts import redirect

        r = Restaurant.objects.filter(id=object_id).first()
        if r is None:
            messages.error(request, "Ресторан не найден")
            return redirect("admin:users_restaurant_changelist")
        new_key = secrets.token_hex(32)
        r.api_key = new_key
        r.save(update_fields=["api_key"])
        messages.warning(
            request,
            f"Новый api_key: RESTAURANT_API_KEY={new_key} "
            f"— запиши в env ресторанного сервера, больше не отобразится.",
        )
        return redirect("admin:users_restaurant_change", object_id=r.id)

    @admin.action(description="Сгенерировать новый api_key (M2M)")
    def rotate_api_keys(self, request, queryset):
        n = 0
        last_key = None
        for r in queryset:
            r.api_key = secrets.token_hex(32)
            r.save(update_fields=["api_key"])
            last_key = r.api_key
            n += 1
        if n == 1:
            self.message_user(
                request,
                f"Сгенерирован новый api_key. RESTAURANT_API_KEY={last_key} "
                f"— запиши в env ресторанного сервера, больше не отобразится.",
                level=messages.WARNING,
            )
        else:
            self.message_user(
                request,
                f"Сгенерировано {n} новых api_key — посмотри каждый в карточке ресторана.",
                level=messages.WARNING,
            )


class UserAdminForm(forms.ModelForm):
    raw_pin = forms.CharField(
        required=False,
        max_length=6,
        label="PIN (4–6 цифр)",
        help_text="Заполнить только при создании или смене PIN. В БД хранится bcrypt-хэш.",
        widget=UnfoldAdminTextInputWidget(
            attrs={
                "autocomplete": "off",
                "inputmode": "numeric",
                "pattern": "[0-9]{4,6}",
                "maxlength": "6",
                "placeholder": "1234",
            },
        ),
    )

    class Meta:
        model = User
        fields = "__all__"

    def save(self, commit: bool = True):
        user = super().save(commit=False)
        raw_pin = self.cleaned_data.get("raw_pin")
        if raw_pin:
            if not raw_pin.isdigit() or not (4 <= len(raw_pin) <= 6):
                raise forms.ValidationError("PIN должен содержать 4–6 цифр")
            user.set_pin(raw_pin)
        if commit:
            user.save()
            self.save_m2m()
        return user


from django.contrib.auth.forms import UserCreationForm as DjangoUserCreationForm


class UserCreationFormWithRole(DjangoUserCreationForm):
    """Форма создания юзера в admin: username + password1/password2 +
    full_name + role + restaurant + raw_pin."""

    raw_pin = forms.CharField(
        required=False, max_length=6, label="PIN (4–6 цифр)",
        help_text="Опционально. Хранится bcrypt-хэшем.",
        widget=UnfoldAdminTextInputWidget(
            attrs={
                "autocomplete": "off",
                "inputmode": "numeric",
                "pattern": "[0-9]{4,6}",
                "maxlength": "6",
                "placeholder": "1234",
            },
        ),
    )

    class Meta(DjangoUserCreationForm.Meta):
        model = User
        fields = ("username", "full_name", "role", "restaurant")

    def save(self, commit: bool = True):
        user = super().save(commit=False)
        raw_pin = self.cleaned_data.get("raw_pin") or ""
        if raw_pin:
            if not raw_pin.isdigit() or not (4 <= len(raw_pin) <= 6):
                raise forms.ValidationError("PIN должен содержать 4–6 цифр")
            user.set_pin(raw_pin)
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(ModelAdmin, DjangoUserAdmin):
    form = UserAdminForm
    add_form = UserCreationFormWithRole
    list_display = ("id", "username", "full_name", "role", "restaurant", "is_active", "is_staff", "is_superuser")
    list_filter = (
        ("role", ChoicesDropdownFilter),
        "restaurant",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    list_filter_submit = False
    search_fields = ("username", "full_name")
    autocomplete_fields = ("restaurant",)
    ordering = ("id",)

    fieldsets = (
        (None, {"fields": ("username", "password", "raw_pin")}),
        ("Профиль", {"fields": ("full_name", "role", "restaurant")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("PIN-блокировка", {"fields": ("failed_pin_attempts", "locked_until")}),
        ("Даты", {"fields": ("last_login", "created_at")}),
    )
    readonly_fields = ("created_at", "last_login")

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "full_name",
                    "role",
                    "restaurant",
                    "password1",
                    "password2",
                    "raw_pin",
                ),
            },
        ),
    )


@admin.register(PinSession)
class PinSessionAdmin(ModelAdmin):
    list_display = ("id", "user", "created_at", "expires_at")
    list_filter = (
        ("user__restaurant", RelatedDropdownFilter),
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    readonly_fields = ("token", "created_at", "expires_at")
    search_fields = ("user__username", "user__full_name")
