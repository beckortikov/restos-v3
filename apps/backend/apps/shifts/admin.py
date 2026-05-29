from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import CashShift, CashShiftOperation


class CashShiftOperationInline(TabularInline):
    model = CashShiftOperation
    extra = 0
    readonly_fields = ("created_at", "created_by")
    fields = ("kind", "amount", "reason", "created_by", "created_at")


@admin.register(CashShift)
class CashShiftAdmin(ModelAdmin):
    list_display = (
        "id", "number", "status", "cashier", "restaurant",
        "opening_balance", "closing_balance", "actual_balance",
        "opened_at", "closed_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        "restaurant",
        ("opened_at", RangeDateFilter),
        ("closed_at", RangeDateFilter),
    )
    list_filter_submit = False
    readonly_fields = ("opened_at", "closed_at")
    search_fields = ("number", "note")
    autocomplete_fields = ("cashier", "restaurant")
    inlines = [CashShiftOperationInline]
    date_hierarchy = "opened_at"
    ordering = ("-opened_at",)


@admin.register(CashShiftOperation)
class CashShiftOperationAdmin(ModelAdmin):
    list_display = ("id", "shift", "kind", "amount", "reason", "created_at")
    list_filter = (
        ("kind", ChoicesDropdownFilter),
        ("shift__restaurant", RelatedDropdownFilter),
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    readonly_fields = ("created_at",)
    autocomplete_fields = ("shift", "created_by")
    date_hierarchy = "created_at"
