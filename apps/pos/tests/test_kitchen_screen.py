"""KitchenScreen: канбан повара, действия по статусам, фильтрация колонок."""
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
    from pos.screens.kitchen_screen import KitchenScreen

    s = KitchenScreen(state)
    qtbot.addWidget(s)
    yield s


def _item(iid: int, status: str, **kw) -> dict:
    base = {
        "id": iid, "order_id": 100 + iid, "name_at_order": "Плов",
        "qty": 2, "table_name": "Стол 5", "category_name": "Горячее",
        "kitchen_status": status, "note": "", "order_type": "hall",
        "created_at": "2026-05-09T19:00:00+00:00",
    }
    base.update(kw)
    return base


# -------- Reload + render --------


def test_reload_request_path(qtbot, screen, state):
    state.client.get.return_value = {"data": [], "meta": {"total": 0}}
    screen.reload()
    args, _ = state.client.get.call_args
    assert args[0] == "/kitchen/items/"


def test_renders_three_columns(screen):
    assert set(screen._column_layouts.keys()) == {"new", "cooking", "ready"}


def test_items_distributed_by_status(qtbot, screen, state):
    state.client.get.return_value = {
        "data": [
            _item(1, "new"),
            _item(2, "cooking"),
            _item(3, "ready"),
            _item(4, "new"),
        ],
        "meta": {"total": 4},
    }
    screen.reload()
    # Counters: 2 / 1 / 1
    assert "2" in screen._column_counters["new"].text()
    assert "1" in screen._column_counters["cooking"].text()
    assert "1" in screen._column_counters["ready"].text()


def test_empty_columns_show_placeholder(qtbot, screen, state):
    from PySide6.QtWidgets import QLabel

    state.client.get.return_value = {"data": [], "meta": {"total": 0}}
    screen.reload()
    for status in ("new", "cooking", "ready"):
        layout = screen._column_layouts[status]
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        labels = [w for w in widgets if isinstance(w, QLabel)]
        assert any("Пусто" in l.text() for l in labels)


def test_card_renders_action_button(qtbot, screen, state):
    from PySide6.QtWidgets import QPushButton

    state.client.get.return_value = {
        "data": [_item(1, "new")],
        "meta": {"total": 1},
    }
    screen.reload()
    new_layout = screen._column_layouts["new"]
    card = new_layout.itemAt(0).widget()
    btns = card.findChildren(QPushButton)
    texts = [b.text() for b in btns]
    assert "Принять" in texts


def test_action_button_calls_correct_endpoint(qtbot, screen, state):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    state.client.get.return_value = {
        "data": [_item(7, "cooking")],
        "meta": {"total": 1},
    }
    screen.reload()
    state.client.post.return_value = {
        "data": _item(7, "ready"),
    }

    cooking_layout = screen._column_layouts["cooking"]
    card = cooking_layout.itemAt(0).widget()
    ready_btn = next(
        b for b in card.findChildren(QPushButton) if b.text() == "Готово"
    )
    qtbot.mouseClick(ready_btn, Qt.LeftButton)
    args, _ = state.client.post.call_args
    assert args[0] == "/kitchen/items/7/mark_ready/"


def test_card_shows_note_when_present(qtbot, screen, state):
    from PySide6.QtWidgets import QLabel

    state.client.get.return_value = {
        "data": [_item(1, "new", note="Без лука")],
        "meta": {"total": 1},
    }
    screen.reload()
    card = screen._column_layouts["new"].itemAt(0).widget()
    labels = card.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("Без лука" in t for t in texts)


def test_card_shows_takeaway_label(qtbot, screen, state):
    from PySide6.QtWidgets import QLabel

    state.client.get.return_value = {
        "data": [_item(1, "new", order_type="takeaway", table_name=None)],
        "meta": {"total": 1},
    }
    screen.reload()
    card = screen._column_layouts["new"].itemAt(0).widget()
    labels = card.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("С собой" in t for t in texts)


def test_set_cook_updates_label(screen):
    screen.set_cook("Шеф Мирзо")
    assert screen._cook_lbl.text() == "Шеф Мирзо"


def test_logout_button_emits_signal(qtbot, screen):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    fired: list[bool] = []
    screen.logout_requested.connect(lambda: fired.append(True))
    btns = screen.findChildren(QPushButton)
    logout_btn = next(b for b in btns if b.text() == "Выйти")
    qtbot.mouseClick(logout_btn, Qt.LeftButton)
    assert fired == [True]


def test_sound_alert_fires_on_new_arrival(qtbot, screen, state, monkeypatch):
    """При появлении новой позиции в колонке NEW (не первой загрузке) — beep."""
    state.client.get.return_value = {
        "data": [_item(1, "new")], "meta": {"total": 1},
    }
    screen.reload()  # первая загрузка — beep не должен сработать
    beeps: list[bool] = []
    monkeypatch.setattr(screen, "_play_alert", lambda: beeps.append(True))

    state.client.get.return_value = {
        "data": [_item(1, "new"), _item(2, "new")], "meta": {"total": 2},
    }
    screen.reload()
    assert beeps == [True]


def test_sound_alert_does_not_fire_on_first_load(qtbot, screen, state, monkeypatch):
    """На первой загрузке (нет prev снимка) — alert не срабатывает."""
    beeps: list[bool] = []
    monkeypatch.setattr(screen, "_play_alert", lambda: beeps.append(True))
    state.client.get.return_value = {
        "data": [_item(1, "new"), _item(2, "new")], "meta": {"total": 2},
    }
    screen.reload()
    assert beeps == []


def test_sound_toggle_disables_alert(qtbot, screen, state, monkeypatch):
    """При выключенном sound_btn новые позиции не вызывают _play_alert."""
    state.client.get.return_value = {
        "data": [_item(1, "new")], "meta": {"total": 1},
    }
    screen.reload()
    screen._sound_btn.setChecked(False)
    assert not screen._sound_enabled
    beeps: list[bool] = []
    monkeypatch.setattr(screen, "_play_alert", lambda: beeps.append(True))

    state.client.get.return_value = {
        "data": [_item(1, "new"), _item(2, "new")], "meta": {"total": 2},
    }
    screen.reload()
    assert beeps == []


def test_sound_toggle_icon_changes(screen):
    screen._sound_btn.setChecked(True)
    assert screen._sound_btn.text() == "🔔"
    screen._sound_btn.setChecked(False)
    assert screen._sound_btn.text() == "🔕"


def test_polling_can_be_started_and_stopped(screen):
    """start_polling запускает таймер; stop_polling — останавливает."""
    screen._poll_timer.stop()
    assert not screen._poll_timer.isActive()
    # Не вызываем reload (мокнем client.get)
    screen.state.client.get.return_value = {"data": []}
    screen.start_polling()
    assert screen._poll_timer.isActive()
    screen.stop_polling()
    assert not screen._poll_timer.isActive()
