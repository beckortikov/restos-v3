from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RelatedDropdownFilter,
)

from .models import Table, TableGroup, Zone


@admin.register(Zone)
class ZoneAdmin(ModelAdmin):
    list_display = ("id", "name", "restaurant", "sort_order")
    list_filter = ("restaurant",)
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant",)
    ordering = ("restaurant", "sort_order", "name")


@admin.register(Table)
class TableAdmin(ModelAdmin):
    list_display = (
        "id", "number", "name", "zone", "capacity",
        "status", "waiter", "guests_count", "updated_at",
    )
    list_filter = (
        "restaurant",
        ("zone", RelatedDropdownFilter),
        ("status", ChoicesDropdownFilter),
    )
    list_filter_submit = False
    search_fields = ("name", "number")
    autocomplete_fields = ("zone", "waiter", "restaurant")
    readonly_fields = ("opened_at", "updated_at")
    ordering = ("restaurant", "zone__sort_order", "number")


@admin.register(TableGroup)
class TableGroupAdmin(ModelAdmin):
    list_display = ("id", "name", "restaurant", "primary_table", "created_at", "closed_at")
    list_filter = (
        "restaurant",
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant", "primary_table", "created_by")
    readonly_fields = ("created_at", "closed_at")
    ordering = ("-created_at",)
