from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import Printer, PrintJob, PrintStation


@admin.register(PrintStation)
class PrintStationAdmin(ModelAdmin):
    list_display = ("id", "name", "restaurant", "system_code", "is_active", "sort_order")
    list_filter = (
        "restaurant",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name", "system_code")
    autocomplete_fields = ("restaurant",)
    ordering = ("sort_order", "name")


@admin.register(Printer)
class PrinterAdmin(ModelAdmin):
    list_display = (
        "id", "name", "restaurant", "kind", "address",
        "paper_size", "is_default", "is_active",
    )
    list_filter = (
        "restaurant",
        ("kind", ChoicesDropdownFilter),
        ("paper_size", ChoicesDropdownFilter),
        "is_default",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name", "address")
    autocomplete_fields = ("restaurant",)


@admin.register(PrintJob)
class PrintJobAdmin(ModelAdmin):
    list_display = (
        "id", "restaurant", "order", "kind", "status",
        "retries", "printer", "scheduled_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("kind", ChoicesDropdownFilter),
        "restaurant",
        ("printer", RelatedDropdownFilter),
        ("scheduled_at", RangeDateFilter),
    )
    list_filter_submit = False
    readonly_fields = ("scheduled_at", "started_at", "finished_at")
    search_fields = ("error",)
    autocomplete_fields = ("restaurant", "printer", "order")
    date_hierarchy = "scheduled_at"
    ordering = ("-scheduled_at",)
