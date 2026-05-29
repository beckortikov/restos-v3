from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import (
    Ingredient,
    IngredientStockMovement,
    SemiFinishedRecipeLine,
    SemiFinishedStockMovement,
    SemiFinishedType,
)


@admin.register(Ingredient)
class IngredientAdmin(ModelAdmin):
    list_display = (
        "id", "name", "restaurant", "unit",
        "current_qty_col", "avg_cost_per_unit",
        "low_stock_threshold", "is_active",
    )
    list_filter = (
        "restaurant",
        ("unit", ChoicesDropdownFilter),
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant",)
    readonly_fields = ("avg_cost_per_unit", "created_at", "updated_at")
    ordering = ("restaurant", "sort_order", "name")

    def current_qty_col(self, obj: Ingredient):
        qty = obj.current_qty
        if obj.is_low_stock:
            return format_html(
                '<strong style="color:#DC2626">⚠ {} {}</strong>',
                qty, obj.unit,
            )
        return format_html(
            '<span>{} {}</span>', qty, obj.unit,
        )
    current_qty_col.short_description = "Остаток"


@admin.register(IngredientStockMovement)
class IngredientStockMovementAdmin(ModelAdmin):
    """Append-only журнал. Редактировать нельзя — это event-stream."""

    list_display = (
        "id", "ingredient", "kind",
        "qty_delta_col", "unit_cost",
        "user", "order", "created_at",
    )
    list_filter = (
        ("kind", ChoicesDropdownFilter),
        ("ingredient", RelatedDropdownFilter),
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    search_fields = ("reason", "ingredient__name")
    autocomplete_fields = ("ingredient", "user", "order")
    readonly_fields = (
        "ingredient", "kind", "qty_delta", "unit_cost",
        "reason", "user", "order", "created_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def qty_delta_col(self, obj):
        q = obj.qty_delta
        if q >= 0:
            return format_html(
                '<strong style="color:#16A34A">+{}</strong>', q,
            )
        return format_html(
            '<strong style="color:#DC2626">{}</strong>', q,
        )
    qty_delta_col.short_description = "Δ"

    def has_change_permission(self, request, obj=None):
        return False  # append-only журнал

    def has_delete_permission(self, request, obj=None):
        return False


class SemiRecipeInline(TabularInline):
    model = SemiFinishedRecipeLine
    fk_name = "semi_type"  # XOR с nested_semi → нужно указать явно
    extra = 1
    fields = ("ingredient", "nested_semi", "qty_per_output", "sort_order")
    autocomplete_fields = ("ingredient", "nested_semi")


@admin.register(SemiFinishedType)
class SemiFinishedTypeAdmin(ModelAdmin):
    list_display = (
        "id", "name", "restaurant", "output_unit",
        "yield_percent", "current_qty_col", "avg_cost_per_unit",
        "is_active",
    )
    list_filter = (
        "restaurant",
        ("output_unit", ChoicesDropdownFilter),
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant",)
    readonly_fields = ("avg_cost_per_unit", "created_at", "updated_at")
    inlines = (SemiRecipeInline,)
    ordering = ("restaurant", "sort_order", "name")

    def current_qty_col(self, obj: SemiFinishedType):
        qty = obj.current_qty
        if obj.is_low_stock:
            return format_html(
                '<strong style="color:#DC2626">⚠ {} {}</strong>',
                qty, obj.output_unit,
            )
        return f"{qty} {obj.output_unit}"
    current_qty_col.short_description = "Остаток"


@admin.register(SemiFinishedStockMovement)
class SemiFinishedStockMovementAdmin(ModelAdmin):
    list_display = (
        "id", "semi_type", "kind",
        "qty_delta_col", "unit_cost",
        "user", "order", "created_at",
    )
    list_filter = (
        ("kind", ChoicesDropdownFilter),
        ("semi_type", RelatedDropdownFilter),
        ("created_at", RangeDateFilter),
    )
    list_filter_submit = False
    search_fields = ("reason", "semi_type__name")
    autocomplete_fields = ("semi_type", "user", "order")
    readonly_fields = (
        "semi_type", "kind", "qty_delta", "unit_cost",
        "reason", "user", "order", "created_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def qty_delta_col(self, obj):
        q = obj.qty_delta
        if q >= 0:
            return format_html('<strong style="color:#16A34A">+{}</strong>', q)
        return format_html('<strong style="color:#DC2626">{}</strong>', q)
    qty_delta_col.short_description = "Δ"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
