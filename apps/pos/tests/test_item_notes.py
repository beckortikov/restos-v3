"""Item notes: NotePickerDialog + интеграция в CartPanel + MenuScreen."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = []
    return c


@pytest.fixture
def notes():
    return [
        {"id": 1, "label": "Без лука", "sort_order": 0, "is_active": True},
        {"id": 2, "label": "Острее", "sort_order": 1, "is_active": True},
        {"id": 3, "label": "Хорошо прожарить", "sort_order": 2, "is_active": True},
        {"id": 4, "label": "Disabled", "sort_order": 99, "is_active": False},
    ]


# -------- NotePickerDialog --------


def test_picker_renders_active_notes_only(qtbot, mock_client, notes):
    from PySide6.QtWidgets import QLabel
    from pos.screens.note_picker_dialog import NotePickerDialog

    d = NotePickerDialog(
        client=mock_client, item_name="Плов",
        current_note="", notes=notes,
    )
    qtbot.addWidget(d)
    btns = d.findChildren(QPushButton)
    chip_texts = {b.text() for b in btns}
    assert "Без лука" in chip_texts
    assert "Острее" in chip_texts
    # Inactive не попал
    assert "Disabled" not in chip_texts


def test_picker_chip_click_fills_input(qtbot, mock_client, notes):
    from pos.screens.note_picker_dialog import NotePickerDialog

    d = NotePickerDialog(
        client=mock_client, item_name="Плов",
        current_note="", notes=notes,
    )
    qtbot.addWidget(d)
    btns = d.findChildren(QPushButton)
    chip = next(b for b in btns if b.text() == "Без лука")
    qtbot.mouseClick(chip, Qt.LeftButton)
    assert d._note_edit.text() == "Без лука"


def test_picker_save_emits_chosen_note(qtbot, mock_client, notes):
    from pos.screens.note_picker_dialog import NotePickerDialog

    d = NotePickerDialog(
        client=mock_client, item_name="Плов",
        current_note="Острее", notes=notes,
    )
    qtbot.addWidget(d)
    fired: list[str] = []
    d.note_chosen.connect(lambda n: fired.append(n))

    btns = d.findChildren(QPushButton)
    save = next(b for b in btns if b.text() == "Сохранить")
    qtbot.mouseClick(save, Qt.LeftButton)
    assert fired == ["Острее"]
    assert d.chosen_note == "Острее"


def test_picker_clear_button_empties_input(qtbot, mock_client, notes):
    from pos.screens.note_picker_dialog import NotePickerDialog

    d = NotePickerDialog(
        client=mock_client, item_name="Плов",
        current_note="Острее", notes=notes,
    )
    qtbot.addWidget(d)
    btns = d.findChildren(QPushButton)
    clear = next(b for b in btns if b.text() == "Очистить")
    qtbot.mouseClick(clear, Qt.LeftButton)
    assert d._note_edit.text() == ""


def test_picker_lazy_fetch_when_notes_not_passed(qtbot, mock_client):
    from pos.screens.note_picker_dialog import NotePickerDialog

    mock_client.get.return_value = [
        {"id": 1, "label": "X", "sort_order": 0, "is_active": True},
    ]
    d = NotePickerDialog(client=mock_client, item_name="Y", current_note="")
    qtbot.addWidget(d)
    args, kwargs = mock_client.get.call_args
    assert args[0] == "/menu/notes/"


# -------- CartPanel notes --------


def test_cart_separates_items_by_note(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = {"id": 10, "name": "Плов", "price": "45.00"}
    cart.add_item(item, note="")
    cart.add_item(item, note="Без лука")
    cart.add_item(item, note="Без лука")

    items = cart.get_items()
    assert len(items) == 2
    by_note = {it["note"]: it["qty"] for it in items}
    assert by_note[""] == 1
    assert by_note["Без лука"] == 2


def test_cart_change_qty_per_note(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = {"id": 10, "name": "Плов", "price": "45.00"}
    cart.add_item(item, note="Острее")
    cart.add_item(item, note="Острее")
    cart.change_qty(10, -1, "Острее")
    items = cart.get_items()
    assert items[0]["qty"] == 1


def test_cart_set_item_note_renames(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = {"id": 10, "name": "Плов", "price": "45.00"}
    cart.add_item(item, note="")
    cart.set_item_note(10, "", "Без лука")
    items = cart.get_items()
    assert items[0]["note"] == "Без лука"
    assert items[0]["qty"] == 1


def test_cart_set_item_note_merges_into_existing(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = {"id": 10, "name": "Плов", "price": "45.00"}
    cart.add_item(item, note="Острее")
    cart.add_item(item, note="Острее")  # qty=2 в Острее
    cart.add_item(item, note="")  # qty=1 без note
    cart.set_item_note(10, "", "Острее")  # перенос в Острее
    items = cart.get_items()
    assert len(items) == 1
    assert items[0]["note"] == "Острее"
    assert items[0]["qty"] == 3  # 2 + 1


def test_cart_note_button_emits_signal(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = {"id": 10, "name": "Плов", "price": "45.00"}
    cart.add_item(item, note="Без лука")

    fired: list[tuple] = []
    cart.note_edit_requested.connect(lambda mid, note: fired.append((mid, note)))

    btns = cart.findChildren(QPushButton)
    note_btn = next(b for b in btns if "Без лука" in b.text())
    qtbot.mouseClick(note_btn, Qt.LeftButton)
    assert fired == [(10, "Без лука")]


def test_cart_get_items_without_note(qtbot):
    """Backwards: add_item без note → запись с note=''."""
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    cart.add_item({"id": 10, "name": "X", "price": "1.00"})
    items = cart.get_items()
    assert items == [{"menu_item_id": 10, "qty": 1, "note": ""}]
