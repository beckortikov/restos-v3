"""ShiftReportScreen — frame 15. Логика disabled-кнопки + раскладка 2×2."""
from unittest.mock import MagicMock

import pytest


REPORT_OPEN = {
    "shift": {
        "id": 1, "number": 1, "status": "open",
        "opening_balance": "0.00", "expected_balance": "53.00",
        "opened_at": "2026-05-08T13:19:00", "closed_at": None,
    },
    "kpi": {
        "revenue": "53.00", "average_check": "26.50",
        "guests_count": 2, "orders_count": 2,
        "average_per_guest": "26.50",
    },
    "sales_by_payment": {"cash": "53.00", "card": "0.00", "transfer": "0.00"},
    "sales_by_category": [{"name": "Горячее", "qty": 2, "total": "53.00"}],
    "sales_by_order_type": [{"type": "hall", "orders_count": 2, "total": "53.00"}],
    "waiters": [],
}

REPORT_CLOSED = {
    **REPORT_OPEN,
    "shift": {
        **REPORT_OPEN["shift"],
        "status": "closed",
        "closed_at": "2026-05-08T19:36:00",
        "actual_balance": "53.00", "discrepancy": "0.00",
    },
}


@pytest.fixture
def state():
    s = MagicMock()
    s.client = MagicMock()
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.shift_report_screen import ShiftReportScreen

    s = ShiftReportScreen(state)
    qtbot.addWidget(s)
    yield s


def _set_report(screen, report: dict) -> None:
    """Хелпер: ставим report напрямую и перерисовываем (минуя API-fetch)."""
    screen._report = report
    screen._render()


def test_close_button_enabled_for_open_shift(screen):
    _set_report(screen, REPORT_OPEN)
    assert screen._close_btn.isEnabled()
    assert screen._close_btn.text() == "Закрыть смену"


def test_close_button_disabled_for_closed_shift(screen):
    _set_report(screen, REPORT_CLOSED)
    assert not screen._close_btn.isEnabled()
    assert screen._close_btn.text() == "Смена закрыта"


def test_close_button_disabled_when_no_report(screen):
    screen._report = None
    screen._render()
    assert not screen._close_btn.isEnabled()


def test_close_button_emits_signal(qtbot, screen):
    from PySide6.QtCore import Qt

    _set_report(screen, REPORT_OPEN)
    fired: list[bool] = []
    screen.close_shift_requested.connect(lambda: fired.append(True))
    qtbot.mouseClick(screen._close_btn, Qt.LeftButton)
    assert fired == [True]


