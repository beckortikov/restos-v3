"""OpenShiftScreen: реальный POST /shifts/open/, обработка SHIFT_ALREADY_OPEN."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def screen(qtbot, mock_client):
    from pos.screens.open_shift_screen import OpenShiftScreen

    s = OpenShiftScreen(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s
    if s._thread is not None and s._thread.isRunning():
        s._thread.quit()
        s._thread.wait(2000)


def _click_open(qtbot, screen):
    from PySide6.QtWidgets import QPushButton

    btn = next(
        b for b in screen.findChildren(QPushButton) if "ОТКРЫТЬ" in b.text()
    )
    qtbot.mouseClick(btn, Qt.LeftButton)


def test_open_calls_api_with_balance(qtbot, screen, mock_client):
    mock_client.post.return_value = {"id": 1, "number": 1, "status": "open"}
    fired: list[dict] = []
    screen.shift_opened.connect(lambda s: fired.append(s))

    screen._balance.setText("1500.00 TJS")
    _click_open(qtbot, screen)
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/shifts/open/"
    assert kwargs["json"]["opening_balance"] == "1500.00"
    assert fired[0]["id"] == 1


def test_open_already_open_offers_continue(qtbot, screen, mock_client, monkeypatch):
    from pos.http_client import ApiError

    # Первый POST → 409, в QMessageBox жмём "Продолжить",
    # после чего GET /shifts/current/ возвращает существующую смену.
    mock_client.post.side_effect = ApiError(
        "SHIFT_ALREADY_OPEN", "Уже открыта", 409
    )
    mock_client.get.return_value = {"id": 5, "number": 5, "status": "open"}

    from PySide6.QtWidgets import QMessageBox

    def fake_exec(self):
        # имитируем клик "Продолжить" — first button (YesRole)
        for btn in self.buttons():
            if "Продолжить" in btn.text():
                self.clickedButton = lambda b=btn: b  # bind closure
                return 0
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    fired: list[dict] = []
    screen.shift_opened.connect(lambda s: fired.append(s))

    screen._balance.setText("0.00 TJS")
    _click_open(qtbot, screen)
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)

    assert fired[0]["id"] == 5
    args, _ = mock_client.get.call_args
    assert args[0] == "/shifts/current/"


def test_quick_buttons_increment_balance(qtbot, screen):
    from PySide6.QtWidgets import QPushButton

    # В UI 3 быстрые кнопки: +100, +500, +1000
    plus500 = next(b for b in screen.findChildren(QPushButton) if b.text() == "+500")
    qtbot.mouseClick(plus500, Qt.LeftButton)
    assert "500" in screen._balance.text()
