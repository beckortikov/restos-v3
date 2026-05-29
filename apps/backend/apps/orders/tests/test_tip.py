"""Чаевые: tip_amount в close_order, total включает tip, печать строки в чеке."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def _items(menu_items, qty=2):
    return [{"menu_item_id": menu_items["plov"].id, "qty": qty}]


def _create(restaurant, waiter, table, menu_items, qty=2):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items, qty),
        idempotency_key=uuid4(),
    )


# -------- Service --------


def test_close_with_tip_increases_total(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order

    o = _create(restaurant, waiter, table, menu_items, qty=2)  # 90 TJS
    order, _job = close_order(
        order_id=o.id, cashier=cashier,
        payment_method="cash", tip_amount="10",
    )
    assert order.tip_amount == Decimal("10.00")
    assert order.total == Decimal("100.00")  # 90 + 10


def test_close_no_tip_keeps_total(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order

    o = _create(restaurant, waiter, table, menu_items, qty=2)
    order, _job = close_order(
        order_id=o.id, cashier=cashier, payment_method="cash",
    )
    assert order.tip_amount == Decimal("0.00")
    assert order.total == Decimal("90.00")


def test_close_rejects_negative_tip(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create(restaurant, waiter, table, menu_items, qty=2)
    with pytest.raises(BusinessError):
        close_order(
            order_id=o.id, cashier=cashier,
            payment_method="cash", tip_amount="-5",
        )


def test_close_with_tip_and_mixed_payments(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    """Сумма payments должна совпадать с total+tip."""
    from apps.orders.services import close_order

    o = _create(restaurant, waiter, table, menu_items, qty=2)  # 90
    # Total с tip = 90 + 10 = 100, делим 60 нал + 40 карта
    order, _job = close_order(
        order_id=o.id, cashier=cashier,
        payments=[
            {"method": "cash", "amount": "60"},
            {"method": "card", "amount": "40"},
        ],
        tip_amount="10",
    )
    assert order.total == Decimal("100.00")
    assert order.tip_amount == Decimal("10.00")


def test_close_mismatch_when_tip_not_covered(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    """Если payments покрывают только base без tip — ошибка."""
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create(restaurant, waiter, table, menu_items, qty=2)
    with pytest.raises(BusinessError) as exc:
        close_order(
            order_id=o.id, cashier=cashier,
            payments=[{"method": "cash", "amount": "90"}],
            tip_amount="10",  # требуется 100, дано 90
        )
    assert exc.value.code == "PAYMENT_AMOUNT_MISMATCH"


# -------- API --------


def test_close_endpoint_accepts_tip(
    api_client, restaurant, waiter, cashier, table, menu_items, printer,
):
    o = _create(restaurant, waiter, table, menu_items, qty=2)
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/close/",
        {"payment_method": "cash", "tip_amount": "15.50"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]["order"]
    assert data["tip_amount"] == "15.50"
    assert data["total"] == "105.50"


# -------- Receipt template --------


def test_receipt_text_includes_tip_line():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе", "currency": "TJS"},
        "order": {
            "id": 1, "table": "Стол 1", "guests": 2,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T19:00:00",
            "payment_method": "cash",
            "subtotal": "90.00",
            "service_charge_pct": "0",
            "service_charge_amount": "0",
            "discount_name": "",
            "discount_kind": "",
            "discount_value": "0",
            "discount_amount": "0",
            "tip_amount": "15.00",
            "total": "105.00",
        },
        "items": [
            {"name": "Плов", "qty": 2, "price": "45.00", "subtotal": "90.00"},
        ],
    }
    text = render_text_preview(payload, width=48)
    assert "Чаевые" in text
    assert "+15.00" in text
    assert "105.00" in text


def test_receipt_text_no_tip_line_when_zero():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе", "currency": "TJS"},
        "order": {
            "id": 1, "table": "Стол 1", "guests": 2,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T19:00:00",
            "payment_method": "cash",
            "subtotal": "90.00",
            "service_charge_pct": "0",
            "service_charge_amount": "0",
            "discount_name": "",
            "discount_kind": "",
            "discount_value": "0",
            "discount_amount": "0",
            "tip_amount": "0",
            "total": "90.00",
        },
        "items": [
            {"name": "Плов", "qty": 2, "price": "45.00", "subtotal": "90.00"},
        ],
    }
    text = render_text_preview(payload, width=48)
    assert "Чаевые" not in text
