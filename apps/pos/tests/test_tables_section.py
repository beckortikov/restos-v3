"""Smoke-тесты TablesSection (Settings → Зоны и столы)."""
from unittest.mock import MagicMock


def test_tables_section_renders_zones_and_tables(qtbot):
    from pos.screens.settings_sections.tables_section import TablesSection

    client = MagicMock()
    sec = TablesSection(client)
    qtbot.addWidget(sec)

    sec._on_loaded(
        zones=[
            {"id": 1, "name": "Зал", "sort_order": 0},
            {"id": 2, "name": "Терраса", "sort_order": 1},
        ],
        tables=[
            {
                "id": 10, "zone": 1, "number": 1, "name": "Стол 1",
                "capacity": 4, "status": "free", "waiter_name": None,
            },
            {
                "id": 11, "zone": 1, "number": 2, "name": "Стол 2",
                "capacity": 2, "status": "occupied",
                "waiter_name": "Карим",
            },
            {
                "id": 12, "zone": 2, "number": 10, "name": "Терраса 1",
                "capacity": 6, "status": "free", "waiter_name": None,
            },
        ],
    )
    # Активная зона по дефолту — первая (Зал, id=1)
    assert sec._active_zone_id == 1
    # Заголовок столов содержит «2» (количество столов в зоне Зал)
    assert "(2)" in sec._tables_head.text()


def test_tables_section_switch_zone(qtbot):
    from pos.screens.settings_sections.tables_section import TablesSection

    client = MagicMock()
    sec = TablesSection(client)
    qtbot.addWidget(sec)
    sec._on_loaded(
        zones=[
            {"id": 1, "name": "Зал", "sort_order": 0},
            {"id": 2, "name": "Терраса", "sort_order": 1},
        ],
        tables=[
            {"id": 10, "zone": 1, "number": 1, "name": "Т1",
             "capacity": 2, "status": "free"},
            {"id": 12, "zone": 2, "number": 5, "name": "T5",
             "capacity": 2, "status": "free"},
        ],
    )
    sec._select_zone(2)
    assert sec._active_zone_id == 2
    # В Террасе 1 стол
    assert "(1)" in sec._tables_head.text()


def test_status_label_map():
    from pos.screens.settings_sections.tables_section import TablesSection

    assert TablesSection._status_label("free") == "свободен"
    assert TablesSection._status_label("occupied") == "занят"
    assert TablesSection._status_label("bill_requested") == "счёт"
    assert TablesSection._status_label("merged") == "объединён"
    assert TablesSection._status_label(None) == "—"
