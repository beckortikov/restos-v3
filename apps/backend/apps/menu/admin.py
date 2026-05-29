from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)

from .models import (
    Category,
    MenuItem,
    MenuItemNote,
    MenuItemTechCardLine,
    Modifier,
    ModifierGroup,
)


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("id", "name", "restaurant", "print_station", "sort_order")
    list_filter = (
        "restaurant",
        ("print_station", RelatedDropdownFilter),
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant", "print_station")
    ordering = ("restaurant", "sort_order", "name")


class MenuItemTechCardInline(TabularInline):
    """Inline-редактор техкарты на странице блюда (Phase 7C)."""

    model = MenuItemTechCardLine
    fk_name = "menu_item"
    extra = 1
    fields = ("ingredient", "nested_semi", "qty_per_unit", "sort_order")
    autocomplete_fields = ("ingredient", "nested_semi")


@admin.register(MenuItem)
class MenuItemAdmin(ModelAdmin):
    list_display = (
        "id", "name", "category", "restaurant",
        "price", "cogs", "kind", "unit", "is_available", "sort_order",
    )
    list_filter = (
        "restaurant",
        ("category", RelatedDropdownFilter),
        ("kind", ChoicesDropdownFilter),
        ("unit", ChoicesDropdownFilter),
        "is_available",
        "is_purchased",
        "is_batch_cooking",
    )
    list_filter_submit = False
    search_fields = ("name", "emoji")
    list_editable = ("is_available", "sort_order")
    autocomplete_fields = ("category", "restaurant")
    filter_horizontal = ("modifier_groups",)
    inlines = (MenuItemTechCardInline,)
    ordering = ("restaurant", "category__sort_order", "sort_order")


@admin.register(MenuItemNote)
class MenuItemNoteAdmin(ModelAdmin):
    list_display = ("id", "label", "restaurant", "is_active", "sort_order")
    list_filter = (
        "restaurant",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("label",)
    autocomplete_fields = ("restaurant",)
    ordering = ("sort_order", "label")


class ModifierInline(TabularInline):
    model = Modifier
    extra = 1
    fields = ("name", "price_delta", "sort_order", "is_active")
    ordering = ("sort_order",)


@admin.register(ModifierGroup)
class ModifierGroupAdmin(ModelAdmin):
    list_display = (
        "id", "name", "restaurant",
        "min_select", "max_select", "is_required", "is_active",
    )
    list_filter = (
        "restaurant",
        "is_required",
        "is_active",
    )
    list_filter_submit = False
    search_fields = ("name",)
    autocomplete_fields = ("restaurant",)
    inlines = (ModifierInline,)
    ordering = ("sort_order", "name")
