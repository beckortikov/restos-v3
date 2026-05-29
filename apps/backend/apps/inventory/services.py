"""Сервисы склада: запись движений + пересчёт средней цены.

Главная функция — `record_movement`. Любое изменение остатка должно
проходить через неё. Прямой `IngredientStockMovement.objects.create()`
работает технически, но не обновляет `Ingredient.avg_cost_per_unit`
для приёмок.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from common.exceptions import BusinessError

from .models import (
    Ingredient,
    IngredientStockMovement,
    StockMovementKind,
)

if TYPE_CHECKING:
    from apps.users.models import User

# Знак qty_delta по типу движения. None = разрешён любой знак.
_SIGN_BY_KIND = {
    StockMovementKind.PURCHASE: "positive",
    StockMovementKind.CONSUME: "negative",
    StockMovementKind.PRODUCE_SEMI: "negative",
    StockMovementKind.WASTE: "negative",
    StockMovementKind.RETURN_TO_SUPPLIER: "negative",
    StockMovementKind.INVENTORY_CORRECT: None,  # ±
    StockMovementKind.MANUAL: None,
}


@transaction.atomic
def record_movement(
    *,
    ingredient: Ingredient,
    kind: str,
    qty_delta: Decimal | str | int | float,
    unit_cost: Decimal | str | None = None,
    reason: str = "",
    user: "User | None" = None,
    order=None,
    allow_negative: bool = False,
) -> IngredientStockMovement:
    """Главный API для изменения остатка.

    - Проверяет знак qty_delta согласно kind (purchase >0, consume <0, и т.д.)
    - При kind=purchase обновляет Ingredient.avg_cost_per_unit как weighted avg
    - Создаёт IngredientStockMovement (event)
    - Защищает от отрицательного остатка для consume / waste (опц.)
    """
    if kind not in StockMovementKind.values:
        raise BusinessError(
            "INVALID_VALUE", f"Неизвестный kind: {kind!r}", 400,
        )
    try:
        qty_delta = Decimal(str(qty_delta))
    except Exception as exc:
        raise BusinessError(
            "INVALID_VALUE", f"qty_delta должен быть число: {qty_delta!r}", 400,
        ) from exc

    if qty_delta == 0:
        raise BusinessError(
            "INVALID_VALUE", "qty_delta не может быть 0", 400,
        )

    # Проверка знака для типов с фиксированным направлением
    expected = _SIGN_BY_KIND.get(kind)
    if expected == "positive" and qty_delta <= 0:
        raise BusinessError(
            "INVALID_SIGN",
            f"Для {kind} qty_delta должен быть > 0", 400,
        )
    if expected == "negative" and qty_delta >= 0:
        raise BusinessError(
            "INVALID_SIGN",
            f"Для {kind} qty_delta должен быть < 0 (расход)", 400,
        )

    # Защита от отрицательного остатка (можно отключать в settings, но
    # дефолтно — не даём уйти в минус).
    if qty_delta < 0 and not allow_negative:
        from django.conf import settings

        if getattr(settings, "INVENTORY_PREVENT_NEGATIVE", True):
            current = ingredient.current_qty
            if current + qty_delta < 0:
                raise BusinessError(
                    "INSUFFICIENT_STOCK",
                    f"Недостаточный остаток «{ingredient.name}»: "
                    f"в наличии {current}, расход {qty_delta}",
                    422,
                )

    # Weighted average cost — пересчитываем при purchase
    if kind == StockMovementKind.PURCHASE and unit_cost is not None:
        try:
            new_unit_cost = Decimal(str(unit_cost))
        except Exception as exc:
            raise BusinessError(
                "INVALID_VALUE", f"unit_cost должен быть число: {unit_cost!r}", 400,
            ) from exc
        # qty_old × cost_old + qty_new × cost_new) / (qty_old + qty_new)
        # Берём остаток ДО этой приёмки.
        old_qty = ingredient.current_qty
        old_cost = ingredient.avg_cost_per_unit
        total_qty = old_qty + qty_delta
        if total_qty > 0:
            weighted = (
                (old_qty * old_cost + qty_delta * new_unit_cost) / total_qty
            )
            ingredient.avg_cost_per_unit = weighted.quantize(Decimal("0.0001"))
            ingredient.save(update_fields=["avg_cost_per_unit", "updated_at"])

    mv = IngredientStockMovement.objects.create(
        ingredient=ingredient,
        kind=kind,
        qty_delta=qty_delta,
        unit_cost=Decimal(str(unit_cost)) if unit_cost is not None else None,
        reason=reason[:255],
        user=user,
        order=order,
    )

    # Phase 8D — авто-стоп блюд после commit'а. Только если qty_delta
    # реально мог сдвинуть остаток (любое ненулевое движение).
    def _reconcile_after_commit(ing_id=ingredient.id):
        from apps.menu.services_autostop import reconcile_for_ingredient
        from .models import Ingredient as _Ing

        try:
            ing = _Ing.objects.get(pk=ing_id)
            reconcile_for_ingredient(ing)
        except Exception:
            pass
    transaction.on_commit(_reconcile_after_commit)

    # Audit-log: записать в audit-журнал если user известен
    if user is not None:
        try:
            from apps.audit.services import audit_log
            audit_log(
                user, "settings_update", target=ingredient,
                payload={
                    "action": "stock_movement",
                    "ingredient": ingredient.name,
                    "kind": kind,
                    "qty_delta": str(qty_delta),
                    "reason": reason[:100],
                },
            )
        except Exception:
            # Не падаем если audit недоступен
            pass

    return mv


def get_low_stock_ingredients(restaurant) -> list[Ingredient]:
    """Список ингредиентов которые «заканчиваются» (current_qty ≤ threshold)."""
    items = list(
        Ingredient.objects.filter(
            restaurant=restaurant, is_active=True,
            low_stock_threshold__isnull=False,
        )
    )
    return [i for i in items if i.is_low_stock]


@transaction.atomic
def record_semi_movement(
    *,
    semi_type,
    kind: str,
    qty_delta,
    reason: str = "",
    user=None,
    order=None,
):
    """Записать движение п/ф напрямую (waste / inventory_correct / consume).

    Для produce используется `produce_semi()` — он сложнее (рецепт + ингредиенты).
    """
    from .models import SemiFinishedStockMovement, SemiStockMovementKind

    if kind not in SemiStockMovementKind.values:
        raise BusinessError("INVALID_VALUE", f"Неизвестный kind: {kind!r}", 400)
    try:
        qty_delta = Decimal(str(qty_delta))
    except Exception as exc:
        raise BusinessError("INVALID_VALUE", "qty_delta не число", 400) from exc
    if qty_delta == 0:
        raise BusinessError("INVALID_VALUE", "qty_delta не может быть 0", 400)

    if qty_delta < 0:
        from django.conf import settings as _s

        if getattr(_s, "INVENTORY_PREVENT_NEGATIVE", True):
            cur = semi_type.current_qty
            if cur + qty_delta < 0:
                raise BusinessError(
                    "INSUFFICIENT_STOCK",
                    f"Недостаточный остаток п/ф «{semi_type.name}»: "
                    f"в наличии {cur}, расход {qty_delta}",
                    422,
                )

    mv = SemiFinishedStockMovement.objects.create(
        semi_type=semi_type,
        kind=kind, qty_delta=qty_delta,
        reason=reason[:255],
        user=user, order=order,
    )

    def _reconcile_semi_after_commit(semi_id=semi_type.id):
        from apps.menu.services_autostop import reconcile_for_semi
        from .models import SemiFinishedType as _Semi

        try:
            sem = _Semi.objects.get(pk=semi_id)
            reconcile_for_semi(sem)
        except Exception:
            pass
    transaction.on_commit(_reconcile_semi_after_commit)
    return mv


@transaction.atomic
def produce_semi(
    *,
    semi_type,
    qty,
    reason: str = "",
    user=None,
):
    """Произвести `qty` единиц полуфабриката из ингредиентов по рецепту.

    Полная атомарность: либо все компоненты успешно списались + п/ф появился,
    либо ничего не изменилось.

    1. Берёт `semi_type.recipe_lines`.
    2. С учётом `yield_percent` рассчитывает фактический расход компонентов
       (yield=80% → нужно 1/0.8 = 1.25× компонентов на 1 unit выхода).
    3. Проверяет что всех компонентов хватает.
    4. Списывает компоненты (ingredient → record_movement,
       nested_semi → record_semi_movement).
    5. Считает суммарную себестоимость партии.
    6. Создаёт PRODUCE-event на сам п/ф + обновляет avg_cost weighted.
    """
    from .models import (
        SemiFinishedStockMovement,
        SemiStockMovementKind,
        StockMovementKind,
    )

    try:
        qty = Decimal(str(qty))
    except Exception as exc:
        raise BusinessError("INVALID_VALUE", "qty не число", 400) from exc
    if qty <= 0:
        raise BusinessError("INVALID_VALUE", "qty должен быть > 0", 400)

    recipe = list(
        semi_type.recipe_lines.select_related("ingredient", "nested_semi")
    )
    if not recipe:
        raise BusinessError(
            "EMPTY_RECIPE",
            f"У полуфабриката «{semi_type.name}» не задан рецепт",
            422,
        )

    yield_pct = Decimal(str(semi_type.yield_percent or 100))
    if yield_pct <= 0:
        raise BusinessError(
            "INVALID_VALUE", "yield_percent должен быть > 0", 422,
        )
    yield_ratio = yield_pct / Decimal("100")

    # 1. Pre-flight check — все компоненты доступны (атомарность).
    batch_cost = Decimal("0")
    for line in recipe:
        component_qty = (qty * line.qty_per_output) / yield_ratio
        comp = line.ingredient or line.nested_semi
        if comp.current_qty < component_qty:
            raise BusinessError(
                "INSUFFICIENT_STOCK",
                f"Не хватает «{comp.name}»: нужно {component_qty}, "
                f"в наличии {comp.current_qty}",
                422,
            )
        batch_cost += component_qty * comp.avg_cost_per_unit

    # 2. Списываем компоненты
    for line in recipe:
        component_qty = (qty * line.qty_per_output) / yield_ratio
        if line.ingredient is not None:
            record_movement(
                ingredient=line.ingredient,
                kind=StockMovementKind.PRODUCE_SEMI,
                qty_delta=-component_qty,
                reason=f"Варка п/ф «{semi_type.name}» × {qty}",
                user=user,
            )
        else:
            record_semi_movement(
                semi_type=line.nested_semi,
                kind=SemiStockMovementKind.CONSUME_FOR_DISH,
                qty_delta=-component_qty,
                reason=f"Варка п/ф «{semi_type.name}» × {qty}",
                user=user,
            )

    # 3. Производим п/ф — weighted avg cost обновляем
    unit_cost = (batch_cost / qty).quantize(Decimal("0.0001")) if qty > 0 else Decimal("0")
    old_qty = semi_type.current_qty
    old_cost = semi_type.avg_cost_per_unit
    total_qty = old_qty + qty
    if total_qty > 0:
        new_avg = (old_qty * old_cost + qty * unit_cost) / total_qty
        semi_type.avg_cost_per_unit = new_avg.quantize(Decimal("0.0001"))
        semi_type.save(update_fields=["avg_cost_per_unit", "updated_at"])

    mv = SemiFinishedStockMovement.objects.create(
        semi_type=semi_type,
        kind=SemiStockMovementKind.PRODUCE,
        qty_delta=qty,
        unit_cost=unit_cost,
        reason=reason[:255] or f"Произведено {qty} {semi_type.output_unit}",
        user=user,
    )

    def _reconcile_after_produce(semi_id=semi_type.id):
        from apps.menu.services_autostop import reconcile_for_semi
        from .models import SemiFinishedType as _Semi
        try:
            reconcile_for_semi(_Semi.objects.get(pk=semi_id))
        except Exception:
            pass
    transaction.on_commit(_reconcile_after_produce)
    if user is not None:
        try:
            from apps.audit.services import audit_log
            audit_log(
                user, "settings_update", target=semi_type,
                payload={
                    "action": "produce_semi",
                    "semi": semi_type.name,
                    "qty": str(qty),
                    "batch_cost": str(batch_cost),
                    "unit_cost": str(unit_cost),
                },
            )
        except Exception:
            pass
    return mv


# ──────────────────────── Phase 7C: Tech cards ───────────────────────────


def calculate_techcard_cogs(menu_item) -> Decimal:
    """Себестоимость 1 единицы блюда из техкарты.

    Σ(line.qty_per_unit × component.avg_cost_per_unit).
    Если у блюда нет техкарты — возвращает 0. Admin может установить cogs
    вручную через PATCH MenuItem; но если в техкарту что-то добавляли и
    потом удалили — cogs сбрасывается в 0 (явный признак «нет рецепта»).
    """
    from apps.menu.models import MenuItemTechCardLine

    lines = (
        MenuItemTechCardLine.objects
        .filter(menu_item=menu_item)
        .select_related("ingredient", "nested_semi")
    )
    total = Decimal("0")
    for line in lines:
        comp = line.ingredient or line.nested_semi
        if comp is None:
            continue
        total += Decimal(str(line.qty_per_unit)) * Decimal(str(comp.avg_cost_per_unit))
    return total.quantize(Decimal("0.01"))


def recalc_menu_item_cogs(menu_item, *, save: bool = True) -> Decimal:
    """Пересчитать MenuItem.cogs из текущей техкарты + ингредиентов.

    Вызывается:
    - При сохранении/удалении строки техкарты (signal)
    - Management command «recalc_all_cogs» — пересчитать все блюда
      после изменения цен закупки.
    """
    new_cogs = calculate_techcard_cogs(menu_item)
    if save:
        if menu_item.cogs != new_cogs:
            menu_item.cogs = new_cogs
            menu_item.save(update_fields=["cogs", "updated_at"])
    return new_cogs


@transaction.atomic
def consume_for_order_close(order, *, user=None) -> dict:
    """При закрытии заказа списать со склада ингредиенты и полуфабрикаты
    согласно техкартам каждой неотменённой позиции.

    Возвращает summary: {consumed: [...], skipped: [...]}.

    Если у блюда **нет техкарты** — позиция пропускается без ошибки
    (типично для покупных товаров, напитков из категории «продано как есть»).

    Если ingredient/semi не хватает — бросаем `INSUFFICIENT_STOCK` (зависит
    от `INVENTORY_PREVENT_NEGATIVE`). Это **прерывает close_order**, чтобы
    кассир знал и принял решение (закупиться или списать вручную).
    """
    from apps.menu.models import MenuItemTechCardLine
    from .models import (
        SemiStockMovementKind,
        StockMovementKind,
    )

    consumed: list[dict] = []
    skipped: list[dict] = []

    # Phase 8B — глобальный toggle. Если ресторан выключил техкарты —
    # автосписания нет вообще (режим «без склада»).
    if not getattr(order.restaurant, "tech_cards_enabled", True):
        return {"consumed": [], "skipped": [{"reason": "tech_cards_enabled=False"}]}

    # Phase 8E — skip-already-consumed: позиции, у которых consumed_at != null,
    # были списаны при create_order / add_items_to_order. Не списываем повторно.
    items = order.items.filter(
        cancelled_at__isnull=True,
        consumed_at__isnull=True,
    ).select_related("menu_item")

    for oi in items:
        mi = oi.menu_item
        if mi is None:
            continue
        # Phase 8B — per-item override.
        if not getattr(mi, "auto_consume", True):
            skipped.append({
                "order_item_id": oi.id,
                "menu_item": mi.name,
                "qty": oi.qty,
                "reason": "auto_consume=False — позиция помечена «без автосписания»",
            })
            continue
        # Заготовочные блюда: сырьё уже списано при заготовке партии.
        # Декрементируем prepared_qty отдельным сервисом (record_batch_consume).
        if getattr(mi, "is_batch_cooking", False):
            skipped.append({
                "order_item_id": oi.id,
                "menu_item": mi.name,
                "qty": oi.qty,
                "reason": "Batch-блюдо — сырьё списано при заготовке",
            })
            continue
        lines = list(
            MenuItemTechCardLine.objects
            .filter(menu_item=mi)
            .select_related("ingredient", "nested_semi")
        )
        if not lines:
            skipped.append({
                "order_item_id": oi.id,
                "menu_item": mi.name,
                "qty": oi.qty,
                "reason": "Нет техкарты — расход не списан",
            })
            continue
        for line in lines:
            total_qty = Decimal(str(line.qty_per_unit)) * Decimal(str(oi.qty))
            if line.ingredient is not None:
                record_movement(
                    ingredient=line.ingredient,
                    kind=StockMovementKind.CONSUME,
                    qty_delta=-total_qty,
                    reason=f"Заказ #{order.id}: {mi.name} × {oi.qty}",
                    user=user,
                    order=order,
                )
                consumed.append({
                    "menu_item": mi.name,
                    "component": line.ingredient.name,
                    "qty": str(total_qty),
                    "kind": "ingredient",
                })
            elif line.nested_semi is not None:
                record_semi_movement(
                    semi_type=line.nested_semi,
                    kind=SemiStockMovementKind.CONSUME_FOR_DISH,
                    qty_delta=-total_qty,
                    reason=f"Заказ #{order.id}: {mi.name} × {oi.qty}",
                    user=user,
                    order=order,
                )
                consumed.append({
                    "menu_item": mi.name,
                    "component": line.nested_semi.name,
                    "qty": str(total_qty),
                    "kind": "semi",
                })
        # Phase 8E — пометить позицию как «уже списана», чтобы повторный вызов
        # consume_for_order_close (на close_order после create_order) её пропустил.
        if oi.consumed_at is None:
            from django.utils import timezone as _tz
            oi.consumed_at = _tz.now()
            oi.save(update_fields=["consumed_at"])

    return {"consumed": consumed, "skipped": skipped}
