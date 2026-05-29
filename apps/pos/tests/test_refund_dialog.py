"""RefundDialog — frame 13."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def order():
    return {
        "id": 42,
        "status": "done",
        "total": "98.00",
        "payment_method": "cash",
        "closed_at": "2026-05-08T12:30:00Z",
        "items": [
            {"id": 100, "name_at_order": "Плов", "price_at_order": "45.00",
             "qty": 2, "cancelled_at": None},
            {"id": 101, "name_at_order": "Чай", "price_at_order": "8.00",
             "qty": 1, "cancelled_at": None},
        ],
    }


@pytest.fixture
def dialog(qtbot, order, mock_client):
    from pos.screens.refund_dialog import RefundDialog

    d = RefundDialog(order=order, client=mock_client)
    qtbot.addWidget(d)
    yield d
    if d._thread is not None and d._thread.isRunning():
        d._thread.quit()
        d._thread.wait(2000)


def test_dialog_opens(dialog):
    assert "#42" in dialog.windowTitle() or dialog.findChildren(QPushButton)


def test_subtotal_updates(dialog):
    # Установить qty=1 для плова → subtotal = 45.00
    dialog._spinners[100].setValue(1)
    assert "45.00" in dialog._items_subtotal_label.text()


def test_subtotal_full(dialog):
    dialog._spinners[100].setValue(2)
    dialog._spinners[101].setValue(1)
    assert "98.00" in dialog._items_subtotal_label.text()


def test_submit_selected_requires_reason(qtbot, dialog):
    dialog._spinners[100].setValue(1)
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Вернуть выбранное")
    with patch(
        "pos.screens.refund_dialog.QMessageBox.warning"
    ) as warn:
        qtbot.mouseClick(submit, Qt.LeftButton)
        assert warn.called


def test_submit_selected_requires_items(qtbot, dialog):
    dialog._reason_edit.setPlainText("test reason")
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Вернуть выбранное")
    with patch(
        "pos.screens.refund_dialog.QMessageBox.warning"
    ) as warn:
        qtbot.mouseClick(submit, Qt.LeftButton)
        assert warn.called


def test_submit_selected_calls_api(qtbot, dialog, mock_client):
    dialog._spinners[100].setValue(1)
    dialog._reason_edit.setPlainText("клиент пожаловался")
    mock_client.request.return_value = {
        "id": 1, "amount": "45.00", "items": [],
    }
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Вернуть выбранное")
    with patch(
        "pos.screens.refund_dialog.QMessageBox.information"
    ):
        qtbot.mouseClick(submit, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: mock_client.request.called, timeout=2000
        )
    args, kwargs = mock_client.request.call_args
    assert args[0] == "POST"
    assert args[1] == "/orders/42/refund/"
    body = kwargs["json"]
    assert body["items"] == [{"order_item_id": 100, "qty": 1}]
    assert body["reason"] == "клиент пожаловался"
    # Idempotency-Key выставлен
    assert "Idempotency-Key" in kwargs["extra_headers"]


def test_submit_full_confirms(qtbot, dialog, mock_client):
    dialog._reason_edit.setPlainText("ошибочный заказ")
    btns = dialog.findChildren(QPushButton)
    full = next(b for b in btns if b.text() == "Возврат всего заказа")
    mock_client.request.return_value = {"id": 2, "amount": "98.00", "items": []}
    from PySide6.QtWidgets import QMessageBox
    with patch(
        "pos.screens.refund_dialog.QMessageBox.question",
        return_value=QMessageBox.Yes,
    ), patch(
        "pos.screens.refund_dialog.QMessageBox.information"
    ):
        qtbot.mouseClick(full, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: mock_client.request.called, timeout=2000
        )
    args, kwargs = mock_client.request.call_args
    assert kwargs["json"]["items"] == []  # пустой = всё
