"""Сервисы меню — Phase 7E.

`record_batch_cook` — атомарная операция «cook заготовил N порций»:
  - валидирует, что блюдо is_batch_cooking;
  - списывает ингредиенты/полуфабрикаты по техкарте × N (если есть);
  - увеличивает `MenuItem.prepared_qty` на N;
  - пишет запись в `BatchCookingLog`.

`record_batch_consume` — обратная: «заказ закрыт, списали N порций»:
  - clamp prepared_qty к 0 (нельзя уйти в минус, но log пишет реальный delta);
  - запись в `BatchCookingLog` с kind=CONSUME.

Для items с `is_batch_cooking=True` `consume_for_order_close` НЕ списывает
ингредиенты по техкарте — они уже были списаны при заготовке партии.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from common.exceptions import BusinessError


@transaction.atomic
def record_batch_cook(
    menu_item,
    qty_delta: int,
    *,
    kind: str = "cook",
    user=None,
    note: str = "",
    consume_techcard: bool = True,
) -> dict:
    """Atomic: log + увеличить prepared_qty (для cook) или уменьшить (consume/correct).

    qty_delta > 0  — заготовка / коррекция в плюс.
    qty_delta < 0  — расход / коррекция в минус (clamped).

    Если `consume_techcard=True` И qty_delta > 0 И у блюда есть техкарта —
    списываем ингредиенты × qty_delta как и при close_order обычных блюд.
    """
    from .models import BatchCookingKind, BatchCookingLog, MenuItem, MenuItemTechCardLine

    if qty_delta == 0:
        raise BusinessError("INVALID_VALUE", "qty_delta не может быть 0", 400)
    if not menu_item.is_batch_cooking:
        raise BusinessError(
            "INVALID_OPERATION",
            f"{menu_item.name} не является заготовочным блюдом",
            400,
        )
    if kind not in BatchCookingKind.values:
        raise BusinessError("INVALID_VALUE", f"Неизвестный kind={kind}", 400)

    # Lock и читаем актуальный prepared_qty
    locked = MenuItem.objects.select_for_update().get(pk=menu_item.pk)
    prev_total = int(locked.prepared_qty)
    new_total_raw = prev_total + int(qty_delta)
    new_total = max(0, new_total_raw)  # PositiveIntegerField → clamp

    locked.prepared_qty = new_total
    locked.save(update_fields=["prepared_qty", "updated_at"])

    # Списать сырьё по техкарте (только для заготовки в плюс)
    consumed: list[dict] = []
    if consume_techcard and qty_delta > 0 and kind == BatchCookingKind.COOK:
        from apps.inventory.services import (
            record_movement as _rm,
            record_semi_movement as _rsm,
        )
        from apps.inventory.models import (
            SemiStockMovementKind as _SSMK,
            StockMovementKind as _SMK,
        )

        lines = list(
            MenuItemTechCardLine.objects
            .filter(menu_item=locked)
            .select_related("ingredient", "nested_semi")
        )
        for line in lines:
            total_qty = Decimal(str(line.qty_per_unit)) * Decimal(str(qty_delta))
            if line.ingredient is not None:
                _rm(
                    ingredient=line.ingredient,
                    kind=_SMK.CONSUME,
                    qty_delta=-total_qty,
                    reason=f"Заготовка: {locked.name} × {qty_delta}",
                    user=user,
                )
                consumed.append({
                    "component": line.ingredient.name,
                    "qty": str(total_qty),
                    "kind": "ingredient",
                })
            elif line.nested_semi is not None:
                _rsm(
                    semi_type=line.nested_semi,
                    kind=_SSMK.CONSUME_FOR_DISH,
                    qty_delta=-total_qty,
                    reason=f"Заготовка: {locked.name} × {qty_delta}",
                    user=user,
                )
                consumed.append({
                    "component": line.nested_semi.name,
                    "qty": str(total_qty),
                    "kind": "semi",
                })

    log = BatchCookingLog.objects.create(
        menu_item=locked,
        qty_delta=int(qty_delta),
        new_total=new_total,
        kind=kind,
        user=user,
        note=note or "",
    )
    shortfall = max(0, -new_total_raw)  # сколько НЕ хватило (если ушли в минус)
    return {
        "log_id": log.id,
        "new_total": new_total,
        "prev_total": prev_total,
        "qty_delta": int(qty_delta),
        "shortfall": shortfall,
        "consumed": consumed,
    }


@transaction.atomic
def writeoff_prepared_batch(
    menu_item,
    qty: int,
    *,
    reason: str,
    user=None,
) -> dict:
    """Phase 8C — списать N испорченных готовых порций (без consume техкарты).

    Используется когда заготовленная партия испортилась/просрочилась.
    Отличается от close_order consume тем, что это ручное событие cook'а.
    """
    if qty <= 0:
        raise BusinessError("INVALID_VALUE", "qty должно быть > 0", 400)
    if not reason or not reason.strip():
        raise BusinessError("INVALID_VALUE", "Причина обязательна", 400)
    return record_batch_cook(
        menu_item,
        qty_delta=-int(qty),
        kind="correct",
        user=user,
        note=f"Списание порции: {reason.strip()}",
        consume_techcard=False,
    )


def record_batch_consume_for_order(order, *, user=None) -> list[dict]:
    """Для каждого OrderItem, у которого menu_item.is_batch_cooking, вычесть
    prepared_qty (clamped) и записать BatchCookingLog kind=CONSUME.

    Возвращает summary: [{menu_item, qty_delta, new_total, shortfall}].
    Если prepared_qty < ordered_qty — clamp, но shortfall > 0 фиксируем.
    Не бросает — это «информативный» расход, для предупреждения cook'а.
    """
    from .models import BatchCookingKind

    summary: list[dict] = []
    # Phase 8E — skip-already-consumed (списано при create_order/add_items_to_order).
    items = order.items.filter(
        cancelled_at__isnull=True,
        consumed_at__isnull=True,
    ).select_related("menu_item")
    for oi in items:
        mi = oi.menu_item
        if mi is None or not mi.is_batch_cooking:
            continue
        try:
            qty = int(oi.qty or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        result = record_batch_cook(
            mi,
            qty_delta=-qty,
            kind=BatchCookingKind.CONSUME,
            user=user,
            note=f"Заказ #{order.id}",
            consume_techcard=False,
        )
        summary.append({
            "menu_item": mi.name,
            "qty_delta": -qty,
            "new_total": result["new_total"],
            "shortfall": result["shortfall"],
        })
        # Phase 8E — пометить «уже списано» (consume_for_order_close её тоже пропустит).
        from django.utils import timezone as _tz
        oi.consumed_at = _tz.now()
        oi.save(update_fields=["consumed_at"])
    return summary
