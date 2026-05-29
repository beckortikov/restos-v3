"""PaymentDialog: compact mode (frame 8) vs full (frame 9)."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QPushButton


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


# -------- Width --------


def test_full_dialog_width_720(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table={"name": "Стол 1"}, client=mock_client,
    )
    qtbot.addWidget(d)
    assert d.width() == 720


def test_compact_dialog_width_520(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table={"name": "Стол 1"}, client=mock_client,
        compact=True,
    )
    qtbot.addWidget(d)
    assert d.width() == 520


# -------- Method buttons height --------


def test_full_method_buttons_height_72(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=False,
    )
    qtbot.addWidget(d)
    btns = d._method_buttons
    for code, btn in btns.items():
        assert btn.height() == 72, f"{code} should be 72px (full mode)"


def test_compact_method_buttons_height_52(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=True,
    )
    qtbot.addWidget(d)
    btns = d._method_buttons
    for code, btn in btns.items():
        assert btn.height() == 52, f"{code} should be 52px (compact mode)"


# -------- Footer layout --------


def test_compact_footer_has_cancel_button(qtbot, order, mock_client):
    """В compact-режиме футер содержит [Отмена] [Оплатить и печать] +
    pill «Без чека»."""
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=True,
    )
    qtbot.addWidget(d)
    btns = d.findChildren(QPushButton)
    texts = {b.text() for b in btns}
    assert "Отмена" in texts


def test_full_footer_has_no_cancel_button(qtbot, order, mock_client):
    """В full-режиме нет кнопки «Отмена» в футере (только close-X в шапке).

    По дизайну frame 9: только большая зелёная + pill «Без чека»."""
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=False,
    )
    qtbot.addWidget(d)
    btns = d.findChildren(QPushButton)
    texts = {b.text() for b in btns}
    # Кнопки «Отмена» как отдельной нет — закрыть через X в шапке
    assert "Отмена" not in texts


def test_compact_pay_button_text(qtbot, order, mock_client):
    """Compact: «Оплатить и печать» (короче, без капса)."""
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=True,
    )
    qtbot.addWidget(d)
    assert d._pay_btn.text() == "Оплатить и печать"


def test_full_pay_button_text(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=False,
    )
    qtbot.addWidget(d)
    assert "ОПЛАТИТЬ" in d._pay_btn.text().upper()


def test_compact_no_receipt_button_present(qtbot, order, mock_client):
    """Pill «Без чека» сохраняется и в compact."""
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(
        order=order, table=None, client=mock_client, compact=True,
    )
    qtbot.addWidget(d)
    assert d._no_receipt_btn is not None
    assert "без чека" in d._no_receipt_btn.text().lower()


# -------- Default param --------


def test_default_is_full_mode(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    d = PaymentDialog(order=order, table=None, client=mock_client)
    qtbot.addWidget(d)
    assert d._compact is False
    assert d.width() == 720
