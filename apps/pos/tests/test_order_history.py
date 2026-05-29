"""OrderHistoryScreen — pagination + search + filter."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def state():
    s = MagicMock()
    s.client = MagicMock()
    s.current_shift = None
    s.online_changed = MagicMock()
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.order_history_screen import OrderHistoryScreen

    s = OrderHistoryScreen(state)
    qtbot.addWidget(s)
    s.show()
    yield s


def _make_paginated(orders: list, total: int, page: int = 1, page_size: int = 50):
    return {
        "data": orders,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 1,
        },
    }


# -------- Pagination --------


def test_reload_uses_paginated_response(qtbot, screen, state):
    state.client.get.return_value = _make_paginated(
        [
            {"id": 1, "status": "done", "total": "45.00",
             "payment_method": "cash", "created_at": "2026-05-08T10:00:00"},
        ],
        total=1,
    )
    screen.reload()
    assert len(screen._orders) == 1
    assert screen._total == 1
    assert "1 из 1" in screen._page_count_lbl.text()
    assert not screen._load_more_btn.isEnabled()


def test_reload_request_has_status_csv(qtbot, screen, state):
    state.client.get.return_value = _make_paginated([], total=0)
    screen.reload()
    args, kwargs = state.client.get.call_args
    assert args[0] == "/orders/"
    params = kwargs["params"]
    assert params["status"] == "done,cancelled"
    assert params["page"] == "1"
    assert params["page_size"] == "50"


def test_load_more_appends_and_increments_page(qtbot, screen, state):
    """Page 1 → 50 of 75; load more → page 2 → 25 + previous = 75."""
    state.client.get.return_value = _make_paginated(
        [{"id": i, "status": "done", "total": "10.00",
          "payment_method": "cash",
          "created_at": "2026-05-08T10:00:00"} for i in range(1, 51)],
        total=75,
    )
    screen.reload()
    assert len(screen._orders) == 50
    assert screen._load_more_btn.isEnabled()

    state.client.get.return_value = _make_paginated(
        [{"id": i, "status": "done", "total": "10.00",
          "payment_method": "cash",
          "created_at": "2026-05-08T10:00:00"} for i in range(51, 76)],
        total=75,
    )
    qtbot.mouseClick(screen._load_more_btn, Qt.LeftButton)
    assert len(screen._orders) == 75
    assert screen._page == 2
    assert not screen._load_more_btn.isEnabled()
    assert "75 из 75" in screen._page_count_lbl.text()


def test_load_more_request_uses_page_param(qtbot, screen, state):
    state.client.get.return_value = _make_paginated(
        [{"id": i, "status": "done", "total": "1",
          "payment_method": "cash",
          "created_at": "2026-05-08T10:00:00"} for i in range(50)],
        total=100,
    )
    screen.reload()
    state.client.get.reset_mock()
    state.client.get.return_value = _make_paginated([], total=100, page=2)
    qtbot.mouseClick(screen._load_more_btn, Qt.LeftButton)
    args, kwargs = state.client.get.call_args
    assert kwargs["params"]["page"] == "2"


# -------- Search --------


def test_search_input_triggers_debounced_reload(qtbot, screen, state):
    state.client.get.return_value = _make_paginated([], total=0)
    state.client.get.reset_mock()

    screen._search_input.setText("Иван")
    # Debounce 350мс — ждём чуть дольше
    qtbot.waitUntil(lambda: state.client.get.called, timeout=2000)

    args, kwargs = state.client.get.call_args
    assert kwargs["params"]["q"] == "Иван"
    assert kwargs["params"]["page"] == "1"


def test_search_resets_page_to_1(qtbot, screen, state):
    """Поиск всегда стартует с первой страницы (даже если был page>1)."""
    state.client.get.return_value = _make_paginated(
        [{"id": i, "status": "done", "total": "1",
          "payment_method": "cash",
          "created_at": "2026-05-08T10:00:00"} for i in range(50)],
        total=120,
    )
    screen.reload()
    qtbot.mouseClick(screen._load_more_btn, Qt.LeftButton)
    assert screen._page == 2

    state.client.get.return_value = _make_paginated([], total=0)
    screen._search_input.setText("xyz")
    qtbot.waitUntil(lambda: screen._page == 1, timeout=2000)


def test_empty_search_returns_no_q_param(qtbot, screen, state):
    state.client.get.return_value = _make_paginated([], total=0)
    state.client.get.reset_mock()

    # Set query then clear
    screen._search_input.setText("Test")
    qtbot.waitUntil(lambda: state.client.get.called, timeout=2000)

    state.client.get.reset_mock()
    screen._search_input.setText("")
    qtbot.waitUntil(lambda: state.client.get.called, timeout=2000)

    args, kwargs = state.client.get.call_args
    # Пустой query → не передаём в params
    assert "q" not in kwargs["params"]


# -------- Search input enabled --------


def test_search_input_is_enabled(screen):
    """Регрессия: раньше search был disabled. Теперь — enabled."""
    assert screen._search_input.isEnabled()


def test_load_more_disabled_when_no_more_pages(qtbot, screen, state):
    state.client.get.return_value = _make_paginated(
        [{"id": 1, "status": "done", "total": "1",
          "payment_method": "cash",
          "created_at": "2026-05-08T10:00:00"}],
        total=1,
    )
    screen.reload()
    assert not screen._load_more_btn.isEnabled()


# -------- Today filter --------


def test_today_mode_sends_today_date_range(qtbot, screen, state):
    """В режиме «today» должен отправлять from=today&to=today."""
    from datetime import date

    state.client.get.return_value = _make_paginated([], total=0)
    state.client.get.reset_mock()
    screen.set_mode("today")
    args, kwargs = state.client.get.call_args
    today = date.today().isoformat()
    assert kwargs["params"].get("from") == today
    assert kwargs["params"].get("to") == today


def test_archive_mode_no_date_range(qtbot, screen, state):
    """В режиме «archive» нет date filter."""
    state.client.get.return_value = _make_paginated([], total=0)
    state.client.get.reset_mock()
    screen.set_mode("archive")
    args, kwargs = state.client.get.call_args
    assert "from" not in kwargs["params"]
    assert "to" not in kwargs["params"]


def test_legacy_list_response_works(qtbot, screen, state):
    """Backwards-compat: если backend вернёт plain list (старый клиент)."""
    state.client.get.return_value = [
        {"id": 1, "status": "done", "total": "10.00",
         "payment_method": "cash", "created_at": "2026-05-08T10:00:00"},
    ]
    screen.reload()
    assert len(screen._orders) == 1
    assert screen._total == 1
