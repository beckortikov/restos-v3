"""Сервисный сбор: snapshot ставки + расчёт total."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [
        {"menu_item_id": menu_items["plov"].id, "qty": 2},  # 2*45 = 90
        {"menu_item_id": menu_items["chai"].id, "qty": 1},  # 1*8 = 8
    ]


def test_order_snapshot_service_charge_from_active(
    restaurant, waiter, table, menu_items
):
    """Создание заказа берёт ставку сервисного сбора из active service Discount."""
    from apps.orders.models import Discount
    from apps.orders.services import create_order

    # Сидер уже создал service-скидку 12%, но активную меняем на 10%
    Discount.objects.filter(restaurant=restaurant, type="service").update(
        is_active=False
    )
    Discount.objects.create(
        restaurant=restaurant, type="service", name="My service",
        kind="percent", value="10.00", is_active=True, sort_order=10,
    )

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    assert order.service_charge_pct == Decimal("10.00")


def test_order_total_includes_service_charge(
    restaurant, waiter, table, menu_items
):
    """Total = subtotal + service. 98 + 10% = 107.80."""
    from apps.orders.services import create_order

    # Сидер сделал 12% активной — пересоздаём как 10% для предсказуемости
    from apps.orders.models import Discount
    Discount.objects.filter(restaurant=restaurant, type="service").update(
        is_active=False
    )
    Discount.objects.create(
        restaurant=restaurant, type="service", name="Svc 10",
        kind="percent", value="10.00", is_active=True, sort_order=10,
    )

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    assert order.subtotal == Decimal("98.00")
    assert order.service_charge_amount == Decimal("9.80")
    assert order.total == Decimal("107.80")


def test_order_no_service_when_no_active(
    restaurant, waiter, table, menu_items
):
    """Если все service-скидки выключены — service_charge_pct=0, total=subtotal."""
    from apps.orders.models import Discount
    from apps.orders.services import create_order

    Discount.objects.filter(restaurant=restaurant, type="service").update(
        is_active=False
    )
    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    assert order.service_charge_pct == Decimal("0.00")
    assert order.total == order.subtotal == Decimal("98.00")


def test_changing_service_after_creation_does_not_affect_old_order(
    restaurant, waiter, table, menu_items
):
    """Snapshot: смена ставки в настройках после создания заказа
    не меняет уже созданный order.total."""
    from apps.orders.models import Discount
    from apps.orders.services import create_order

    Discount.objects.filter(restaurant=restaurant, type="service").update(
        is_active=False
    )
    svc = Discount.objects.create(
        restaurant=restaurant, type="service", name="Svc",
        kind="percent", value="12.00", is_active=True, sort_order=10,
    )

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    snapshotted = order.service_charge_pct

    # Меняем настройку
    svc.value = Decimal("20.00")
    svc.save()

    # Старый заказ не меняется
    order.refresh_from_db()
    assert order.service_charge_pct == snapshotted == Decimal("12.00")


def test_serializer_includes_service_fields(
    restaurant, waiter, table, menu_items
):
    from apps.orders.serializers import OrderSerializer
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    data = OrderSerializer(order).data
    assert "subtotal" in data
    assert "service_charge_pct" in data
    assert "service_charge_amount" in data
    assert "total" in data


def test_print_payload_includes_service(
    restaurant, waiter, cashier, table, menu_items, printer
):
    """build_receipt_payload отображает сервисный сбор отдельной строкой."""
    from apps.orders.services import close_order, create_order
    from apps.printing.services import build_receipt_payload

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    closed, _job = close_order(
        order_id=order.id, cashier=cashier, payment_method="cash"
    )
    payload = build_receipt_payload(closed)
    assert "subtotal" in payload["order"]
    assert "service_charge_amount" in payload["order"]
    assert "service_charge_pct" in payload["order"]
