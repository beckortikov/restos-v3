"""Тесты экрана 1. PIN Login: ввод цифр, backspace, submit, ошибки, локаут."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def screen(qtbot, mock_client):
    from pos.auth.pin_login_screen import PinLoginScreen
    from pos.auth.session import SessionStore

    w = PinLoginScreen(client=mock_client, session_store=SessionStore())
    qtbot.addWidget(w)
    w.show()
    yield w
    # Гарантия: дожидаемся завершения in-flight QThread (login worker), иначе
    # на teardown widget'а Qt разрушит живой поток → crash при следующем тесте.
    t = w._thread
    if t is not None and t.isRunning():
        t.quit()
        if not t.wait(3000):
            t.terminate()
            t.wait(500)


def _click(qtbot, screen, label: str):
    from PySide6.QtWidgets import QPushButton

    for b in screen.findChildren(QPushButton):
        if b.text() == label:
            qtbot.mouseClick(b, Qt.LeftButton)
            return
    raise AssertionError(f"button {label!r} not found")


def test_typing_fills_dots(qtbot, screen):
    for d in "1234":
        _click(qtbot, screen, d)
    assert screen._pin == "1234"
    # 4 заполненных + 2 пустых
    # Заполненная точка окрашена в COLORS['accent_orange'] (brand warm amber).
    from pos.resources.tokens import COLORS
    accent = COLORS["accent_orange"].lower()
    filled = sum(
        1 for d in screen._dot_widgets
        if accent in d.styleSheet().lower()
    )
    assert filled == 4


def test_backspace_removes_last_digit(qtbot, screen):
    for d in "12":
        _click(qtbot, screen, d)
    _click(qtbot, screen, "⌫")
    assert screen._pin == "1"


def test_pin_max_6_digits(qtbot, screen):
    # auto-submit сработает на 6-й цифре, но мы мокаем клиент чтобы он недолго висел
    from threading import Event

    block = Event()

    def hang(*a, **kw):
        block.wait(0.2)  # короткий блок, чтобы тест не зависал
        return {
            "session_token": "tok",
            "user": {"id": 1, "full_name": "X", "role": "cashier"},
        }

    screen.client.post.side_effect = hang
    for d in "123456":
        _click(qtbot, screen, d)
    # после 6 цифр submit ушёл, добавление 7-й не должно повлиять
    assert len(screen._pin) == 6
    _click(qtbot, screen, "7")
    assert len(screen._pin) == 6
    # Освобождаем worker и ждём его завершения перед teardown — иначе
    # ожидающий thread+widget разрушатся одновременно → segfault.
    block.set()
    qtbot.waitUntil(lambda: screen._thread is None, timeout=3000)


def test_submit_too_short_shows_error(qtbot, screen):
    for d in "12":
        _click(qtbot, screen, d)
    _click(qtbot, screen, "OK")
    assert "4–6" in screen._error.text()


def test_submit_success_emits_logged_in(qtbot, screen, mock_client):
    mock_client.post.return_value = {
        "session_token": "abc-token",
        "user": {"id": 1, "full_name": "Анна", "role": "cashier"},
        "expires_at": "2026-01-01T00:00:00Z",
    }
    fired_users: list[dict] = []
    screen.logged_in.connect(lambda u: fired_users.append(u))

    for d in "1234":
        _click(qtbot, screen, d)
    _click(qtbot, screen, "OK")

    qtbot.waitUntil(lambda: bool(fired_users), timeout=2000)
    assert fired_users[0]["full_name"] == "Анна"
    assert screen.session_store.token == "abc-token"
    assert screen._pin == ""
    mock_client.post.assert_called_once_with("/auth/pin/", json={"pin": "1234"})


def test_submit_invalid_pin_shows_error(qtbot, screen, mock_client):
    from pos.http_client import ApiError

    mock_client.post.side_effect = ApiError("AUTH_INVALID_PIN", "Неверный PIN", 401)

    for d in "0000":
        _click(qtbot, screen, d)
    _click(qtbot, screen, "OK")

    qtbot.waitUntil(lambda: "Неверный" in screen._error.text(), timeout=2000)
    assert screen._pin == ""
    assert screen.session_store.token is None


def test_submit_locked_shows_until_time(qtbot, screen, mock_client):
    from pos.http_client import ApiError

    mock_client.post.side_effect = ApiError(
        "AUTH_INVALID_PIN",
        "Учётка заблокирована",
        401,
        detail={"locked_until": "2026-05-08T15:30:00+00:00"},
    )

    for d in "0000":
        _click(qtbot, screen, d)
    _click(qtbot, screen, "OK")

    qtbot.waitUntil(
        lambda: "заблокирована" in screen._error.text().lower(), timeout=2000
    )


def test_network_error_shows_message(qtbot, screen, mock_client):
    from pos.http_client import ApiError

    mock_client.post.side_effect = ApiError("NETWORK", "down", 0)

    for d in "1234":
        _click(qtbot, screen, d)
    _click(qtbot, screen, "OK")

    qtbot.waitUntil(
        lambda: "Нет связи" in screen._error.text(), timeout=2000
    )


def test_keyboard_input(qtbot, screen):
    qtbot.keyClick(screen, Qt.Key_1)
    qtbot.keyClick(screen, Qt.Key_2)
    qtbot.keyClick(screen, Qt.Key_3)
    qtbot.keyClick(screen, Qt.Key_4)
    assert screen._pin == "1234"

    qtbot.keyClick(screen, Qt.Key_Backspace)
    assert screen._pin == "123"
