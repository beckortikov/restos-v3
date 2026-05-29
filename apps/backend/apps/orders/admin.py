from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import (
    CancelReason,
    Discount,
    Order,
    OrderItem,
    PaymentProvider,
    RefundedItem,
    RefundOperation,
)


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = (
        "name_at_order", "price_at_order", "qty",
        "cancelled_at", "cancelled_by", "cancel_reason", "created_at",
    )
    fields = readonly_fields + ("menu_item",)
    can_delete = False


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = (
        "id", "status", "order_type", "table", "waiter", "cashier",
        "guests_count", "payment_method", "total", "created_at", "closed_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("order_type", ChoicesDropdownFilter),
        ("payment_method", ChoicesDropdownFilter),
        "restaurant",
        ("created_at", RangeDateFilter),
        ("closed_at", RangeDateFilter),
    )
    list_filter_submit = False
    search_fields = (
        "id", "comment", "idempotency_key", "customer_name", "customer_phone",
    )
    readonly_fields = (
        "idempotency_key", "created_at", "updated_at",
        "bill_requested_at", "closed_at", "cancelled_at",
    )
    autocomplete_fields = ("table", "waiter", "cashier")
    inlines = [OrderItemInline]
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50


@admin.register(Discount)
class DiscountAdmin(ModelAdmin):
    list_display = ("id", "name", "type", "kind", "value", "is_active", "sort_order")
    list_filter = (
        ("type", ChoicesDropdownFilter),
        ("kind", ChoicesDropdownFilter),
        "restaurant",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant",)
    ordering = ("sort_order", "name")


@admin.register(PaymentProvider)
class PaymentProviderAdmin(ModelAdmin):
    list_display = ("id", "name", "kind", "commission_pct", "is_active", "sort_order")
    list_filter = (
        ("kind", ChoicesDropdownFilter),
        "restaurant",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant",)
    ordering = ("sort_order", "name")


@admin.register(CancelReason)
class CancelReasonAdmin(ModelAdmin):
    list_display = ("id", "label", "kind", "is_active", "sort_order")
    list_filter = (
        ("kind", ChoicesDropdownFilter),
        "restaurant",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("label",)
    autocomplete_fields = ("restaurant",)
    ordering = ("sort_order", "label")


@admin.register(RefundOperation)
class RefundOperationAdmin(ModelAdmin):
    list_display = ("id", "order", "amount", "cashier", "created_at")
    list_filter = (
        "restaurant",
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    search_fields = ("order__id", "reason")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
