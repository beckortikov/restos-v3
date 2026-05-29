from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(ModelAdmin):
    list_display = (
        "id", "created_at", "action", "user", "user_full_name",
        "target_type", "target_id", "ip_address",
    )
    list_filter = (
        ("action", ChoicesDropdownFilter),
        ("user__restaurant", RelatedDropdownFilter),
        ("user", RelatedDropdownFilter),
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    search_fields = ("user_full_name", "target_type", "ip_address")
    readonly_fields = (
        "user", "user_full_name", "action",
        "target_type", "target_id",
        "payload", "ip_address", "created_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False  # audit-журнал — только append через сервисы

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
