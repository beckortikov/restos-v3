from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import Reservation


@admin.register(Reservation)
class ReservationAdmin(ModelAdmin):
    list_display = (
        "id", "scheduled_at", "table", "customer_name",
        "customer_phone", "party_size", "status",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        "restaurant",
        ("table", RelatedDropdownFilter),
        ("scheduled_at", RangeDateFilter),
    )
    list_filter_submit = False
    search_fields = ("customer_name", "customer_phone", "notes")
    autocomplete_fields = ("restaurant", "table", "created_by")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "scheduled_at"
    ordering = ("scheduled_at",)
