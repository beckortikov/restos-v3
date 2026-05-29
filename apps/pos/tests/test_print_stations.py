"""PrintersSection: динамические цеха печати + paper size в EditDialog."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = []
    return c


@pytest.fixture
def section(qtbot, mock_client):
    from pos.screens.settings_sections.printers_section import PrintersSection

    s = PrintersSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def _setup(mock_client, printers, stations):
    def _get(path, **kwargs):
        if "/printing/stations/" in path:
            return stations
        return printers
    mock_client.get.side_effect = _get


# -------- Stations CRUD --------


def test_stations_card_renders(qtbot, section, mock_client):
    printers = [
        {"id": 1, "name": "Касса", "kind": "virtual", "address": "k",
         "paper_size": "80mm", "is_default": True, "is_active": True},
    ]
    stations = [
        {"id": 10, "name": "Касса", "system_code": "cashier",
         "is_system": True, "printer": 1, "printer_name": "Касса",
         "is_active": True, "sort_order": 0},
        {"id": 11, "name": "Горячий цех", "system_code": "",
         "is_system": False, "printer": None, "printer_name": None,
         "is_active": True, "sort_order": 2},
    ]
    _setup(mock_client, printers, stations)
    section.reload()
    qtbot.waitUntil(
        lambda: len(section._stations) == 2, timeout=2000
    )
    assert section._stations_layout.count() == 2


def test_station_printer_change_calls_api(qtbot, section, mock_client):
    printers = [
        {"id": 1, "name": "Касса", "kind": "virtual", "address": "k",
         "paper_size": "80mm", "is_default": True, "is_active": True},
        {"id": 2, "name": "Кухня", "kind": "virtual", "address": "kit",
         "paper_size": "58mm", "is_default": False, "is_active": True},
    ]
    stations = [
        {"id": 22, "name": "Бар", "system_code": "", "is_system": False,
         "printer": None, "printer_name": None,
         "is_active": True, "sort_order": 4},
    ]
    _setup(mock_client, printers, stations)
    mock_client.request.return_value = {"id": 22, "printer": 2}

    section.reload()
    qtbot.waitUntil(
        lambda: section._stations_layout.count() == 1, timeout=2000
    )

    combos = section._stations_holder.findChildren(QComboBox)
    assert len(combos) == 1
    # index: 0=Не выбран, 1=Касса (id=1), 2=Кухня (id=2)
    combos[0].setCurrentIndex(2)
    qtbot.waitUntil(lambda: mock_client.request.called, timeout=2000)
    args, kwargs = mock_client.request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "/printing/stations/22/"
    assert kwargs["json"] == {"printer": 2}


def test_system_station_no_delete_button(qtbot, section, mock_client):
    """is_system=True → нет кнопки удаления."""
    printers = []
    stations = [
        {"id": 10, "name": "Касса", "system_code": "cashier",
         "is_system": True, "printer": None, "printer_name": None,
         "is_active": True, "sort_order": 0},
    ]
    _setup(mock_client, printers, stations)
    section.reload()
    qtbot.waitUntil(
        lambda: section._stations_layout.count() == 1, timeout=2000
    )

    # В строке должен быть combobox, но НЕ trash-кнопка
    btns = section._stations_holder.findChildren(QPushButton)
    trash_btns = [b for b in btns if b.toolTip() == "Удалить цех"]
    assert trash_btns == []


def test_custom_station_has_delete_button(qtbot, section, mock_client):
    printers = []
    stations = [
        {"id": 11, "name": "Горячий цех", "system_code": "",
         "is_system": False, "printer": None, "printer_name": None,
         "is_active": True, "sort_order": 2},
    ]
    _setup(mock_client, printers, stations)
    section.reload()
    qtbot.waitUntil(
        lambda: section._stations_layout.count() == 1, timeout=2000
    )
    btns = section._stations_holder.findChildren(QPushButton)
    trash_btns = [b for b in btns if b.toolTip() == "Удалить цех"]
    assert len(trash_btns) == 1


def test_add_station_calls_api(qtbot, section, mock_client):
    printers = []
    stations = []
    _setup(mock_client, printers, stations)
    mock_client.request.return_value = {
        "id": 99, "name": "Кондитерский", "system_code": "",
        "is_system": False, "is_active": True, "sort_order": 99,
    }

    with patch(
        "PySide6.QtWidgets.QInputDialog.getText",
        return_value=("Кондитерский", True),
    ):
        section._on_add_station()
        qtbot.waitUntil(lambda: mock_client.request.called, timeout=2000)

    args, kwargs = mock_client.request.call_args
    assert args[0] == "POST"
    assert args[1] == "/printing/stations/"
    assert kwargs["json"]["name"] == "Кондитерский"


def test_add_station_cancelled(qtbot, section, mock_client):
    with patch(
        "PySide6.QtWidgets.QInputDialog.getText",
        return_value=("", False),
    ):
        section._on_add_station()
    assert not mock_client.request.called


# -------- Printer paper size in edit dialog --------


def test_printer_edit_dialog_default_80mm(qtbot, mock_client):
    """Открытие dialog без printer (=create mode) — paper_combo по умолчанию 80mm."""
    from pos.screens.settings_sections.printer_edit_dialog import PrinterEditDialog

    d = PrinterEditDialog(client=mock_client, printer=None)
    qtbot.addWidget(d)
    assert d.paper_combo.currentData() == "80mm"


def test_printer_edit_dialog_loads_existing_paper_size(qtbot, mock_client):
    from pos.screens.settings_sections.printer_edit_dialog import PrinterEditDialog

    d = PrinterEditDialog(
        client=mock_client,
        printer={
            "id": 1, "name": "X", "kind": "tcp", "address": "1.2.3.4",
            "paper_size": "58mm", "is_default": False, "is_active": True,
        },
    )
    qtbot.addWidget(d)
    assert d.paper_combo.currentData() == "58mm"


def test_printer_edit_dialog_save_includes_paper_size(qtbot, mock_client):
    from pos.screens.settings_sections.printer_edit_dialog import PrinterEditDialog

    mock_client.request.return_value = {"id": 99}
    d = PrinterEditDialog(client=mock_client, printer=None)
    qtbot.addWidget(d)
    d.name_edit.setText("Test")
    # Switch to 58mm (index 0 in PAPER_CHOICES)
    d.paper_combo.setCurrentIndex(0)
    btns = d.findChildren(QPushButton)
    save = next(b for b in btns if b.text() == "Сохранить")
    qtbot.mouseClick(save, Qt.LeftButton)

    args, kwargs = mock_client.request.call_args
    body = kwargs["json"]
    assert body["paper_size"] == "58mm"
