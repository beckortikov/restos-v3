"""PaymentDialog: смешанная оплата (Phase 4 multi-payment)."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def order():
    return {
        "id": 1, "items": [],
        "subtotal": "100.00", "service_charge_amount": "0.00",
        "service_charge_pct": "0.00", "discount_amount": "0.00",
        "total": "100.00", "guests_count": 1,
    }


@pytest.fixture
def dlg(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(order=order, table={"name": "Стол 1"}, client=mock_client)
    qtbot.addWidget(d)
    yield d


def test_mixed_toggle_present(dlg):
    assert hasattr(dlg, "_mixed_chk")
    assert "Смешанная" in dlg._mixed_chk.text()


def test_mixed_inputs_hidden_by_default(dlg):
    assert not dlg._mixed_inputs_box.isVisible()
    assert not dlg._mixed_chk.isChecked()


def test_mixed_toggle_shows_three_inputs(qtbot, dlg):
    dlg._mixed_chk.setChecked(True)
    # box стал виден
    assert dlg._mixed_inputs_box.isVisible() or dlg._mixed_inputs_box.isVisibleTo(dlg)
    # 3 поля: cash, card, transfer
    assert set(dlg._mixed_inputs.keys()) == {"cash", "card", "transfer"}


def test_mixed_toggle_disables_method_buttons(dlg):
    dlg._mixed_chk.setChecked(True)
    for code, btn in dlg._method_buttons.items():
        assert not btn.isEnabled()


def test_mixed_off_re_enables_method_buttons(dlg):
    dlg._mixed_chk.setChecked(True)
    dlg._mixed_chk.setChecked(False)
    for btn in dlg._method_buttons.values():
        assert btn.isEnabled()


def test_pay_button_disabled_until_sum_matches(dlg):
    dlg._mixed_chk.setChecked(True)
    dlg._mixed_inputs["cash"].setText("50")
    assert not dlg._pay_btn.isEnabled()  # 50 < 100
    assert "Осталось" in dlg._mixed_balance_lbl.text()
    dlg._mixed_inputs["card"].setText("50")
    assert dlg._pay_btn.isEnabled()
    assert "✓" in dlg._mixed_balance_lbl.text()


def test_pay_button_disabled_when_sum_exceeds_total(dlg):
    dlg._mixed_chk.setChecked(True)
    dlg._mixed_inputs["cash"].setText("60")
    dlg._mixed_inputs["card"].setText("50")  # 110 > 100
    assert not dlg._pay_btn.isEnabled()
    assert "Перебор" in dlg._mixed_balance_lbl.text()


def test_mixed_amount_filters_non_numeric(dlg):
    dlg._mixed_chk.setChecked(True)
    dlg._mixed_inputs["cash"].setText("12abc.50")
    assert dlg._mixed_inputs["cash"].text() == "12.50"


def test_pay_sends_payments_array(qtbot, dlg, mock_client):
    """В mixed-режиме _on_pay должен слать body={'payments': [...]}, не payment_method."""
    from PySide6.QtCore import Qt

    dlg._mixed_chk.setChecked(True)
    dlg._mixed_inputs["cash"].setText("60")
    dlg._mixed_inputs["card"].setText("40")
    assert dlg._pay_btn.isEnabled()

    mock_client.post.return_value = {
        "data": {"order": {"id": 1, "status": "done"}, "print_job": {"id": 1}}
    }
    qtbot.mouseClick(dlg._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/orders/1/close/"
    body = kwargs["json"]
    assert "payments" in body
    assert "payment_method" not in body
    pays = body["payments"]
    methods = {p["method"] for p in pays}
    assert methods == {"cash", "card"}
    amounts = {p["method"]: p["amount"] for p in pays}
    assert amounts["cash"] == "60"
    assert amounts["card"] == "40"


def test_single_method_still_sends_payment_method(qtbot, dlg, mock_client):
    """В обычном (не-mixed) режиме body как раньше: payment_method без payments."""
    from PySide6.QtCore import Qt

    dlg._select_method("cash")
    assert dlg._pay_btn.isEnabled()

    mock_client.post.return_value = {
        "data": {"order": {"id": 1}, "print_job": {"id": 1}}
    }
    qtbot.mouseClick(dlg._pay_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    body = mock_client.post.call_args.kwargs["json"]
    assert body == {"payment_method": "cash"} or (
        body.get("payment_method") == "cash" and "payments" not in body
    )


def test_mixed_payments_list_only_includes_nonzero(dlg):
    """Поля с пустыми/0 значениями не идут в payments."""
    dlg._mixed_chk.setChecked(True)
    dlg._mixed_inputs["cash"].setText("100")
    dlg._mixed_inputs["card"].setText("")  # пусто
    dlg._mixed_inputs["transfer"].setText("0")
    pays = dlg._mixed_payments_list()
    methods = {p["method"] for p in pays}
    assert methods == {"cash"}
