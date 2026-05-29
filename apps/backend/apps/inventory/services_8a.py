"""Phase 8A — сервисы для накладных, списаний, расхода и инвентаризации.

Все операции, меняющие склад, проходят через `record_movement` —
event-stream pattern сохраняется.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from common.exceptions import BusinessError

from .models import (
    DocumentStatus,
    InventoryCheck,
    StockMovementKind,
    StockReceipt,
    StockWriteoff,
    SupplyExpense,
    SupplyExpenseReason,
)
from .services import record_movement


@transaction.atomic
def apply_receipt(receipt: StockReceipt, *, user=None) -> StockReceipt:
    """Провести накладную → создать PURCHASE движения по всем линиям."""
    if receipt.status == DocumentStatus.APPLIED:
        raise BusinessError(
            "INVALID_STATE", "Накладная уже проведена", 400,
        )
    lines = list(receipt.lines.select_related("ingredient"))
    if not lines:
        raise BusinessError("INVALID_STATE", "В накладной нет позиций", 400)

    for ln in lines:
        if ln.qty <= 0:
            raise BusinessError(
                "INVALID_VALUE",
                f"Кол-во должно быть > 0 ({ln.ingredient.name})", 400,
            )
        if ln.unit_cost < 0:
            raise BusinessError(
                "INVALID_VALUE",
                f"Цена не может быть < 0 ({ln.ingredient.name})", 400,
            )
        if ln.ingredient.restaurant_id != receipt.restaurant_id:
            raise BusinessError(
                "INVALID_VALUE",
                f"Ингредиент {ln.ingredient.name} не из вашего ресторана", 400,
            )

    for ln in lines:
        record_movement(
            ingredient=ln.ingredient,
            kind=StockMovementKind.PURCHASE,
            qty_delta=Decimal(str(ln.qty)),
            unit_cost=Decimal(str(ln.unit_cost)),
            reason=(
                f"Накладная #{receipt.id} от {receipt.receipt_date}"
                + (f" ({receipt.supplier.name})" if receipt.supplier else "")
            ),
            user=user,
        )

    receipt.status = DocumentStatus.APPLIED
    receipt.applied_at = timezone.now()
    receipt.save(update_fields=["status", "applied_at", "updated_at"])
    return receipt


@transaction.atomic
def apply_writeoff(writeoff: StockWriteoff, *, user=None) -> StockWriteoff:
    """Провести списание → WASTE-движения."""
    if writeoff.status == DocumentStatus.APPLIED:
        raise BusinessError("INVALID_STATE", "Списание уже проведено", 400)
    lines = list(writeoff.lines.select_related("ingredient"))
    if not lines:
        raise BusinessError("INVALID_STATE", "В списании нет позиций", 400)

    for ln in lines:
        if ln.qty <= 0:
            raise BusinessError(
                "INVALID_VALUE",
                f"Кол-во должно быть > 0 ({ln.ingredient.name})", 400,
            )
        if ln.ingredient.restaurant_id != writeoff.restaurant_id:
            raise BusinessError(
                "INVALID_VALUE",
                f"Ингредиент {ln.ingredient.name} не из вашего ресторана", 400,
            )

    for ln in lines:
        record_movement(
            ingredient=ln.ingredient,
            kind=StockMovementKind.WASTE,
            qty_delta=-Decimal(str(ln.qty)),
            reason=f"Списание #{writeoff.id}: {writeoff.get_reason_display()}",
            user=user,
        )

    writeoff.status = DocumentStatus.APPLIED
    writeoff.applied_at = timezone.now()
    writeoff.save(update_fields=["status", "applied_at", "updated_at"])
    return writeoff


@transaction.atomic
def record_supply_expense(
    *,
    restaurant,
    ingredient,
    qty: Decimal,
    reason: str = SupplyExpenseReason.HOUSEHOLD,
    note: str = "",
    user=None,
) -> SupplyExpense:
    """Зафиксировать расход хозтовара. Атомарно: SupplyExpense + CONSUME-движение.

    Если `restaurant.supply_allow_negative=False` и склада не хватает —
    бросаем `INSUFFICIENT_STOCK`. Это защита от «выдали 10 рулонов когда
    в наличии 3».
    """
    if qty <= 0:
        raise BusinessError("INVALID_VALUE", "Кол-во должно быть > 0", 400)
    if ingredient.restaurant_id != restaurant.id:
        raise BusinessError(
            "INVALID_VALUE", "Ингредиент не из вашего ресторана", 400,
        )
    if not getattr(restaurant, "supply_allow_negative", False):
        current = ingredient.current_qty
        if current < qty:
            raise BusinessError(
                "INSUFFICIENT_STOCK",
                f"Недостаточно {ingredient.name}: остаток {current}, "
                f"требуется {qty}", 409,
            )

    expense = SupplyExpense.objects.create(
        restaurant=restaurant,
        ingredient=ingredient,
        qty=Decimal(str(qty)),
        reason=reason,
        note=note or "",
        user=user,
    )
    record_movement(
        ingredient=ingredient,
        kind=StockMovementKind.CONSUME,
        qty_delta=-Decimal(str(qty)),
        reason=f"Расход хозтовара: {expense.get_reason_display()}"
               + (f" — {note}" if note else ""),
        user=user,
        allow_negative=getattr(restaurant, "supply_allow_negative", False),
    )
    return expense


@transaction.atomic
def apply_inventory_check(check: InventoryCheck, *, user=None) -> InventoryCheck:
    """Провести инвентаризацию → INVENTORY_CORRECT-движения для расхождений."""
    if check.status == DocumentStatus.APPLIED:
        raise BusinessError(
            "INVALID_STATE", "Инвентаризация уже проведена", 400,
        )
    lines = list(check.lines.select_related("ingredient"))
    if not lines:
        raise BusinessError("INVALID_STATE", "В инвентаризации нет позиций", 400)

    for ln in lines:
        if ln.actual_qty < 0:
            raise BusinessError(
                "INVALID_VALUE",
                f"Фактический остаток < 0 ({ln.ingredient.name})", 400,
            )
        if ln.ingredient.restaurant_id != check.restaurant_id:
            raise BusinessError(
                "INVALID_VALUE",
                f"Ингредиент {ln.ingredient.name} не из вашего ресторана", 400,
            )

    for ln in lines:
        # Сравниваем actual с current_qty НА МОМЕНТ APPLY (а не expected,
        # которое могло устареть, если черновик висел долго).
        current = ln.ingredient.current_qty
        diff = Decimal(str(ln.actual_qty)) - current
        if diff == 0:
            continue
        record_movement(
            ingredient=ln.ingredient,
            kind=StockMovementKind.INVENTORY_CORRECT,
            qty_delta=diff,
            reason=f"Инвентаризация #{check.id} от {check.check_date}",
            user=user,
        )

    check.status = DocumentStatus.APPLIED
    check.applied_at = timezone.now()
    check.save(update_fields=["status", "applied_at", "updated_at"])
    return check


def populate_inventory_check_from_stock(check: InventoryCheck) -> int:
    """Заполнить InventoryCheckLine текущими остатками из stock.

    `expected_qty` = current_qty в момент создания. `actual_qty` = expected
    (пользователь редактирует actual в UI). Возвращает кол-во созданных строк.
    """
    from .models import Ingredient, InventoryCheckLine

    qs = Ingredient.objects.filter(
        restaurant=check.restaurant, is_active=True,
    )
    if check.is_food is True:
        qs = qs.filter(is_food=True)
    elif check.is_food is False:
        qs = qs.filter(is_food=False)
    lines = []
    for ing in qs:
        current = ing.current_qty
        lines.append(InventoryCheckLine(
            inventory_check=check,
            ingredient=ing,
            expected_qty=current,
            actual_qty=current,
        ))
    InventoryCheckLine.objects.bulk_create(lines)
    return len(lines)
