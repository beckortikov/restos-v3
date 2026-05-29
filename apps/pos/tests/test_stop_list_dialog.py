"""StopListDialog: stop_list / restore endpoints + StopReasonDialog flow."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def items():
    return [
        {"id": 1, "name": "Плов", "price": "45.00", "category": 1,
         "is_available": True, "sort_order": 1, "stop_reason": "",
         "stop_until": None, "emoji": ""},
        {"id": 2, "name": "Лагман", "price": "25.00", "category": 1,
         "is_available": False, "sort_order": 2,
         "stop_reason": "Закончилась лапша", "stop_until": "2026-05-15",
         "emoji": ""},
    ]


@pytest.fixture
def dlg(qtbot, client, items, monkeypatch):
    """Создаём диалог, подменяя GET /menu/items/."""
    client.get.return_value = items
    from pos.screens.stop_list_dialog import StopListDialog

    d = StopListDialog(client=client)
    qtbot.addWidget(d)
    yield d


# -------- Render --------


def test_renders_all_items_initially(dlg):
    assert len(dlg._row_widgets) == 2


def test_in_stop_row_shows_reason(dlg):
    """Лагман в стопе — должна быть строка с причиной."""
    from PySide6.QtWidgets import QLabel

    labels = dlg._row_widgets[2].findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("Закончилась лапша" in t for t in texts)


def test_counter_shows_in_stop_count(dlg):
    assert "1" in dlg._counter.text()  # 1 in stop


# -------- Toggle: in-stock → stop --------


def test_toggle_inventory_to_stop_opens_reason_dialog(qtbot, dlg, client, monkeypatch):
    """При снятии (available → stop) открывается StopReasonDialog."""
    from pos.screens import stop_list_dialog as mod

    captured: list[dict] = []

    class _FakeDialog:
        DialogCode = type("DC", (), {"Accepted": 1})

        def __init__(self, item_name, parent=None):
            self.reason = "test reason"
            self.until_iso = "2026-05-20"

        def exec(self):
            return 1

    monkeypatch.setattr(mod, "StopReasonDialog", _FakeDialog, raising=False)
    # Но он импортируется внутри _toggle, поэтому надо пропатчить модуль
    import sys as _sys
    fake_mod = type(_sys.modules["pos.screens.stop_list_dialog"])(
        "pos.screens.stop_reason_dialog"
    )
    fake_mod.StopReasonDialog = _FakeDialog
    monkeypatch.setitem(_sys.modules, "pos.screens.stop_reason_dialog", fake_mod)

    client.post.return_value = {
        "data": {"id": 1, "name": "Плов", "price": "45.00", "category": 1,
                 "is_available": False, "sort_order": 1,
                 "stop_reason": "test reason", "stop_until": "2026-05-20"},
    }
    dlg._toggle(1)
    qtbot.waitUntil(lambda: client.post.called, timeout=2000)

    args, kwargs = client.post.call_args
    assert args[0] == "/menu/items/1/stop_list/"
    assert kwargs["json"]["reason"] == "test reason"
    assert kwargs["json"]["until"] == "2026-05-20"


# -------- Toggle: stop → in-stock (restore) --------


def test_toggle_stop_to_inventory_calls_restore_no_dialog(qtbot, dlg, client):
    """При возврате (stop → in-stock) сразу POST /restore/ без диалога."""
    client.post.return_value = {
        "data": {"id": 2, "name": "Лагман", "price": "25.00", "category": 1,
                 "is_available": True, "sort_order": 2,
                 "stop_reason": "", "stop_until": None},
    }
    dlg._toggle(2)
    qtbot.waitUntil(lambda: client.post.called, timeout=2000)

    args, _kwargs = client.post.call_args
    assert args[0] == "/menu/items/2/restore/"


# -------- StopReasonDialog --------


def test_reason_dialog_default_no_until(qtbot):
    from pos.screens.stop_reason_dialog import StopReasonDialog

    d = StopReasonDialog(item_name="Плов")
    qtbot.addWidget(d)
    assert not d._until_chk.isChecked()
    assert not d._until_input.isEnabled()


def test_reason_dialog_save_no_until(qtbot):
    from pos.screens.stop_reason_dialog import StopReasonDialog

    d = StopReasonDialog(item_name="Плов")
    qtbot.addWidget(d)
    d._reason_input.setPlainText("Закончилась говядина")
    d._on_save()
    assert d.reason == "Закончилась говядина"
    assert d.until_iso is None


def test_reason_dialog_save_with_until(qtbot):
    from datetime import date

    from pos.screens.stop_reason_dialog import StopReasonDialog

    d = StopReasonDialog(item_name="Плов")
    qtbot.addWidget(d)
    d._until_chk.setChecked(True)
    assert d._until_input.isEnabled()
    d._reason_input.setPlainText("X")
    d._on_save()
    assert d.until_iso is not None
    # Должна быть валидная дата (после today)
    parsed = date.fromisoformat(d.until_iso)
    assert parsed >= date.today()
