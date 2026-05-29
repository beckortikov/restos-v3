"""Cash operations: внесение/изъятие наличных в открытой смене."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


# -------- Service --------


def test_add_cash_in_increases_expected_balance(restaurant, cashier):
    from apps.shifts.services import add_cash_operation, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000"),
    )
    assert shift.expected_balance == Decimal("1000.00")
    add_cash_operation(
        shift=shift, kind="cash_in", amount=Decimal("500"),
        reason="Размен", user=cashier,
    )
    shift.refresh_from_db()
    assert shift.expected_balance == Decimal("1500.00")


def test_add_cash_out_decreases_expected_balance(restaurant, cashier):
    from apps.shifts.services import add_cash_operation, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000"),
    )
    add_cash_operation(
        shift=shift, kind="cash_out", amount=Decimal("300"),
        reason="Закупка", user=cashier,
    )
    shift.refresh_from_db()
    assert shift.expected_balance == Decimal("700.00")


def test_cash_op_rejected_for_closed_shift(restaurant, cashier):
    from apps.shifts.services import (
        add_cash_operation,
        close_shift,
        open_shift,
    )
    from common.exceptions import BusinessError

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"),
    )
    close_shift(
        shift_id=shift.id, restaurant=restaurant,
        actual_balance=Decimal("0"), note="",
    )
    shift.refresh_from_db()
    with pytest.raises(BusinessError) as exc:
        add_cash_operation(
            shift=shift, kind="cash_in", amount=Decimal("100"),
            reason="late", user=cashier,
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_cash_op_rejected_for_nonpositive_amount(restaurant, cashier):
    from apps.shifts.services import add_cash_operation, open_shift
    from common.exceptions import BusinessError

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"),
    )
    with pytest.raises(BusinessError):
        add_cash_operation(
            shift=shift, kind="cash_in", amount=Decimal("0"),
            reason="", user=cashier,
        )
    with pytest.raises(BusinessError):
        add_cash_operation(
            shift=shift, kind="cash_out", amount=Decimal("-100"),
            reason="", user=cashier,
        )


def test_cash_op_writes_audit_log(restaurant, cashier):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.shifts.services import add_cash_operation, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"),
    )
    add_cash_operation(
        shift=shift, kind="cash_out", amount=Decimal("250"),
        reason="Курьер", user=cashier,
    )
    e = AuditEntry.objects.filter(action=AuditAction.CASH_OUT).first()
    assert e is not None
    assert e.payload["amount"] == "250"
    assert e.payload["reason"] == "Курьер"
    assert e.payload["shift_number"] == shift.number


# -------- API endpoint --------


def test_cash_op_endpoint_creates_operation(api_client, restaurant, cashier):
    from apps.shifts.models import CashShiftOperation
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000"),
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/shifts/{shift.id}/cash_op/",
        {"kind": "cash_out", "amount": "200", "reason": "Закупка"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()["data"]
    assert body["kind"] == "cash_out"
    assert body["amount"] == "200.00"
    assert CashShiftOperation.objects.filter(shift=shift).count() == 1


def test_cash_op_endpoint_validates_kind(api_client, restaurant, cashier):
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"),
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/shifts/{shift.id}/cash_op/",
        {"kind": "wrong", "amount": "10", "reason": ""},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400


def test_cash_ops_list_endpoint(api_client, restaurant, cashier):
    from apps.shifts.services import add_cash_operation, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"),
    )
    add_cash_operation(
        shift=shift, kind="cash_in", amount=Decimal("100"),
        reason="A", user=cashier,
    )
    add_cash_operation(
        shift=shift, kind="cash_out", amount=Decimal("50"),
        reason="B", user=cashier,
    )

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        f"/api/v1/shifts/{shift.id}/cash_ops/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2
    kinds = {op["kind"] for op in data}
    assert kinds == {"cash_in", "cash_out"}


# -------- Shift report includes cash totals --------


def test_shift_report_includes_cash_in_out_totals(restaurant, cashier):
    from apps.shifts.services import (
        add_cash_operation,
        build_shift_report,
        open_shift,
    )

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000"),
    )
    add_cash_operation(
        shift=shift, kind="cash_in", amount=Decimal("500"),
        reason="x", user=cashier,
    )
    add_cash_operation(
        shift=shift, kind="cash_out", amount=Decimal("200"),
        reason="y", user=cashier,
    )

    rep = build_shift_report(shift)
    assert rep["shift"]["cash_in_total"] == "500.00"
    assert rep["shift"]["cash_out_total"] == "200.00"
    assert rep["shift"]["expected_balance"] == "1300.00"
    assert len(rep["cash_operations"]) == 2
