"""Smoke-тесты InventorySection (Phase 7D-1)."""
from unittest.mock import MagicMock


def test_inventory_section_renders_ingredients(qtbot):
    from pos.screens.settings_sections.inventory_section import InventorySection

    client = MagicMock()
    sec = InventorySection(client)
    qtbot.addWidget(sec)

    sec._on_loaded([
        {
            "id": 1, "name": "Говядина", "unit": "kg",
            "current_qty": "5.000", "avg_cost_per_unit": "120.0000",
            "low_stock_threshold": "2.000", "is_low_stock": False,
            "is_active": True, "sort_order": 0,
        },
        {
            "id": 2, "name": "Соль", "unit": "g",
            "current_qty": "50.000", "avg_cost_per_unit": "0.0100",
            "low_stock_threshold": "100.000", "is_low_stock": True,
            "is_active": True, "sort_order": 1,
        },
        {
            "id": 3, "name": "Старый", "unit": "kg",
            "current_qty": "0.000", "avg_cost_per_unit": "0",
            "is_low_stock": False, "is_active": False, "sort_order": 99,
        },
    ])
    assert sec._table.rowCount() == 3
    assert sec._table.item(0, 0).text() == "Говядина"
    assert sec._table.item(0, 1).text() == "кг"  # mapped unit
    # Phase 8D — 7 колонок (Тип убран после разделения на Продукты/Хозтовары):
    # 0 Название, 1 Ед., 2 Остаток, 3 Себест., 4 Сорт., 5 Статус, 6 Действия
    assert sec._table.columnCount() == 7
    assert sec._table.item(0, 2).text() == "5 кг"  # Phase 8E: адаптивный формат, без trailing нулей
    # Pill-badge в колонке 5
    from pos.screens.settings_sections.inventory_widgets import StatusBadge

    def _badge_text(row: int) -> str:
        w = sec._table.cellWidget(row, 5)
        if w is None:
            return ""
        for child in w.findChildren(StatusBadge):
            return child.text()
        return ""

    assert _badge_text(1) == "Заканчивается"
    assert _badge_text(2) == "Отключён"


def test_inventory_section_empty(qtbot):
    from pos.screens.settings_sections.inventory_section import InventorySection

    sec = InventorySection(MagicMock())
    qtbot.addWidget(sec)
    sec._on_loaded([])
    assert sec._table.rowCount() == 0


def test_ingredient_edit_dialog_create(qtbot):
    from pos.screens.settings_sections.ingredient_edit_dialog import (
        IngredientEditDialog,
    )

    client = MagicMock()
    dlg = IngredientEditDialog(client, ingredient=None)
    qtbot.addWidget(dlg)
    dlg.name_edit.setText("Мука")
    # find "Килограмм" index
    for i in range(dlg.unit_combo.count()):
        if dlg.unit_combo.itemData(i) == "kg":
            dlg.unit_combo.setCurrentIndex(i)
            break
    dlg._save()
    # POST вызван
    args, kwargs = client.request.call_args
    assert args[0] == "POST"
    assert "/inventory/ingredients/" in args[1]
    assert kwargs["json"]["name"] == "Мука"
    assert kwargs["json"]["unit"] == "kg"


def test_ingredient_edit_dialog_validates_name(qtbot, monkeypatch):
    from pos.screens.settings_sections.ingredient_edit_dialog import (
        IngredientEditDialog,
    )

    warned = {}

    def fake_warning(*a, **kw):
        warned["called"] = True

    monkeypatch.setattr(
        "pos.screens.settings_sections.ingredient_edit_dialog.QMessageBox.warning",
        fake_warning,
    )
    client = MagicMock()
    dlg = IngredientEditDialog(client, ingredient=None)
    qtbot.addWidget(dlg)
    dlg.name_edit.setText("")
    dlg._save()
    assert warned.get("called") is True
    client.request.assert_not_called()


def test_purchase_dialog_payload(qtbot):
    from pos.screens.settings_sections.stock_action_dialogs import PurchaseDialog

    client = MagicMock()
    ing = {
        "id": 1, "name": "Мука", "unit": "kg",
        "current_qty": "5.000", "avg_cost_per_unit": "0",
    }
    dlg = PurchaseDialog(client, ingredient=ing)
    qtbot.addWidget(dlg)
    dlg.qty_spin.setValue(10.0)
    dlg.cost_spin.setValue(85.5)
    dlg.reason_edit.setText("Накладная #1")
    dlg._submit()
    args, kwargs = client.post.call_args
    assert "purchase" in args[0]
    # Phase 8E — payload now uses 2 dp
    assert kwargs["json"]["qty"] == "10.00"
    assert kwargs["json"]["unit_cost"] == "85.50"
    assert kwargs["json"]["reason"] == "Накладная #1"


def test_waste_dialog_requires_reason(qtbot, monkeypatch):
    from pos.screens.settings_sections.stock_action_dialogs import WasteDialog

    warned = {}

    def fake_warning(*a, **kw):
        warned["called"] = True

    monkeypatch.setattr(
        "pos.screens.settings_sections.stock_action_dialogs.QMessageBox.warning",
        fake_warning,
    )
    client = MagicMock()
    dlg = WasteDialog(client, ingredient={
        "id": 1, "name": "X", "unit": "kg", "current_qty": "10", "avg_cost_per_unit": "0",
    })
    qtbot.addWidget(dlg)
    dlg.qty_spin.setValue(2.0)
    # без reason — должна быть warning
    dlg._submit()
    assert warned.get("called") is True
    client.post.assert_not_called()


def test_inventory_correct_delta_preview(qtbot):
    from pos.screens.settings_sections.stock_action_dialogs import (
        InventoryCorrectDialog,
    )

    client = MagicMock()
    ing = {
        "id": 1, "name": "X", "unit": "kg",
        "current_qty": "10.000", "avg_cost_per_unit": "0",
    }
    dlg = InventoryCorrectDialog(client, ingredient=ing)
    qtbot.addWidget(dlg)
    # Initial: actual=10 → дельта 0
    assert "Изменений нет" in dlg._delta_lbl.text()
    # Изменим: actual=8 → дельта -2
    dlg.qty_spin.setValue(8.0)
    assert "-2" in dlg._delta_lbl.text() or "−2" in dlg._delta_lbl.text()
    # actual=12 → дельта +2
    dlg.qty_spin.setValue(12.0)
    assert "+2" in dlg._delta_lbl.text()
