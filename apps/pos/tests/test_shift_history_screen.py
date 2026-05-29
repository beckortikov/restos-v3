"""ShiftHistoryScreen — список смен с пагинацией."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def state():
    s = MagicMock()
    s.client = MagicMock()
    s.online_changed = MagicMock()
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.shift_history_screen import ShiftHistoryScreen

    s = ShiftHistoryScreen(state)
    qtbot.addWidget(s)
    yield s


def _paginated(rows, total, page=1):
    return {
        "data": rows,
        "meta": {"total": total, "page": page, "page_size": 50, "pages": 1},
    }


def test_reload_loads_paginated(qtbot, screen, state):
    state.client.get.return_value = _paginated(
        [
            {
                "id": 1, "number": 7, "status": "closed",
                "cashier_name": "Иван", "opened_at": "2026-05-08T08:00:00",
                "closed_at": "2026-05-08T22:00:00",
                "cash_revenue": "1000.00", "card_revenue": "500.00",
                "transfer_revenue": "0", "discrepancy": "0.00",
            },
        ],
        total=1,
    )
    screen.reload()
    assert len(screen._shifts) == 1
    assert screen._total == 1
    assert "1 из 1" in screen._page_count_lbl.text()
    assert not screen._load_more_btn.isEnabled()


def test_reload_request_path_and_params(qtbot, screen, state):
    state.client.get.return_value = _paginated([], total=0)
    screen.reload()
    args, kwargs = state.client.get.call_args
    assert args[0] == "/shifts/"
    assert kwargs["params"]["page"] == "1"
    assert kwargs["params"]["page_size"] == "50"


def test_open_shift_report_emits_signal(qtbot, screen, state):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    state.client.get.return_value = _paginated(
        [
            {
                "id": 42, "number": 3, "status": "closed",
                "cashier_name": "Иван", "opened_at": "2026-05-08T08:00:00",
                "closed_at": "2026-05-08T22:00:00",
                "cash_revenue": "100", "card_revenue": "0",
                "transfer_revenue": "0", "discrepancy": None,
            },
        ],
        total=1,
    )
    screen.reload()

    fired: list[int] = []
    screen.open_shift_report.connect(lambda sid: fired.append(sid))
    btns = screen._rows_holder.findChildren(QPushButton)
    open_btn = next(b for b in btns if b.text() == "Открыть")
    qtbot.mouseClick(open_btn, Qt.LeftButton)
    assert fired == [42]


def test_empty_state(qtbot, screen, state):
    state.client.get.return_value = _paginated([], total=0)
    screen.reload()
    from PySide6.QtWidgets import QLabel
    labels = screen._rows_holder.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("пока нет" in t for t in texts)


def test_back_button_emits_signal(qtbot, screen):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    fired: list[bool] = []
    screen.back_requested.connect(lambda: fired.append(True))
    btns = screen.findChildren(QPushButton)
    back = next(b for b in btns if "Назад" in b.text())
    qtbot.mouseClick(back, Qt.LeftButton)
    assert fired == [True]


def test_revenue_sums_three_methods(qtbot, screen, state):
    """Колонка «Выручка» показывает cash + card + transfer."""
    state.client.get.return_value = _paginated(
        [
            {
                "id": 1, "number": 1, "status": "closed",
                "cashier_name": "Иван", "opened_at": "2026-05-08T08:00:00",
                "closed_at": "2026-05-08T20:00:00",
                "cash_revenue": "1000.00", "card_revenue": "500.00",
                "transfer_revenue": "200.00", "discrepancy": None,
            },
        ],
        total=1,
    )
    screen.reload()
    from PySide6.QtWidgets import QLabel
    labels = screen._rows_holder.findChildren(QLabel)
    texts = [l.text() for l in labels]
    # 1000 + 500 + 200 = 1700
    assert any("1700" in t for t in texts)


def test_settings_reports_section_emits_open_shift_history(qtbot):
    """Карточка «Архив смен» в Reports — кликается, эмитит open_shift_history."""
    from pos.screens.settings_sections.reports_section import ReportsSection
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    section = ReportsSection()
    qtbot.addWidget(section)

    fired: list[bool] = []
    section.open_shift_history.connect(lambda: fired.append(True))

    # Найти кнопку «Открыть» рядом с карточкой «Архив смен» — это последняя
    # стрелка в action-card.
    arrows = [
        b for b in section.findChildren(QPushButton)
        if not b.text() and b.icon() and b.iconSize().width() == 18
    ]
    # По порядку: 1) Отчёт по смене, 2) История заказов, 3) Архив смен
    assert len(arrows) >= 3
    qtbot.mouseClick(arrows[2], Qt.LeftButton)
    assert fired == [True]
