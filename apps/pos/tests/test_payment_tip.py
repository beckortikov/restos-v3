"""PaymentDialog: чаевые (tip_amount)."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def order():
    return {
        "id": 1, "items": [],
        "subtotal": "90.00", "service_charge_amount": "0.00",
        "service_charge_pct": "0.00", "discount_amount": "0.00",
        "tip_amount": "0",
        "total": "90.00", "guests_count": 2,
    }


@pytest.fixture
def dlg(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(order=order, table={"name": "Стол 1"}, client=mock_client)
    qtbot.addWidget(d)
    yield d


def test_tip_input_present(dlg):
    assert hasattr(dlg, "_tip_input")
    assert dlg._tip_input.placeholderText() == "0.00"


def test_tip_value_default_is_zero(dlg):
    from decimal import Decimal

    assert dlg._tip_value() == Decimal("0")


def test_tip_input_filters_non_numeric(dlg):
    dlg._tip_input.setText("12abc.50")
    assert dlg._tip_input.text() == "12.50"


def test_tip_shows_running_total_label(dlg):
    dlg._tip_input.setText("10")
    assert dlg._tip_total_lbl.isVisible() or dlg._tip_total_lbl.isVisibleTo(dlg)
    assert "100" in dlg._tip_total_lbl.text()  # 90 + 10


def test_tip_label_hidden_when_zero(dlg):
    dlg._tip_input.setText("10")
    dlg._tip_input.setText("")
    # При пустом значении — скрыт
    assert not dlg._tip_total_lbl.isVisible()


def test_pay_sends_tip_amount(qtbot, dlg, mock_client):
    from PySide6.QtCore import Qt

    dlg._tip_input.setText("15")
    dlg._select_method("cash")
    mock_client.post.return_value = {
        "data": {"order": {"id": 1}, "print_job": {"id": 1}},
    }
    qtbot.mouseClick(dlg._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    body = mock_client.post.call_args.kwargs["json"]
    assert body["payment_method"] == "cash"
    assert body["tip_amount"] == "15"


def test_pay_no_tip_does_not_send_tip_field(qtbot, dlg, mock_client):
    from PySide6.QtCore import Qt

    dlg._select_method("cash")
    mock_client.post.return_value = {
        "data": {"order": {"id": 1}, "print_job": {"id": 1}},
    }
    qtbot.mouseClick(dlg._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    body = mock_client.post.call_args.kwargs["json"]
    assert "tip_amount" not in body


def test_mixed_payment_balance_includes_tip(dlg):
    """В mixed-режиме сумма payments должна совпадать с total+tip."""
    dlg._tip_input.setText("10")
    dlg._mixed_chk.setChecked(True)
    # total=90, tip=10 → effective=100
    dlg._mixed_inputs["cash"].setText("60")
    dlg._mixed_inputs["card"].setText("40")
    assert dlg._pay_btn.isEnabled()
    # 60+30 < 100
    dlg._mixed_inputs["card"].setText("30")
    assert not dlg._pay_btn.isEnabled()


def test_mixed_with_tip_sends_payments_and_tip(qtbot, dlg, mock_client):
    from PySide6.QtCore import Qt

    dlg._tip_input.setText("10")
    dlg._mixed_chk.setChecked(True)
    dlg._mixed_inputs["cash"].setText("60")
    dlg._mixed_inputs["card"].setText("40")

    mock_client.post.return_value = {
        "data": {"order": {"id": 1}, "print_job": {"id": 1}},
    }
    qtbot.mouseClick(dlg._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    body = mock_client.post.call_args.kwargs["json"]
    assert body["tip_amount"] == "10"
    assert "payments" in body
    assert sum(float(p["amount"]) for p in body["payments"]) == 100.0