def test_back_button_emits_signal(qtbot, screen):
    """Кнопка «Назад» эмитит back_requested."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    _set_report(screen, REPORT_OPEN)
    fired: list[bool] = []
    screen.back_requested.connect(lambda: fired.append(True))

    btns = screen.findChildren(QPushButton)
    back = next(b for b in btns if b.text() == "Назад")
    qtbot.mouseClick(back, Qt.LeftButton)
    assert fired == [True]


def test_summary_layout_two_columns(screen):
    """Раскладка 2×2 точно по frame 15 дизайну:
    - (0,0) Оплата   (0,1) По типу
    - (1,0) Категории (1,1) Касса
    """
    _set_report(screen, REPORT_OPEN)

    grid = screen._details_grid
    # 4 виджета размещены в позициях согласно frame 15
    titles_at_pos: dict[tuple[int, int], str] = {}
    for r in range(2):
        for c in range(2):
            item = grid.itemAtPosition(r, c)
            if item is None or item.widget() is None:
                continue
            from PySide6.QtWidgets import QLabel

            lbls = item.widget().findChildren(QLabel)
            if lbls:
                # Первый QLabel в карточке = заголовок секции
                titles_at_pos[(r, c)] = lbls[0].text()

    assert titles_at_pos.get((0, 0)) == "Оплата по способам"
    assert titles_at_pos.get((0, 1)) == "По типу заказа"
    assert titles_at_pos.get((1, 0)) == "Продажи по категориям"
    assert titles_at_pos.get((1, 1)) == "Касса"


def test_kpi_cards_render(screen):
    """4 KPI карточки: Выручка / Средний чек / Гостей / Заказов."""
    _set_report(screen, REPORT_OPEN)
    assert screen._kpi_layout.count() == 4


# -------- Cash op button --------


def test_cash_op_button_present_and_enabled_for_open_shift(screen):
    _set_report(screen, REPORT_OPEN)
    assert hasattr(screen, "_cash_op_btn")
    assert "Касса" in screen._cash_op_btn.text()
    assert screen._cash_op_btn.isEnabled()


def test_cash_op_button_disabled_for_closed_shift(screen):
    _set_report(screen, REPORT_CLOSED)
    assert not screen._cash_op_btn.isEnabled()


def test_cash_op_button_no_op_without_shift_id(qtbot, screen, state):
    """Без вызова set_shift_id() кнопка не должна открывать диалог."""
    from PySide6.QtCore import Qt

    _set_report(screen, REPORT_OPEN)
    state.client.post.reset_mock()
    qtbot.mouseClick(screen._cash_op_btn, Qt.LeftButton)
    assert not state.client.post.called


def test_cash_totals_shown_in_kassa_card(screen):
    """Если cash_in_total/cash_out_total > 0 — отображаются строки + Внесения / − Изъятия."""
    from PySide6.QtWidgets import QLabel

    report_with_cash_ops = {
        **REPORT_OPEN,
        "shift": {
            **REPORT_OPEN["shift"],
            "cash_in_total": "500.00",
            "cash_out_total": "200.00",
        },
    }
    _set_report(screen, report_with_cash_ops)
    labels = screen.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("Внесения" in t for t in texts)
    assert any("Изъятия" in t for t in texts)
    assert any("500.00" in t for t in texts)
    assert any("200.00" in t for t in texts)


def test_cash_totals_hidden_when_zero(screen):
    """Если нет cash ops — не показываем 0-строки (визуальный шум)."""
    from PySide6.QtWidgets import QLabel

    report_no_ops = {
        **REPORT_OPEN,
        "shift": {
            **REPORT_OPEN["shift"],
            "cash_in_total": "0.00",
            "cash_out_total": "0.00",
        },
    }
    _set_report(screen, report_no_ops)
    labels = screen.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert not any("Внесения" in t for t in texts)
    assert not any("Изъятия" in t for t in texts)


# -------- Z-report button --------


def test_print_z_button_present(screen):
    _set_report(screen, REPORT_OPEN)
    assert hasattr(screen, "_print_z_btn")
    assert "Z-отчёт" in screen._print_z_btn.text()


def test_print_z_button_calls_endpoint_and_emits_signal(qtbot, screen, state):
    from PySide6.QtCore import Qt

    screen.set_shift_id(42)
    state.client.get.return_value = {"data": REPORT_OPEN}
    state.client.post.return_value = {"data": {"job_id": 5, "shift_id": 42}}
    # set_shift_id уже вызвал get → render. Перезагрузим явно.
    screen._report = REPORT_OPEN
    screen._render()

    fired: list[int] = []
    screen.print_z_requested.connect(lambda sid: fired.append(sid))
    qtbot.mouseClick(screen._print_z_btn, Qt.LeftButton)

    state.client.post.assert_called_once()
    args, kwargs = state.client.post.call_args
    assert args[0] == "/shifts/42/print_z/"
    assert fired == [42]


def test_print_z_button_no_op_without_shift_id(qtbot, screen, state):
    """Без вызова set_shift_id() кнопка не должна слать запросы."""
    from PySide6.QtCore import Qt

    _set_report(screen, REPORT_OPEN)
    state.client.post.reset_mock()
    qtbot.mouseClick(screen._print_z_btn, Qt.LeftButton)
    assert not state.client.post.called


# -------- KPI deltas --------


def test_kpi_card_renders_delta_chip_when_pct_present(screen):
    """Если в report есть deltas — на KPI-карточке показывается чип ↑/↓ %."""
    from PySide6.QtWidgets import QLabel

    report_with_deltas = {
        **REPORT_OPEN,
        "deltas": {
            "revenue_pct": "5.0",
            "orders_pct": "-3.2",
            "guests_pct": None,
            "average_check_pct": "0.0",
        },
        "previous_shift": {"shift_number": 1, "revenue": "50.00"},
    }
    _set_report(screen, report_with_deltas)
    # Соберём все QLabel внутри kpi_row, ищем строки с %.
    labels = screen._kpi_row.findChildren(QLabel)
    texts = [l.text() for l in labels]
    chip_texts = [t for t in texts if "%" in t]
    # Должно быть 3 чипа (revenue, orders, average_check). guests_pct=None — без чипа.
    assert len(chip_texts) == 3
    assert any("↑" in t and "5.0" in t for t in chip_texts)
    assert any("↓" in t and "3.2" in t for t in chip_texts)
    assert any("→" in t for t in chip_texts)  # 0.0% → flat arrow


def test_kpi_card_no_delta_chip_when_no_previous_shift(screen):
    """Если deltas пусто (нет прошлой смены) — чипов нет."""
    from PySide6.QtWidgets import QLabel

    _set_report(screen, REPORT_OPEN)  # deltas отсутствует
    labels = screen._kpi_row.findChildren(QLabel)
    texts = [l.text() for l in labels]
    chip_texts = [t for t in texts if "%" in t and ("↑" in t or "↓" in t)]
    assert chip_texts == []


def test_styled_background_attribute_set(screen):
    """WA_StyledBackground обязателен — без него фон не красится в bg_light
    и сквозь дыры между карточками пробивается системный чёрный."""
    from PySide6.QtCore import Qt

    assert screen.testAttribute(Qt.WA_StyledBackground)
