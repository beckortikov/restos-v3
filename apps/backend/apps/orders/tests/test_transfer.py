"""Перенос заказа — frame 7."""
from uuid import uuid4

import pytest

from common.exceptions import BusinessError

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [{"menu_item_id": menu_items["plov"].id, "qty": 1}]


@pytest.fixture
def table2(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=2, name="Стол 2", capacity=4
    )


def test_transfer_happy_path(
    restaurant, waiter, cashier, table, table2, menu_items
):
    from apps.orders.services import create_order, transfer_order
    from apps.tables.models import TableStatus

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    moved = transfer_order(
        order_id=order.id, target_table_id=table2.id, cashier=cashier
    )
    assert moved.table_id == table2.id

    table.refresh_from_db()
    table2.refresh_from_db()
    assert table.status == TableStatus.FREE
    assert table.current_order_id is None
    assert table2.status == TableStatus.OCCUPIED
    assert table2.current_order_id == order.id
    assert table2.guests_count == 2


def test_transfer_preserves_bill_requested(
    restaurant, waiter, cashier, table, table2, menu_items
):
    from apps.orders.services import (
        create_order,
        request_bill,
        transfer_order,
    )
    from apps.tables.models import TableStatus

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    request_bill(order_id=order.id, waiter=waiter)
    transfer_order(
        order_id=order.id, target_table_id=table2.id, cashier=cashier
    )
    table2.refresh_from_db()
    assert table2.status == TableStatus.BILL_REQUESTED


def test_transfer_to_occupied_blocked(
    restaurant, waiter, cashier, table, table2, menu_items
):
    from apps.orders.services import create_order, transfer_order

    order_a = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    create_order(
        restaurant=restaurant, table_id=table2.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        transfer_order(
            order_id=order_a.id, target_table_id=table2.id, cashier=cashier
        )
    assert exc.value.code == "TABLE_OCCUPIED"


def test_transfer_same_table_blocked(
    restaurant, waiter, cashier, table, menu_items
):
    from apps.orders.services import create_order, transfer_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        transfer_order(
            order_id=order.id, target_table_id=table.id, cashier=cashier
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_transfer_closed_blocked(
    restaurant, waiter, cashier, table, table2, menu_items, printer
):
    from apps.orders.services import close_order, create_order, transfer_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")
    with pytest.raises(BusinessError) as exc:
        transfer_order(
            order_id=order.id, target_table_id=table2.id, cashier=cashier
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_transfer_takeaway_blocked(
    restaurant, waiter, cashier, table, menu_items
):
    """Перенос — только для hall."""
    from apps.orders.services import create_order, transfer_order

    order = create_order(
        restaurant=restaurant, waiter=waiter,
        items_data=_items(menu_items), comment="",
        order_type="takeaway", customer_name="Иван",
        customer_phone="+992 900 11 22 33",
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        transfer_order(
            order_id=order.id, target_table_id=table.id, cashier=cashier
        )
    assert exc.value.code == "INVALID_TRANSITION"


# -------- API --------


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def test_api_transfer_endpoint(
    api_client, cashier_token, restaurant, waiter, cashier,
    table, table2, menu_items,
):
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/transfer/",
        {"table_id": table2.id},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["table"] == table2.id


def test_api_transfer_missing_table_id(
    api_client, cashier_token, restaurant, waiter, cashier, table, menu_items
):
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/transfer/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 422
