"""ActiveOrdersScreen — tabs по order_type (frame 10 + frame 11).

Один экран, переключение between «Все / Зал / С собой / Доставка».
"""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def state():
    s = MagicMock()
    s.client = MagicMock()
    s.online_changed = MagicMock()
    s.orders_changed = MagicMock()
    s.orders = []
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.active_orders_screen import ActiveOrdersScreen

    s = ActiveOrdersScreen(state)
    qtbot.addWidget(s)
    s.show()
    yield s


def _make_orders():
    return [
        {"id": 1, "order_type": "hall", "table_name": "Стол 1",
         "status": "new", "guests_count": 2, "items": [],
         "total": "45.00", "created_at": "2026-05-08T10:00:00"},
        {"id": 2, "order_type": "takeaway", "customer_name": "Анвар",
         "customer_phone": "+992 900 11 22 33",
         "status": "new", "items": [], "total": "120.00",
         "created_at": "2026-05-08T10:05:00"},
        {"id": 3, "order_type": "delivery", "customer_name": "Гулнара",
         "customer_address": "ул. Рудаки 32",
         "status": "new", "items": [], "total": "85.00",
         "created_at": "2026-05-08T10:10:00"},
        {"id": 4, "order_type": "takeaway", "customer_name": "Тимур",
         "status": "bill_requested", "items": [], "total": "60.00",
         "created_at": "2026-05-08T10:15:00"},
    ]


def test_default_tab_is_all(screen):
    assert screen._type_filter == "all"
    btns = screen._tab_buttons
    assert "all" in btns and "hall" in btns
    assert "takeaway" in btns and "delivery" in btns


def test_all_tab_shows_every_order(qtbot, screen, state):
    state.orders = _make_orders()
    screen._render_orders()
    assert len(screen._cards) == 4
    assert "4 заказа в очереди" in screen._queue_count_lbl.text()


def test_hall_filter(qtbot, screen, state):
    state.orders = _make_orders()
    screen.set_type_filter("hall")
    assert len(screen._cards) == 1
    assert "1 заказ в очереди" in screen._queue_count_lbl.text()


def test_takeaway_filter(qtbot, screen, state):
    state.orders = _make_orders()
    screen.set_type_filter("takeaway")
    assert len(screen._cards) == 2


def test_delivery_filter(qtbot, screen, state):
    state.orders = _make_orders()
    screen.set_type_filter("delivery")
    assert len(screen._cards) == 1


def test_tab_click_switches_filter(qtbot, screen, state):
    state.orders = _make_orders()
    screen._render_orders()
    qtbot.mouseClick(screen._tab_buttons["takeaway"], Qt.LeftButton)
    assert screen._type_filter == "takeaway"
    assert len(screen._cards) == 2


def test_invalid_filter_ignored(screen, state):
    state.orders = _make_orders()
    screen.set_type_filter("hall")
    screen.set_type_filter("nope-not-a-type")
    assert screen._type_filter == "hall"


def test_empty_filter_clears_counter(qtbot, screen, state):
    state.orders = []
    screen._render_orders()
    assert screen._queue_count_lbl.text() == ""


# -------- OrderCard takeaway/delivery rendering --------


def test_order_card_shows_customer_for_takeaway(qtbot):
    from PySide6.QtWidgets import QLabel
    from pos.widgets.order_card import OrderCard

    order = {
        "id": 99, "order_type": "takeaway",
        "customer_name": "Анвар",
        "customer_phone": "+992 900 11 22 33",
        "status": "new", "items": [{"name_at_order": "Шаурма", "qty": 1}],
        "total": "30.00", "created_at": "2026-05-08T10:00:00",
    }
    card = OrderCard(order)
    qtbot.addWidget(card)

    # Customer name виден в одной из строк
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("Анвар" in t for t in labels)
    assert any("С собой" in t for t in labels)


def test_order_card_falls_back_to_phone_if_no_name(qtbot):
    from PySide6.QtWidgets import QLabel
    from pos.widgets.order_card import OrderCard

    order = {
        "id": 99, "order_type": "delivery",
        "customer_name": "",
        "customer_phone": "+992 900 11 22 33",
        "status": "new", "items": [], "total": "30.00",
        "created_at": "2026-05-08T10:00:00",
    }
    card = OrderCard(order)
    qtbot.addWidget(card)
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("Доставка" in t for t in labels)
    assert any("+992 900" in t for t in labels)
