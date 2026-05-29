"""Авто-стоп блюд при нехватке ингредиентов/полуфабрикатов (Phase 8D).

Правила:
- Блюдо с `auto_consume=True` и непустой техкартой → считается «отслеживаемым».
- При любом stock movement, после commit'а, для каждого затронутого
  ingredient/semi ищем все отслеживаемые MenuItem и пересчитываем
  «хватает ли на 1 порцию». Если нет — auto_stopped=True, is_available=False.
- Если хватает и блюдо было `auto_stopped=True` — восстанавливаем.
- Ручной стоп (`auto_stopped=False`, `is_available=False`) — не трогаем.
- `allow_oversell=True` — игнорируем (менеджер разрешил «в минус»).
- `auto_consume=False` или пустая техкарта — пропускаем.

Триггер: `transaction.on_commit(...)` из record_movement / record_semi_movement.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction


def _has_enough_for_one_portion(menu_item) -> tuple[bool, str]:
    """Хватает ли остатков на 1 порцию блюда?

    Возвращает (enough, missing_component_name).
    Если техкарты нет — (True, "") (нечего отслеживать).
    """
    from .models import MenuItemTechCardLine

    lines = list(
        MenuItemTechCardLine.objects
        .filter(menu_item=menu_item)
        .select_related("ingredient", "nested_semi")
    )
    if not lines:
        return True, ""
    for line in lines:
        comp = line.ingredient or line.nested_semi
        if comp is None:
            continue
        need = Decimal(str(line.qty_per_unit))
        have = Decimal(str(comp.current_qty))
        if have < need:
            return False, comp.name
    return True, ""


@transaction.atomic
def reconcile_menu_item_stop(menu_item) -> dict:
    """Пересчитать авто-стоп для одного блюда.

    Возвращает {action: "stopped"|"restored"|"noop", reason: str}.
    """
    from .models import MenuItem

    # Перечитываем под локом, чтобы не гонять с параллельными движениями.
    mi = MenuItem.objects.select_for_update().get(pk=menu_item.pk)

    if not mi.auto_consume:
        return {"action": "noop", "reason": "auto_consume=False"}
    if mi.allow_oversell:
        # Принудительный override — если был авто-стоп, снимаем.
        if mi.auto_stopped:
            mi.is_available = True
            mi.auto_stopped = False
            mi.stop_reason = ""
            mi.stop_until = None
            mi.save(update_fields=[
                "is_available", "auto_stopped",
                "stop_reason", "stop_until", "updated_at",
            ])
            return {"action": "restored", "reason": "allow_oversell"}
        return {"action": "noop", "reason": "allow_oversell=True"}

    enough, missing = _has_enough_for_one_portion(mi)

    if not enough:
        # Не хватает → авто-стоп. Ручной стоп не перезаписываем
        # (auto_stopped=False + is_available=False — оставляем как есть).
        if not mi.is_available and not mi.auto_stopped:
            return {"action": "noop", "reason": "manual stop"}
        new_reason = f"Авто-стоп: нет «{missing}»"
        if mi.is_available or mi.stop_reason != new_reason or not mi.auto_stopped:
            mi.is_available = False
            mi.auto_stopped = True
            mi.stop_reason = new_reason
            mi.stop_until = None
            mi.save(update_fields=[
                "is_available", "auto_stopped",
                "stop_reason", "stop_until", "updated_at",
            ])
            return {"action": "stopped", "reason": new_reason}
        return {"action": "noop", "reason": "already stopped"}

    # Хватает. Если в авто-стопе — снимаем. Ручной стоп оставляем.
    if mi.auto_stopped:
        mi.is_available = True
        mi.auto_stopped = False
        mi.stop_reason = ""
        mi.stop_until = None
        mi.save(update_fields=[
            "is_available", "auto_stopped",
            "stop_reason", "stop_until", "updated_at",
        ])
        return {"action": "restored", "reason": "stock available"}

    return {"action": "noop", "reason": "available"}


def reconcile_for_ingredient(ingredient) -> list[dict]:
    """Пересчитать авто-стоп для всех блюд, где этот ingredient в техкарте
    напрямую ИЛИ опосредованно через nested_semi (рецепт п/ф).
    """
    from apps.inventory.models import SemiFinishedRecipeLine

    from .models import MenuItem, MenuItemTechCardLine

    direct_ids = set(
        MenuItemTechCardLine.objects
        .filter(ingredient=ingredient)
        .values_list("menu_item_id", flat=True)
    )
    # Косвенно: ingredient → semi (recipe_lines) → MenuItemTechCardLine.nested_semi
    semi_ids = set(
        SemiFinishedRecipeLine.objects
        .filter(ingredient=ingredient)
        .values_list("semi_type_id", flat=True)
    )
    indirect_ids = set(
        MenuItemTechCardLine.objects
        .filter(nested_semi_id__in=semi_ids)
        .values_list("menu_item_id", flat=True)
    )
    all_ids = direct_ids | indirect_ids
    if not all_ids:
        return []
    items = MenuItem.objects.filter(id__in=all_ids).select_related("restaurant")
    return [
        {"menu_item_id": mi.id, **reconcile_menu_item_stop(mi)}
        for mi in items
    ]


def reconcile_for_semi(semi_type) -> list[dict]:
    """Пересчитать авто-стоп для всех блюд, где этот semi в техкарте."""
    from .models import MenuItem, MenuItemTechCardLine

    ids = set(
        MenuItemTechCardLine.objects
        .filter(nested_semi=semi_type)
        .values_list("menu_item_id", flat=True)
    )
    if not ids:
        return []
    items = MenuItem.objects.filter(id__in=ids)
    return [
        {"menu_item_id": mi.id, **reconcile_menu_item_stop(mi)}
        for mi in items
    ]
