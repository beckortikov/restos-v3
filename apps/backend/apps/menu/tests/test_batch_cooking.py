"""Phase 7E — BatchCookingLog + record_batch_cook + интеграция с close_order."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def waiter(restaurant):
    from apps.users.models import User, UserRole

    return User.objects.create_user(
        username="w1", password="w-pass",
        role=UserRole.WAITER, restaurant=restaurant,
    )


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Касса",
        kind=PrinterKind.VIRTUAL, is_default=True, is_active=True,
    )


@pytest.fixture
def batch_item(restaurant, category):
    from apps.menu.models import MenuItem

    return MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов (заготовка)",
        price=Decimal("45.00"), is_batch_cooking=True, prepared_qty=0,
        low_stock_threshold=5,
    )


@pytest.fixture
def ingredient_rice(restaurant):
    from apps.inventory.models import Ingredient, IngredientUnit

    return Ingredient.objects.create(
        restaurant=restaurant, name="Рис", unit=IngredientUnit.KG,
        avg_cost_per_unit=Decimal("20"),
    )


# -------- record_batch_cook --------


def test_record_batch_cook_increments_prepared_qty(batch_item):
    from apps.menu.models import BatchCookingLog
    from apps.menu.services import record_batch_cook

    result = record_batch_cook(batch_item, qty_delta=10, kind="cook")

    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 10
    assert result["new_total"] == 10
    assert result["prev_total"] == 0
    assert result["shortfall"] == 0
    assert BatchCookingLog.objects.filter(menu_item=batch_item).count() == 1
    log = BatchCookingLog.objects.get(menu_item=batch_item)
    assert log.qty_delta == 10
    assert log.kind == "cook"


def test_record_batch_cook_rejects_non_batch(restaurant, category):
    from apps.menu.models import MenuItem
    from apps.menu.services import record_batch_cook
    from common.exceptions import BusinessError

    mi = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Чай",
        price=Decimal("8.00"), is_batch_cooking=False,
    )
    with pytest.raises(BusinessError) as exc:
        record_batch_cook(mi, qty_delta=5)
    assert exc.value.code == "INVALID_OPERATION"


def test_record_batch_cook_zero_delta_rejected(batch_item):
    from apps.menu.services import record_batch_cook
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        record_batch_cook(batch_item, qty_delta=0)
    assert exc.value.code == "INVALID_VALUE"


def test_record_batch_cook_consumes_techcard(
    batch_item, ingredient_rice, restaurant, cashier,
):
    """Когда cook заготавливает партию — списываем сырьё × N по техкарте."""
    from apps.inventory.services import record_movement
    from apps.inventory.models import StockMovementKind
    from apps.menu.models import MenuItemTechCardLine
    from apps.menu.services import record_batch_cook

    # Заполняем склад
    record_movement(
        ingredient=ingredient_rice, kind=StockMovementKind.PURCHASE,
        qty_delta=Decimal("10"), unit_cost=Decimal("20"),
        reason="initial",
    )
    # Техкарта: 0.2 кг риса на 1 порцию
    MenuItemTechCardLine.objects.create(
        menu_item=batch_item, ingredient=ingredient_rice,
        qty_per_unit=Decimal("0.2"),
    )

    record_batch_cook(batch_item, qty_delta=5, kind="cook", user=cashier)

    batch_item.refresh_from_db()
    ingredient_rice.refresh_from_db()
    assert batch_item.prepared_qty == 5
    # Было 10, заготовили 5 × 0.2 = 1.0 → осталось 9.0
    assert ingredient_rice.current_qty == Decimal("9.0")


def test_record_batch_consume_clamps_to_zero(batch_item):
    """При расходе больше чем заготовлено — clamp к 0, shortfall > 0."""
    from apps.menu.services import record_batch_cook

    record_batch_cook(batch_item, qty_delta=3, kind="cook")
    result = record_batch_cook(batch_item, qty_delta=-5, kind="consume")

    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 0
    assert result["new_total"] == 0
    assert result["shortfall"] == 2  # на 2 порции не хватило


# -------- API endpoint --------


def test_batch_cook_api_endpoint(api_client, cashier, batch_item):
    api_client.force_authenticate(user=cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{batch_item.id}/batch_cook/",
        {"qty": 8, "note": "Утренняя варка"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["meta"]["new_total"] == 8
    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 8


def test_batch_cook_api_history_get(api_client, cashier, batch_item):
    from apps.menu.services import record_batch_cook

    record_batch_cook(batch_item, qty_delta=10, kind="cook", user=cashier)
    record_batch_cook(batch_item, qty_delta=-3, kind="consume", user=cashier)

    api_client.force_authenticate(user=cashier)
    resp = api_client.get(f"/api/v1/menu/items/{batch_item.id}/batch_cook/")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["meta"]["prepared_qty"] == 7


# -------- close_order integration --------


def test_close_order_decrements_prepared_qty(
    cashier, waiter, restaurant, table, printer, batch_item,
):
    """Закрытие заказа с batch-блюдом декрементирует prepared_qty."""
    from apps.menu.services import record_batch_cook
    from apps.orders.services import close_order, create_order

    record_batch_cook(batch_item, qty_delta=5, kind="cook", user=cashier)

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=table.id,
        items_data=[{"menu_item_id": batch_item.id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    batch_item.refresh_from_db()
    assert batch_item.prepared_qty == 3  # 5 - 2

    from apps.menu.models import BatchCookingLog
    logs = list(
        BatchCookingLog.objects.filter(menu_item=batch_item).order_by("created_at")
    )
    assert len(logs) == 2
    assert logs[1].kind == "consume"
    assert logs[1].qty_delta == -2
    assert logs[1].new_total == 3


def test_close_order_batch_item_skips_techcard_consume(
    cashier, waiter, restaurant, table, printer, batch_item, ingredient_rice,
):
    """Batch-блюдо при close_order не списывает сырьё повторно по техкарте."""
    from apps.inventory.services import record_movement
    from apps.inventory.models import StockMovementKind
    from apps.menu.models import MenuItemTechCardLine
    from apps.menu.services import record_batch_cook
    from apps.orders.services import close_order, create_order

    record_movement(
        ingredient=ingredient_rice, kind=StockMovementKind.PURCHASE,
        qty_delta=Decimal("10"), unit_cost=Decimal("20"), reason="x",
    )
    MenuItemTechCardLine.objects.create(
        menu_item=batch_item, ingredient=ingredient_rice,
        qty_per_unit=Decimal("0.2"),
    )
    record_batch_cook(batch_item, qty_delta=5, kind="cook", user=cashier)
    ingredient_rice.refresh_from_db()
    qty_after_cook = ingredient_rice.current_qty
    assert qty_after_cook == Decimal("9.0")

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=table.id,
        items_data=[{"menu_item_id": batch_item.id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    ingredient_rice.refresh_from_db()
    assert ingredient_rice.current_qty == qty_after_cook
