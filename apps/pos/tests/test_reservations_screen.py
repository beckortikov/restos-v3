"""ReservationsScreen + ReservationFormDialog + бейдж на TableCard."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def state():
    s = MagicMock()
    s.client = MagicMock()
    s.tables = [
        {"id": 1, "name": "Стол 1", "number": 1, "zone_name": "Зал",
         "capacity": 4, "status": "free"},
        {"id": 2, "name": "Стол 2", "number": 2, "zone_name": "Зал",
         "capacity": 6, "status": "free"},
    ]
    s.online_changed = MagicMock()
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.reservations_screen import ReservationsScreen

    s = ReservationsScreen(state)
    qtbot.addWidget(s)
    yield s


# -------- Screen --------


def test_default_mode_is_active(screen):
    assert screen._mode == "active"


def test_reload_active_mode_passes_active_param(qtbot, screen, state):
    state.client.get.return_value = {"data": [], "meta": {"total": 0}}
    screen.reload()
    args, kwargs = state.client.get.call_args
    assert args[0] == "/reservations/"
    assert kwargs["params"]["active"] == "true"


def test_reload_today_mode_passes_date_range(qtbot, screen, state):
    from datetime import date

    state.client.get.return_value = {"data": [], "meta": {"total": 0}}
    screen.set_mode("today")
    args, kwargs = state.client.get.call_args
    today = date.today().isoformat()
    assert kwargs["params"]["from"] == today
    assert kwargs["params"]["to"] == today


def test_empty_state(qtbot, screen, state):
    from PySide6.QtWidgets import QLabel

    state.client.get.return_value = {"data": [], "meta": {"total": 0}}
    screen.reload()
    labels = screen._rows_holder.findChildren(QLabel)
    assert any("нет" in l.text().lower() for l in labels)


def test_renders_actions_for_pending_status(qtbot, screen, state):
    from PySide6.QtWidgets import QPushButton

    state.client.get.return_value = {
        "data": [
            {
                "id": 7, "table": 1, "table_name": "Стол 5",
                "customer_name": "Иван", "customer_phone": "+7900",
                "party_size": 4,
                "scheduled_at": "2026-05-09T19:30:00+00:00",
                "status": "pending",
            },
        ],
        "meta": {"total": 1},
    }
    screen.reload()
    btns = screen._rows_holder.findChildren(QPushButton)
    texts = {b.text() for b in btns}
    assert "Подтвердить" in texts
    assert "Усадить" in texts
    assert "Не пришли" in texts
    assert "Отмена" in texts


def test_action_calls_correct_endpoint(qtbot, screen, state):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    state.client.get.return_value = {
        "data": [
            {
                "id": 7, "table": 1, "table_name": "Стол 5",
                "customer_name": "Иван", "party_size": 2,
                "scheduled_at": "2026-05-09T19:30:00+00:00",
                "status": "pending",
            },
        ],
        "meta": {"total": 1},
    }
    screen.reload()
    state.client.post.return_value = {"data": {"id": 7, "status": "confirmed"}}

    btns = screen._rows_holder.findChildren(QPushButton)
    confirm_btn = next(b for b in btns if b.text() == "Подтвердить")
    qtbot.mouseClick(confirm_btn, Qt.LeftButton)
    args, kwargs = state.client.post.call_args
    assert args[0] == "/reservations/7/confirm/"


def test_renders_no_actions_for_seated(qtbot, screen, state):
    from PySide6.QtWidgets import QPushButton

    state.client.get.return_value = {
        "data": [
            {
                "id": 7, "table": 1, "table_name": "Стол 5",
                "customer_name": "Иван", "party_size": 2,
                "scheduled_at": "2026-05-09T19:30:00+00:00",
                "status": "seated",
            },
        ],
        "meta": {"total": 1},
    }
    screen.reload()
    btns = screen._rows_holder.findChildren(QPushButton)
    action_texts = {b.text() for b in btns} - {"+ Новая резервация", "← Назад", "Активные", "На сегодня", "Все"}
    # Никаких кнопок-действий
    assert action_texts == set()


# -------- Form dialog --------


def test_form_dialog_save_disabled_until_name(qtbot, state):
    from pos.screens.reservation_form_dialog import ReservationFormDialog

    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)
    assert not d._save_btn.isEnabled()
    d._name.setText("Иван")
    assert d._save_btn.isEnabled()


def test_form_dialog_posts_correct_body(qtbot, state):
    from pos.screens.reservation_form_dialog import ReservationFormDialog
    from PySide6.QtCore import Qt

    state.client.post.return_value = {"data": {"id": 1, "status": "pending"}}
    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)
    d._name.setText("Иван")
    d._phone.setText("+7900")
    # Touch UI: меняем party и duration через сервисные методы
    d._change_party(+3)  # default 2 → 5
    d._set_duration(90)
    if d._table_combo is not None:
        d._table_combo.setCurrentIndex(0)

    fired: list[dict] = []
    d.reservation_created.connect(lambda r: fired.append(r))

    qtbot.mouseClick(d._save_btn, Qt.LeftButton)

    args, kwargs = state.client.post.call_args
    assert args[0] == "/reservations/"
    body = kwargs["json"]
    assert body["customer_name"] == "Иван"
    assert body["customer_phone"] == "+7900"
    assert body["party_size"] == 5
    assert body["duration_min"] == 90
    assert body["table"] == 1
    assert "scheduled_at" in body
    assert fired


def test_form_dialog_party_step_buttons(qtbot, state):
    from pos.screens.reservation_form_dialog import ReservationFormDialog

    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)
    assert d._party_size == 2
    d._change_party(+1)
    assert d._party_size == 3
    assert d._guests_lbl.text() == "3"
    d._change_party(-2)
    assert d._party_size == 1  # min=1
    d._change_party(-5)
    assert d._party_size == 1  # clamp


def test_form_dialog_time_presets(qtbot, state):
    from datetime import datetime, timedelta

    from pos.screens.reservation_form_dialog import ReservationFormDialog

    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)

    d._set_in_minutes(60)
    diff = (d._scheduled_at - datetime.now()).total_seconds() / 60
    # Около 60 мин ± округление до 15 мин
    assert 45 <= diff <= 75


def test_form_dialog_tomorrow_hour_preset(qtbot, state):
    from datetime import datetime, timedelta

    from pos.screens.reservation_form_dialog import ReservationFormDialog

    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)

    d._set_tomorrow_hour(19)
    expected_date = (datetime.now().date() + timedelta(days=1))
    assert d._scheduled_at.date() == expected_date
    assert d._scheduled_at.hour == 19
    assert d._scheduled_at.minute == 0


def test_form_dialog_shift_minutes_does_not_go_to_past(qtbot, state):
    from datetime import datetime, timedelta

    from pos.screens.reservation_form_dialog import ReservationFormDialog

    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)

    # Сдвигаем сильно назад
    d._shift_minutes(-1000)
    # Должно остаться в будущем
    assert d._scheduled_at > datetime.now() - timedelta(minutes=10)


def test_form_dialog_single_table_hides_combobox(qtbot, state):
    """Когда стол один — combobox не показываем (предзаполнен)."""
    from pos.screens.reservation_form_dialog import ReservationFormDialog

    d = ReservationFormDialog(
        client=state.client,
        tables=[state.tables[0]],
    )
    qtbot.addWidget(d)
    assert d._table_combo is None


def test_form_dialog_save_button_not_stuck(qtbot, state, monkeypatch):
    """Регрессия: после ошибки backend кнопка восстанавливается."""
    from pos.http_client import ApiError
    from pos.screens.reservation_form_dialog import ReservationFormDialog
    from pos.screens import reservation_form_dialog as mod

    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: None)
    state.client.post.side_effect = ApiError(
        "RESERVATION_CONFLICT", "уже занято", 409,
    )
    d = ReservationFormDialog(client=state.client, tables=state.tables)
    qtbot.addWidget(d)
    d._name.setText("X")
    d._on_save()
    # После ошибки — кнопка снова активна, текст восстановлен
    assert d._save_btn.isEnabled()
    assert "Создать" in d._save_btn.text()
    assert not d._submitting


# -------- Reservation badge on TableCard --------


def test_table_card_renders_reservation_badge(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtWidgets import QLabel

    card = TableCard({
        "id": 5, "name": "Стол 5", "number": 5, "status": "free",
        "next_reservation": {
            "id": 1,
            "scheduled_at": "2026-05-09T19:30:00+00:00",
            "customer_name": "Иван",
            "party_size": 4,
            "status": "confirmed",
        },
    })
    qtbot.addWidget(card)
    labels = card.findChildren(QLabel)
    texts = [l.text() for l in labels]
    # Бейдж содержит «Резерв» и время
    assert any("Резерв" in t for t in texts)
    assert any("19:30" in t for t in texts)
    # Размер компании ×4
    assert any("×4" in t for t in texts)


def test_table_card_no_badge_when_no_reservation(qtbot):
    from pos.widgets.table_card import TableCard
    from PySide6.QtWidgets import QLabel

    card = TableCard({
        "id": 5, "name": "Стол 5", "number": 5, "status": "free",
        "next_reservation": None,
    })
    qtbot.addWidget(card)
    labels = card.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert not any("Резерв" in t for t in texts)
