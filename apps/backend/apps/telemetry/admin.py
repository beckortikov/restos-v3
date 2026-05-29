from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import (
    PendingTelemetrySnapshot,
    RestaurantCatalogSnapshot,
    TelemetrySnapshot,
)


@admin.register(TelemetrySnapshot)
class TelemetrySnapshotAdmin(ModelAdmin):
    list_display = (
        "id", "restaurant", "business_date",
        "daily_revenue", "daily_orders_count", "mtd_revenue",
        "last_order_at", "open_shifts_count", "app_version",
        "received_at",
    )
    list_filter = (
        ("restaurant", RelatedDropdownFilter),
        ("business_date", RangeDateFilter),
    )
    list_filter_submit = False
    autocomplete_fields = ("restaurant",)
    readonly_fields = ("received_at",)
    date_hierarchy = "business_date"
    ordering = ("-business_date", "restaurant_id")


@admin.register(RestaurantCatalogSnapshot)
class RestaurantCatalogSnapshotAdmin(ModelAdmin):
    """Каталог меню ресторана — singleton per restaurant."""

    list_display = (
        "id", "restaurant",
        "categories_count", "items_count", "active_items_count",
        "updated_at",
    )
    list_filter = (
        ("restaurant", RelatedDropdownFilter),
        ("updated_at", RangeDateFilter),
    )
    list_filter_submit = False
    autocomplete_fields = ("restaurant",)
    readonly_fields = (
        "categories_count", "items_count", "active_items_count",
        "data", "updated_at",
    )
    ordering = ("-updated_at",)


@admin.register(PendingTelemetrySnapshot)
class PendingTelemetrySnapshotAdmin(ModelAdmin):
    """Эта таблица обычно пустая на cloud-инстансе.
    Live она только на restaurant-инстансе (как буфер push'а)."""

    list_display = (
        "id", "restaurant_id", "business_date", "captured_at",
        "attempts", "last_attempt_at",
    )
    readonly_fields = (
        "restaurant_id", "business_date", "captured_at", "payload",
        "attempts", "last_attempt_at", "last_error", "created_at",
    )
    ordering = ("business_date",)
