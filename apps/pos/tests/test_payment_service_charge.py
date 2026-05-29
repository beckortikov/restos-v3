"""PaymentDialog отображает service charge из snapshot'а заказа (frame 9)."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_client():
    return MagicMock()


def _open_dialog(qtbot, order, mock_client):
    from pos.screens.payment_dialog import PaymentDialog

    dlg = PaymentDialog(order=order, table={"name": "Стол 1"}, client=mock_client)
    qtbot.addWidget(dlg)
    return dlg


def test_service_charge_visible_when_pct_gt_zero(qtbot, mock_client):
    from PySide6.QtWidgets import QLabel

    order = {
        "id": 1, "items": [
            {"id": 10, "name_at_order": "Плов", "qty": 2,
             "price_at_order": "45.00", "subtotal": "90.00", "cancelled_at": None},
        ],
        "subtotal": "90.00",
        "service_charge_pct": "12.00",
        "service_charge_amount": "10.80",
        "total": "100.80",
        "guests_count": 1,
    }
    dlg = _open_dialog(qtbot, order, mock_client)

    labels = [l.text() for l in dlg.findChildren(QLabel)]
    # Подитог
    assert any("Подитог" in t for t in labels)
    assert any("90.00" in t for t in labels)
    # Service charge с процентом в лейбле
    assert any("Обслуживание (12%)" in t for t in labels)
    assert any("+10.80" in t for t in labels)
    # ИТОГО
    assert any("100.80" in t for t in labels)


def test_service_charge_hidden_when_pct_zero(qtbot, mock_client):
    from PySide6.QtWidgets import QLabel

    order = {
        "id": 2, "items": [
            {"id": 10, "name_at_order": "X", "qty": 1,
             "price_at_order": "50.00", "subtotal": "50.00", "cancelled_at": None},
        ],
        "subtotal": "50.00",
        "service_charge_pct": "0.00",
        "service_charge_amount": "0.00",
        "total": "50.00",
        "guests_count": 1,
    }
    dlg = _open_dialog(qtbot, order, mock_client)
    labels = [l.text() for l in dlg.findChildren(QLabel)]
    # Лейбл «Обслуживание» без скобок-процента
    assert any(t == "Обслуживание" for t in labels)
    # Сумма обслуживания = 0
    assert any("+0.00" in t for t in labels)


def test_subtotal_fallback_when_missing(qtbot, mock_client):
    """Если backend не отдал subtotal (старая схема), вычисляется из total - service."""
    from PySide6.QtWidgets import QLabel

    order = {
        "id": 3, "items": [],
        "service_charge_amount": "10.00",
        "total": "110.00",
        "guests_count": 1,
        # subtotal отсутствует
    }
    dlg = _open_dialog(qtbot, order, mock_client)
    labels = [l.text() for l in dlg.findChildren(QLabel)]
    # subtotal = 110 - 10 = 100.00
    assert any("100.00" in t for t in labels)
