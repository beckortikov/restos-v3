"""TransferDialog — frame 7."""
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
        "id": 7,
        "table": 1,
        "table_name": "Стол 1",
        "order_type": "hall",
        "status": "new",
    }


@pytest.fixture
def tables():
    return [
        {"id": 1, "number": 1, "name": "Стол 1", "capacity": 4, "status": "occupied"},
        {"id": 2, "number": 2, "name": "Стол 2", "capacity": 4, "status": "free"},
        {"id": 3, "number": 3, "name": "Стол 3", "capacity": 2, "status": "free"},
        {"id": 4, "number": 4, "name": "Стол 4", "capacity": 6, "status": "occupied"},
    ]


@pytest.fixture
def dialog(qtbot, order, tables, mock_client):
    from pos.screens.transfer_dialog import TransferDialog

    d = TransferDialog(order=order, tables=tables, client=mock_client)
    qtbot.addWidget(d)
    yield d
    if d._thread is not None and d._thread.isRunning():
        d._thread.quit()
        d._thread.wait(2000)


def test_only_free_tables_excluding_self(dialog):
    # 2 свободных (стол 2 и 3), стол 1 — исходный, столы 1 и 4 — заняты
    assert set(dialog._buttons.keys()) == {2, 3}


def test_submit_disabled_until_select(dialog):
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Перенести")
    assert not submit.isEnabled()


def test_select_enables_submit(qtbot, dialog):
    qtbot.mouseClick(dialog._buttons[2], Qt.LeftButton)
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Перенести")
    assert submit.isEnabled()
    assert dialog._selected_id == 2


def test_submit_calls_api(qtbot, dialog, mock_client):
    mock_client.post.return_value = {"id": 7, "table": 2}
    qtbot.mouseClick(dialog._buttons[2], Qt.LeftButton)
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Перенести")
    qtbot.mouseClick(submit, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/orders/7/transfer/"
    assert kwargs["json"] == {"table_id": 2}


def test_submit_failure_reenables(qtbot, dialog, mock_client):
    from pos.http_client import ApiError

    mock_client.post.side_effect = ApiError("TABLE_OCCUPIED", "Занят", 409)
    qtbot.mouseClick(dialog._buttons[2], Qt.LeftButton)
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if b.text() == "Перенести")
    with patch("pos.screens.transfer_dialog.QMessageBox.warning"):
        qtbot.mouseClick(submit, Qt.LeftButton)
        qtbot.waitUntil(lambda: submit.isEnabled(), timeout=2000)
    assert submit.text() == "Перенести"


def test_no_free_tables_empty_state(qtbot, mock_client):
    from pos.screens.transfer_dialog import TransferDialog

    order = {"id": 7, "table": 1, "order_type": "hall", "status": "new"}
    tables = [
        {"id": 1, "number": 1, "name": "1", "capacity": 4, "status": "occupied"},
        {"id": 2, "number": 2, "name": "2", "capacity": 4, "status": "occupied"},
    ]
    d = TransferDialog(order=order, tables=tables, client=mock_client)
    qtbot.addWidget(d)
    assert d._buttons == {}
