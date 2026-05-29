"""Multi-payment Phase 4: close_order(payments=[{method, amount}, ...])."""
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


def _create_order(restaurant, waiter, table, menu_items, qty=2):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items, qty),
        idempotency_key=uuid4(),
    )


# -------- Service: payments[] --------


def test_close_with_single_payment_method_legacy(
    restaurant, waiter, cashier, table, menu_items, printer
):
    """Legacy: payment_method='cash' создаёт ровно один OrderPayment."""
    from apps.orders.models import OrderPayment
    from apps.orders.services import close_order

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)
    order, _job = close_order(
        order_id=o.id, cashier=cashier, payment_method="cash",
    )
    assert order.payment_method == "cash"
    pays = OrderPayment.objects.filter(order=order)
    assert pays.count() == 1
    assert pays.first().method == "cash"
    assert pays.first().amount == Decimal("90.00")  # 2×45


def test_close_with_mixed_payments(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.models import OrderPayment
    from apps.orders.services import close_order

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)  # 90 TJS
    order, _job = close_order(
        order_id=o.id, cashier=cashier,
        payments=[
            {"method": "cash", "amount": "60"},
            {"method": "card", "amount": "30"},
        ],
    )
    assert order.status == "done"
    pays = OrderPayment.objects.filter(order=order).order_by("id")
    assert pays.count() == 2
    assert pays[0].method == "cash"
    assert pays[0].amount == Decimal("60.00")
    assert pays[1].method == "card"
    assert pays[1].amount == Decimal("30.00")
    # Primary method = с наибольшей суммой = cash
    assert order.payment_method == "cash"


def test_close_payments_sum_must_match_total(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)  # 90
    with pytest.raises(BusinessError) as exc:
        close_order(
            order_id=o.id, cashier=cashier,
            payments=[
                {"method": "cash", "amount": "50"},
                {"method": "card", "amount": "20"},  # 70 < 90
            ],
        )
    assert exc.value.code == "PAYMENT_AMOUNT_MISMATCH"


def test_close_payments_rejects_negative_amount(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)
    with pytest.raises(BusinessError):
        close_order(
            order_id=o.id, cashier=cashier,
            payments=[{"method": "cash", "amount": "-10"}],
        )


def test_close_payments_rejects_unknown_method(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)
    with pytest.raises(BusinessError):
        close_order(
            order_id=o.id, cashier=cashier,
            payments=[{"method": "bitcoin", "amount": "90"}],
        )


def test_close_requires_at_least_one_payment_method(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)
    with pytest.raises(BusinessError):
        close_order(order_id=o.id, cashier=cashier)


def test_close_payments_empty_list_rejected(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order
    from common.exceptions import BusinessError

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)
    with pytest.raises(BusinessError):
        close_order(order_id=o.id, cashier=cashier, payments=[])


# -------- API endpoint --------


def test_close_endpoint_accepts_payments(
    api_client, restaurant, waiter, cashier, table, menu_items, printer
):
    o = _create_order(restaurant, waiter, table, menu_items, qty=2)  # 90
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/close/",
        {
            "payments": [
                {"method": "cash", "amount": "40.00"},
                {"method": "card", "amount": "50.00"},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]["order"]
    assert data["payment_method"] == "card"  # наибольшая сумма
    pays = data.get("payments") or []
    assert len(pays) == 2
    methods_amounts = {(p["method"], p["amount"]) for p in pays}
    assert methods_amounts == {("cash", "40.00"), ("card", "50.00")}


def test_close_endpoint_legacy_payment_method_still_works(
    api_client, restaurant, waiter, cashier, table, menu_items, printer
):
    o = _create_order(restaurant, waiter, table, menu_items, qty=1)
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/close/",
        {"payment_method": "cash"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]["order"]
    assert data["payment_method"] == "cash"
    assert len(data.get("payments") or []) == 1


# -------- Shift report by_payment correctly aggregates --------


def test_shift_report_aggregates_multi_payments_by_method(
    restaurant, waiter, cashier, table, menu_items, printer
):
    """Z-отчёт должен корректно суммировать по методам через OrderPayment."""
    from apps.shifts.services import build_shift_report, open_shift
    from apps.tables.services import free_table
    from apps.orders.services import close_order

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"),
    )
    o = _create_order(restaurant, waiter, table, menu_items, qty=2)  # 90
    close_order(
        order_id=o.id, cashier=cashier,
        payments=[
            {"method": "cash", "amount": "60"},
            {"method": "card", "amount": "30"},
        ],
    )
    free_table(table)

    rep = build_shift_report(shift)
    assert rep["sales_by_payment"]["cash"] == "60.00"
    assert rep["sales_by_payment"]["card"] == "30.00"
    # cash_revenue должен быть 60 (не 90 как при single-method)
    shift.refresh_from_db()
    assert shift.cash_revenue == Decimal("60.00")
    assert shift.card_revenue == Decimal("30.00")


def test_audit_log_records_payments_breakdown(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.orders.services import close_order

    o = _create_order(restaurant, waiter, table, menu_items, qty=2)
    close_order(
        order_id=o.id, cashier=cashier,
        payments=[
            {"method": "cash", "amount": "40"},
            {"method": "card", "amount": "50"},
        ],
    )
    e = AuditEntry.objects.filter(
        action=AuditAction.ORDER_CLOSE, target_id=o.id
    ).first()
    assert e is not None
    assert "payments" in e.payload
    assert len(e.payload["payments"]) == 2
