"""CategoryEditDialog — print_station dropdown."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    return c


@pytest.fixture
def stations():
    return [
        {"id": 10, "name": "Касса", "system_code": "cashier",
         "is_system": True, "printer": None,
         "is_active": True, "sort_order": 0},
        {"id": 12, "name": "Горячий цех", "system_code": "",
         "is_system": False, "printer": None,
         "is_active": True, "sort_order": 2},
        {"id": 13, "name": "Бар", "system_code": "",
         "is_system": False, "printer": None,
         "is_active": True, "sort_order": 4},
    ]


def test_dialog_loads_stations_when_not_passed(qtbot, mock_client):
    """reasons=None → диалог сам тянет /printing/stations/."""
    from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

    mock_client.get.return_value = []
    d = CategoryEditDialog(client=mock_client, category=None)
    qtbot.addWidget(d)
    args, _ = mock_client.get.call_args
    assert args[0] == "/printing/stations/"


def test_dialog_renders_station_combo(qtbot, mock_client, stations):
    from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

    d = CategoryEditDialog(
        client=mock_client, category=None, stations=stations,
    )
    qtbot.addWidget(d)
    # Combobox должен иметь "— Без цеха —" + 3 station
    combo = d.station_combo
    assert combo.count() == 4
    assert combo.itemData(0) is None
    # Ищем «Горячий цех»
    found = False
    for i in range(combo.count()):
        if "Горячий цех" in combo.itemText(i):
            found = True
            break
    assert found


def test_dialog_save_includes_print_station(qtbot, mock_client, stations):
    from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

    mock_client.request.return_value = {"id": 5}
    d = CategoryEditDialog(
        client=mock_client, category=None, stations=stations,
    )
    qtbot.addWidget(d)
    d.name_edit.setText("Шашлыки")
    # Выбрать «Горячий цех» (id=12)
    for i in range(d.station_combo.count()):
        if d.station_combo.itemData(i) == 12:
            d.station_combo.setCurrentIndex(i)
            break

    btns = d.findChildren(QPushButton)
    save = next(b for b in btns if b.text() == "Сохранить")
    qtbot.mouseClick(save, Qt.LeftButton)

    args, kwargs = mock_client.request.call_args
    body = kwargs["json"]
    assert body["name"] == "Шашлыки"
    assert body["print_station"] == 12


def test_dialog_save_with_no_station(qtbot, mock_client, stations):
    """Категория без цеха: print_station=None в body."""
    from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

    mock_client.request.return_value = {"id": 5}
    d = CategoryEditDialog(
        client=mock_client, category=None, stations=stations,
    )
    qtbot.addWidget(d)
    d.name_edit.setText("Без цеха")
    # «Без цеха» опция = индекс 0
    d.station_combo.setCurrentIndex(0)

    btns = d.findChildren(QPushButton)
    save = next(b for b in btns if b.text() == "Сохранить")
    qtbot.mouseClick(save, Qt.LeftButton)

    args, kwargs = mock_client.request.call_args
    assert kwargs["json"]["print_station"] is None


def test_dialog_loads_existing_print_station(qtbot, mock_client, stations):
    """Edit-mode: pre-select станции из category.print_station."""
    from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

    d = CategoryEditDialog(
        client=mock_client,
        category={
            "id": 7, "name": "Салаты", "sort_order": 1,
            "print_station": 13,  # Бар
        },
        stations=stations,
    )
    qtbot.addWidget(d)
    assert d.station_combo.currentData() == 13
