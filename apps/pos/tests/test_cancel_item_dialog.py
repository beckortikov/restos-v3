"""CancelItemDialog — отмена отдельной позиции из активного заказа."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    # Дефолтные причины — пусть get('/cancel_reasons/') возвращает пусто,
    # тесты, где нужны чипы, перепишут возвращаемое значение.
    c.get.return_value = []
    return c


@pytest.fixture
def item():
    return {"id": 50, "name_at_order": "Плов", "qty": 2, "subtotal": "90.00"}


@pytest.fixture
def dialog(qtbot, item, mock_client):
    from pos.screens.cancel_item_dialog import CancelItemDialog

    d = CancelItemDialog(order_id=42, item=item, client=mock_client)
    qtbot.addWidget(d)
    yield d
    if d._thread is not None and d._thread.isRunning():
        d._thread.quit()
        d._thread.wait(2000)


def test_submit_requires_reason(qtbot, dialog):
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Отменить позицию")
    with patch(
        "pos.screens.cancel_item_dialog.QMessageBox.warning"
    ) as warn:
        qtbot.mouseClick(submit, Qt.LeftButton)
        assert warn.called


def test_submit_calls_api(qtbot, dialog, mock_client):
    dialog._reason_edit.setPlainText("ошибка кассира")
    mock_client.post.return_value = {"id": 42}
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Отменить позицию")
    qtbot.mouseClick(submit, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/orders/42/cancel_item/"
    assert kwargs["json"] == {"item_id": 50, "reason": "ошибка кассира"}


def test_failure_reenables(qtbot, dialog, mock_client):
    from pos.http_client import ApiError

    dialog._reason_edit.setPlainText("test")
    mock_client.post.side_effect = ApiError("INVALID_TRANSITION", "msg", 422)
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Отменить позицию")
    with patch("pos.screens.cancel_item_dialog.QMessageBox.warning"):
        qtbot.mouseClick(submit, Qt.LeftButton)
        qtbot.waitUntil(lambda: submit.isEnabled(), timeout=2000)


def test_chips_render_from_reasons(qtbot, item, mock_client):
    from pos.screens.cancel_item_dialog import CancelItemDialog

    reasons = [
        {"id": 1, "kind": "item", "label": "Гость передумал", "sort_order": 0,
         "is_active": True},
        {"id": 2, "kind": "item", "label": "Ошибка кассира", "sort_order": 1,
         "is_active": True},
    ]
    d = CancelItemDialog(
        order_id=1, item=item, client=mock_client, reasons=reasons,
    )
    qtbot.addWidget(d)

    btns = d.findChildren(QPushButton)
    chip_labels = {b.text() for b in btns}
    assert "Гость передумал" in chip_labels
    assert "Ошибка кассира" in chip_labels


def test_chip_click_fills_textarea(qtbot, item, mock_client):
    from pos.screens.cancel_item_dialog import CancelItemDialog

    reasons = [
        {"id": 1, "kind": "item", "label": "Гость передумал", "sort_order": 0,
         "is_active": True},
    ]
    d = CancelItemDialog(
        order_id=1, item=item, client=mock_client, reasons=reasons,
    )
    qtbot.addWidget(d)

    btns = d.findChildren(QPushButton)
    chip = next(b for b in btns if b.text() == "Гость передумал")
    qtbot.mouseClick(chip, Qt.LeftButton)
    assert d._reason_edit.toPlainText() == "Гость передумал"


def test_dialog_fetches_reasons_when_not_passed(qtbot, item, mock_client):
    """Если reasons=None, диалог сам тянет /cancel_reasons/?kind=item."""
    from pos.screens.cancel_item_dialog import CancelItemDialog

    mock_client.get.return_value = [
        {"id": 1, "kind": "item", "label": "X", "sort_order": 0, "is_active": True},
    ]
    d = CancelItemDialog(order_id=1, item=item, client=mock_client)
    qtbot.addWidget(d)
    args, kwargs = mock_client.get.call_args
    assert args[0] == "/cancel_reasons/"
    assert kwargs.get("params", {}).get("kind") == "item"
    assert d._reasons[0]["label"] == "X"


def test_emits_signal_on_success(qtbot, dialog, mock_client):
    fired: list[dict] = []
    dialog.item_cancelled.connect(lambda d: fired.append(d))
    dialog._reason_edit.setPlainText("причина")
    mock_client.post.return_value = {"id": 42, "status": "new"}
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Отменить позицию")
    qtbot.mouseClick(submit, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)
    assert fired[0]["id"] == 42


# -------- Order detail panel × button --------


@pytest.fixture
def panel(qtbot):
    from pos.widgets.order_detail_panel import OrderDetailPanel

    p = OrderDetailPanel()
    qtbot.addWidget(p)
    return p


def test_detail_panel_emits_cancel_item_for_active(qtbot, panel):
    table = {"id": 1, "name": "Стол 1"}
    order = {
        "id": 5, "status": "new", "guests_count": 2, "total": "90.00",
        "items": [
            {"id": 50, "name_at_order": "Плов", "qty": 2, "subtotal": "90.00",
             "cancelled_at": None},
        ],
    }
    panel.show_order(table, order)

    fired: list[tuple] = []
    panel.cancel_item_requested.connect(lambda oid, it: fired.append((oid, it)))

    # Найти × кнопку в строке (24x24, danger color)
    btns = panel.findChildren(QPushButton)
    x_btns = [b for b in btns if b.toolTip() == "Отменить позицию"]
    assert len(x_btns) == 1
    qtbot.mouseClick(x_btns[0], Qt.LeftButton)
    assert len(fired) == 1
    assert fired[0][0] == 5
    assert fired[0][1]["id"] == 50


def test_detail_panel_no_cancel_for_done(qtbot, panel):
    """Закрытый заказ (status=done) — × кнопок быть не должно."""
    table = {"id": 1, "name": "Стол 1"}
    order = {
        "id": 5, "status": "done", "guests_count": 2, "total": "90.00",
        "items": [
            {"id": 50, "name_at_order": "Плов", "qty": 2, "subtotal": "90.00",
             "cancelled_at": None},
        ],
    }
    panel.show_order(table, order)
    btns = panel.findChildren(QPushButton)
    x_btns = [b for b in btns if b.toolTip() == "Отменить позицию"]
    assert x_btns == []
