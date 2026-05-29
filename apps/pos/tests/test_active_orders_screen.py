import pytest


def _order(**kw) -> dict:
    base = {
        "id": 100,
        "status": "new",
        "table": 1,
        "table_name": "Стол 1",
        "waiter_name": "Карим",
        "guests_count": 2,
        "total": "98.00",
        "currency": "TJS",
        "created_at": "2026-05-08T14:00:00+00:00",
        "items": [{"name_at_order": "Плов", "qty": 1, "cancelled_at": None}],
        "order_type": "hall",
    }
    base.update(kw)
    return base


@pytest.fixture
def fake_state():
    from PySide6.QtCore import QObject, Signal

    class _FakeState(QObject):
        tables_changed = Signal(list)
        orders_changed = Signal(list)
        online_changed = Signal(bool)

        def __init__(self):
            super().__init__()
            self._orders: list[dict] = []
            self._tables: list[dict] = []
            self.client = None  # тесты cancel не проверяют HTTP

        @property
        def orders(self):
            return self._orders

        @property
        def tables(self):
            return self._tables

        def set_orders(self, orders):
            self._orders = orders
            self.orders_changed.emit(orders)

        def refresh(self):
            return True

    return _FakeState()


@pytest.fixture
def screen(qtbot, fake_state):
    from pos.screens.active_orders_screen import ActiveOrdersScreen

    s = ActiveOrdersScreen(fake_state)
    qtbot.addWidget(s)
    return s


def test_initial_empty(screen):
    assert screen._cards == []


def test_renders_orders(screen, fake_state):
    fake_state.set_orders([_order(id=1), _order(id=2), _order(id=3)])
    assert len(screen._cards) == 3


def test_bill_requested_orders_first(screen, fake_state):
    fake_state.set_orders([
        _order(id=1, status="new", created_at="2026-05-08T13:00:00+00:00"),
        _order(id=2, status="bill_requested", created_at="2026-05-08T12:00:00+00:00"),
        _order(id=3, status="new", created_at="2026-05-08T14:00:00+00:00"),
    ])
    # bill_requested должен быть первым
    assert screen._cards[0]._order_id == 2


def test_new_orders_sorted_by_created_desc(screen, fake_state):
    fake_state.set_orders([
        _order(id=1, status="new", created_at="2026-05-08T10:00:00+00:00"),
        _order(id=2, status="new", created_at="2026-05-08T14:00:00+00:00"),
        _order(id=3, status="new", created_at="2026-05-08T12:00:00+00:00"),
    ])
    ids = [c._order_id for c in screen._cards]
    assert ids == [2, 3, 1]


def test_pay_signal_propagates(qtbot, screen, fake_state):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    fake_state.set_orders([_order(id=42)])
    seen: list[int] = []
    screen.pay_requested.connect(lambda i: seen.append(i))

    pay_btn = next(
        b for b in screen._cards[0].findChildren(QPushButton) if b.text() == "Оплатить"
    )
    qtbot.mouseClick(pay_btn, Qt.LeftButton)
    assert seen == [42]


def test_logout_via_sidebar(qtbot, screen):
    from PySide6.QtCore import Qt

    seen: list[bool] = []
    screen.logout_requested.connect(lambda: seen.append(True))
    qtbot.mouseClick(screen.sidebar._buttons["logout"], Qt.LeftButton)
    assert seen == [True]


def test_nav_to_tables(qtbot, screen):
    from PySide6.QtCore import Qt

    seen: list[str] = []
    screen.nav_requested.connect(lambda n: seen.append(n))
    qtbot.mouseClick(screen.sidebar._buttons["tables"], Qt.LeftButton)
    assert seen == ["tables"]


def test_offline_indicator(screen, fake_state):
    fake_state.online_changed.emit(False)
    assert "Offline" in screen._status_label.text()
    fake_state.online_changed.emit(True)
    assert "Online" in screen._status_label.text()


def test_set_cashier_name(screen):
    screen.set_cashier_name("Анна Кассир")
    assert screen._cashier_lbl.text() == "Анна Кассир"
