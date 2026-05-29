"""MenuScreen — проверка потока «Отправить» (frame 4).

Воспроизводит жалобу: «не могу заказать на стол, отправить не работает».
"""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = []
    return c


@pytest.fixture
def state(mock_client):
    s = MagicMock()
    s.client = mock_client
    s.tables = [{"id": 1, "name": "Стол 1", "number": 1}]
    s.orders = []
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.menu_screen import MenuScreen

    s = MenuScreen(state)
    qtbot.addWidget(s)
    s.show()
    yield s
    if s._thread is not None and s._thread.isRunning():
        s._thread.quit()
        s._thread.wait(2000)


def test_create_hall_submit_calls_orders_endpoint(qtbot, screen, mock_client):
    screen.configure_create(order_type="hall", table_id=1)

    plov = {
        "id": 10, "category": 1, "name": "Плов",
        "price": "45.00", "is_available": True,
    }
    screen._cart.add_item(plov)
    assert not screen._cart.is_empty()

    btns = screen._cart.findChildren(QPushButton)
    submit = next(b for b in btns if "Отправить" in b.text())
    assert submit.isEnabled()

    mock_client.request.return_value = {"id": 99, "status": "new"}

    qtbot.mouseClick(submit, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.request.called, timeout=2000)

    args, kwargs = mock_client.request.call_args
    assert args[0] == "POST"
    assert args[1] == "/orders/"
    body = kwargs["json"]
    assert body["order_type"] == "hall"
    assert body["table_id"] == 1
    assert body["items"] == [{"menu_item_id": 10, "qty": 1, "note": ""}]
    assert "Idempotency-Key" in kwargs["extra_headers"]


def test_thread_cleared_after_success(qtbot, screen, mock_client):
    """После успеха _thread = None, чтобы можно было отправить ещё раз."""
    screen.configure_create(order_type="hall", table_id=1)
    screen._cart.add_item(
        {"id": 10, "category": 1, "name": "Плов",
         "price": "45.00", "is_available": True}
    )

    fired: list[int] = []
    screen.order_submitted.connect(lambda oid: fired.append(oid))

    mock_client.request.return_value = {"id": 99}
    btns = screen._cart.findChildren(QPushButton)
    submit = next(b for b in btns if "Отправить" in b.text())
    qtbot.mouseClick(submit, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(fired), timeout=2000)

    assert fired == [99]
    assert screen._thread is None


def test_idem_key_resets_per_configure_create(qtbot, screen):
    screen.configure_create(order_type="hall", table_id=1)
    k1 = screen._idem_key
    screen.configure_create(order_type="hall", table_id=2)
    k2 = screen._idem_key
    assert k1 != k2


def test_submit_disabled_when_empty(qtbot, screen):
    screen.configure_create(order_type="hall", table_id=1)
    btns = screen._cart.findChildren(QPushButton)
    submit = next(b for b in btns if "Отправить" in b.text())
    assert not submit.isEnabled()
