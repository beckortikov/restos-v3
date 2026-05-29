"""CloseShiftScreen: рендер по shift dict, расчёт diff, POST /close/."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


def _shift(**kw) -> dict:
    base = {
        "id": 7, "number": 78, "status": "open",
        "opening_balance": "1000.00",
        "expected_balance": "5400.00",
        "cash_revenue": "5400.00",
        "card_revenue": "4670.00",
        "transfer_revenue": "500.00",
        "orders_count": 47,
        "guests_count": 135,
        "average_check": "215.00",
        "opened_at": "2026-05-08T09:00:00+00:00",
    }
    base.update(kw)
    return base


@pytest.fixture
def make_dialog(qtbot):
    def _make(shift_data=None):
        from pos.screens.close_shift_screen import CloseShiftScreen

        client = MagicMock()
        d = CloseShiftScreen(shift=shift_data or _shift(), client=client)
        qtbot.addWidget(d)
        return d, client

    return _make


def test_renders_shift_summary(make_dialog):
    from PySide6.QtWidgets import QLabel

    d, _ = make_dialog()
    texts = [w.text() for w in d.findChildren(QLabel) if w.text()]
    assert any("№78" in t for t in texts)
    assert any("47" == t for t in texts)
    assert any("135" == t for t in texts)
    assert any("5400.00" in t for t in texts)
    assert any("4670.00" in t for t in texts)
    assert any("500.00" in t for t in texts)


def test_diff_zero_shows_match(make_dialog):
    d, _ = make_dialog()
    d._balance_input.setText("5400.00")
    d._update_diff()
    assert "+0.00" in d._diff_label.text() or "0.00" in d._diff_label.text()
    assert "совпадает" in d._badge_text.text().lower()


def test_diff_negative_shows_shortage(make_dialog):
    d, _ = make_dialog()
    d._balance_input.setText("5150.00")
    d._update_diff()
    assert "-250.00" in d._diff_label.text()
    assert "недостача" in d._badge_text.text().lower()


def test_diff_positive_shows_surplus(make_dialog):
    d, _ = make_dialog()
    d._balance_input.setText("5500.00")
    d._update_diff()
    assert "+100.00" in d._diff_label.text()
    assert "излишек" in d._badge_text.text().lower()


def test_close_calls_api(qtbot, make_dialog):
    d, client = make_dialog()
    client.post.return_value = {
        "id": 7, "number": 78, "status": "closed",
        "actual_balance": "5400.00", "discrepancy": "0.00",
        "expected_balance": "5400.00",
    }
    fired: list[dict] = []
    d.shift_closed.connect(lambda s: fired.append(s))

    d._balance_input.setText("5400.00")
    qtbot.mouseClick(d._close_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)

    args, kwargs = client.post.call_args
    assert args[0] == "/shifts/7/close/"
    assert kwargs["json"]["actual_balance"] == "5400.00"
    assert fired[0]["status"] == "closed"
