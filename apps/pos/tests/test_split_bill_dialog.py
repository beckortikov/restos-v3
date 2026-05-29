"""SplitBillDialog — frame 6."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def order():
    return {"id": 5, "total": "100.00", "guests_count": 4}


@pytest.fixture
def dialog(qtbot, order, mock_client):
    from pos.screens.split_bill_dialog import SplitBillDialog

    d = SplitBillDialog(order=order, client=mock_client)
    qtbot.addWidget(d)
    yield d
    if d._thread is not None and d._thread.isRunning():
        d._thread.quit()
        d._thread.wait(2000)


def test_default_parts_from_guests(dialog):
    assert dialog._parts_spin.value() == 4


def test_share_calculation_even(dialog):
    dialog._parts_spin.setValue(4)
    assert "25.00" in dialog._share_lbl.text()


def test_share_calculation_with_remainder(dialog):
    dialog._parts_spin.setValue(3)
    # 100/3 = 33.33 with last 33.34
    assert "33.33" in dialog._share_lbl.text()
    assert "33.34" in dialog._share_sub.text()


def test_submit_calls_api(qtbot, dialog, mock_client):
    mock_client.post.return_value = {
        "parts": 4, "share": "25.00", "last_share": "25.00", "print_jobs": []
    }
    btns = dialog.findChildren(QPushButton)
    submit = next(b for b in btns if "Печатать" in b.text())
    with patch("pos.screens.split_bill_dialog.QMessageBox.information"):
        qtbot.mouseClick(submit, Qt.LeftButton)
        qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)
    args, kwargs = mock_client.post.call_args
    assert args[0] == "/orders/5/split_print/"
    assert kwargs["json"] == {"parts": 4}


def test_minimum_parts_two(dialog):
    dialog._parts_spin.setValue(1)  # отвергается range minimum
    assert dialog._parts_spin.value() >= 2


def test_minimum_default_when_no_guests(qtbot, mock_client):
    from pos.screens.split_bill_dialog import SplitBillDialog

    d = SplitBillDialog(
        order={"id": 1, "total": "10.00", "guests_count": 0},
        client=mock_client,
    )
    qtbot.addWidget(d)
    assert d._parts_spin.value() == 2
