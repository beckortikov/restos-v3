"""Refund — frame 13. Backend service + API."""
from decimal import Decimal
from uuid import uuid4

import pytest

from common.exceptions import BusinessError

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [
        {"menu_item_id": menu_items["plov"].id, "qty": 2},
        {"menu_item_id": menu_items["chai"].id, "qty": 1},
    ]


def _make_closed_order(restaurant, waiter, cashier, table, menu_items, payment="cash"):
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant,
        table_id=table.id,
        waiter=waiter,
        guests_count=2,
        items_data=_items(menu_items),
        comment="",
        idempotency_key=uuid4(),
    )
    closed, _job = close_order(
        order_id=order.id, cashier=cashier, payment_method=payment
    )
    return closed


def test_full_refund(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order

    order = _make_closed_order(restaurant, waiter, cashier, table, menu_items)
    refund = refund_order(
        order_id=order.id,
        cashier=cashier,
        items_data=[],  # пусто = всё
        reason="Клиент вернул",
        idempotency_key=uuid4(),
    )
    # 2*45 + 1*8 = 98
    assert refund.amount == Decimal("98.00")
    assert refund.items.count() == 2


def test_partial_refund(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order

    order = _make_closed_order(restaurant, waiter, cashier, table, menu_items)
    plov_item = order.items.get(name_at_order="Плов")
    refund = refund_order(
        order_id=order.id,
        cashier=cashier,
        items_data=[{"order_item_id": plov_item.id, "qty": 1}],
        reason="Один плов несъедобный",
        idempotency_key=uuid4(),
    )
    assert refund.amount == Decimal("45.00")
    assert refund.items.count() == 1


def test_double_refund_blocked(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order

    order = _make_closed_order(restaurant, waiter, cashier, table, menu_items)
    plov_item = order.items.get(name_at_order="Плов")

    refund_order(
        order_id=order.id, cashier=cashier,
        items_data=[{"order_item_id": plov_item.id, "qty": 2}],
        reason="r1", idempotency_key=uuid4(),
    )
    # Повторный возврат за того же плова — лимит исчерпан
    with pytest.raises(BusinessError) as exc:
        refund_order(
            order_id=order.id, cashier=cashier,
            items_data=[{"order_item_id": plov_item.id, "qty": 1}],
            reason="r2", idempotency_key=uuid4(),
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_refund_only_for_done(
    restaurant, waiter, cashier, table, menu_items
):
    from apps.orders.services import create_order, refund_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        refund_order(
            order_id=order.id, cashier=cashier,
            items_data=[], reason="x", idempotency_key=uuid4(),
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_refund_requires_reason(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order

    order = _make_closed_order(restaurant, waiter, cashier, table, menu_items)
    with pytest.raises(BusinessError) as exc:
        refund_order(
            order_id=order.id, cashier=cashier,
            items_data=[], reason="   ", idempotency_key=uuid4(),
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_refund_idempotent(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order

    order = _make_closed_order(restaurant, waiter, cashier, table, menu_items)
    key = uuid4()
    r1 = refund_order(
        order_id=order.id, cashier=cashier, items_data=[],
        reason="dup", idempotency_key=key,
    )
    r2 = refund_order(
        order_id=order.id, cashier=cashier, items_data=[],
        reason="dup", idempotency_key=key,
    )
    assert r1.id == r2.id


def test_cash_refund_creates_cash_out_in_shift(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100"),
    )
    order = _make_closed_order(restaurant, waiter, cashier, table, menu_items)
    # close_order привязывает order к shift автоматически
    assert order.shift_id == shift.id

    refund_order(
        order_id=order.id, cashier=cashier, items_data=[],
        reason="клиент", idempotency_key=uuid4(),
    )
    shift.refresh_from_db()
    assert shift.cash_out_total == Decimal("98.00")


def test_card_refund_no_cash_out(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import refund_order
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100"),
    )
    order = _make_closed_order(
        restaurant, waiter, cashier, table, menu_items, payment="card"
    )
    refund_order(
        order_id=order.id, cashier=cashier, items_data=[],
        reason="r", idempotency_key=uuid4(),
    )
    shift.refresh_from_db()
    assert shift.cash_out_total == Decimal("0.00")


# -------- API --------


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def test_api_refund_endpoint(
    api_client, cashier_token, restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")

    resp = api_client.post(
        f"/api/v1/orders/{order.id}/refund/",
        {"items": [], "reason": "клиент"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["amount"] == "98.00"
    assert len(body["items"]) == 2

    # list refunds
    resp = api_client.get(
        f"/api/v1/orders/{order.id}/refunds/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 1


def test_api_refund_requires_idempotency_key(
    api_client, cashier_token, restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")

    resp = api_client.post(
        f"/api/v1/orders/{order.id}/refund/",
        {"items": [], "reason": "x"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
