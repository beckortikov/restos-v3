from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import PayrollPeriod, TimeEntry


@admin.register(TimeEntry)
class TimeEntryAdmin(ModelAdmin):
    list_display = (
        "id", "user", "restaurant", "clock_in", "clock_out",
        "status", "hourly_rate_snapshot",
    )
    list_filter = ("restaurant", "status")
    search_fields = ("user__full_name", "user__username", "note")
    autocomplete_fields = ("user", "restaurant")
    date_hierarchy = "clock_in"


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(ModelAdmin):
    list_display = (
        "id", "user", "restaurant", "period_start", "period_end",
        "hours_worked", "total", "status",
    )
    list_filter = ("restaurant", "status")
    search_fields = ("user__full_name", "user__username")
    autocomplete_fields = ("user", "restaurant")
    readonly_fields = ("base_salary", "total", "paid_at", "paid_operation_id")
