"""ModifierPickerDialog + интеграция CartPanel с modifier_ids."""
from decimal import Decimal


def _steak_with_groups() -> dict:
    return {
        "id": 100, "name": "Стейк", "price": "100.00",
        "modifier_groups": [
            {
                "id": 1, "name": "Прожарка",
                "min_select": 1, "max_select": 1, "is_required": True,
                "modifiers": [
                    {"id": 11, "name": "Medium", "price_delta": "0",
                     "is_active": True},
                    {"id": 12, "name": "Well-done", "price_delta": "0",
                     "is_active": True},
                ],
            },
            {
                "id": 2, "name": "Соусы",
                "min_select": 0, "max_select": 2, "is_required": False,
                "modifiers": [
                    {"id": 21, "name": "Чесночный", "price_delta": "3",
                     "is_active": True},
                    {"id": 22, "name": "Острый", "price_delta": "2",
                     "is_active": True},
                    {"id": 23, "name": "Без соли", "price_delta": "-1",
                     "is_active": True},
                ],
            },
        ],
    }


# -------- ModifierPickerDialog --------


def test_picker_required_blocks_ok_until_chosen(qtbot):
    from pos.screens.modifier_picker_dialog import ModifierPickerDialog

    dlg = ModifierPickerDialog(_steak_with_groups())
    qtbot.addWidget(dlg)
    # Required не выбран → кнопка ОК disabled
    assert not dlg._ok_btn.isEnabled()

    # Выбрать Medium из «Прожарка»
    medium = next(
        b for b in dlg._buttons_by_group[1] if "Medium" in b.text()
    )
    medium.setChecked(True)
    assert dlg._ok_btn.isEnabled()


def test_picker_max_select_for_optional_group(qtbot):
    from pos.screens.modifier_picker_dialog import ModifierPickerDialog

    dlg = ModifierPickerDialog(_steak_with_groups())
    qtbot.addWidget(dlg)

    medium = next(b for b in dlg._buttons_by_group[1] if "Medium" in b.text())
    medium.setChecked(True)
    sauces = dlg._buttons_by_group[2]
    sauces[0].setChecked(True)
    sauces[1].setChecked(True)
    assert dlg._ok_btn.isEnabled()
    sauces[2].setChecked(True)  # 3 > max_select=2 → блокируем
    assert not dlg._ok_btn.isEnabled()


def test_picker_returns_chosen_ids_and_snapshot(qtbot):
    from pos.screens.modifier_picker_dialog import ModifierPickerDialog

    dlg = ModifierPickerDialog(_steak_with_groups())
    qtbot.addWidget(dlg)
    # Medium + Чесночный
    next(b for b in dlg._buttons_by_group[1] if "Medium" in b.text()).setChecked(True)
    next(b for b in dlg._buttons_by_group[2] if "Чесночный" in b.text()).setChecked(True)

    ids = dlg.chosen_modifier_ids
    assert sorted(ids) == [11, 21]
    snap = dlg.chosen_modifiers_snapshot
    by_id = {s["id"]: s for s in snap}
    assert by_id[21]["name"] == "Чесночный"
    assert by_id[21]["price_delta"] == "3"


def test_picker_total_includes_deltas(qtbot):
    from pos.screens.modifier_picker_dialog import ModifierPickerDialog

    dlg = ModifierPickerDialog(_steak_with_groups())
    qtbot.addWidget(dlg)
    next(b for b in dlg._buttons_by_group[1] if "Medium" in b.text()).setChecked(True)
    next(b for b in dlg._buttons_by_group[2] if "Чесночный" in b.text()).setChecked(True)
    next(b for b in dlg._buttons_by_group[2] if "Острый" in b.text()).setChecked(True)
    # 100 + 3 + 2 = 105.00
    assert "105.00" in dlg._total_lbl.text()


# -------- CartPanel + modifier_ids --------


def test_cart_separates_items_by_modifier_set(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = _steak_with_groups()
    cart.add_item(
        item,
        modifier_ids=[11, 21],
        modifiers=[
            {"id": 11, "name": "Medium", "price_delta": "0"},
            {"id": 21, "name": "Чесночный", "price_delta": "3"},
        ],
    )
    cart.add_item(
        item,
        modifier_ids=[12],
        modifiers=[{"id": 12, "name": "Well-done", "price_delta": "0"}],
    )
    cart.add_item(  # дубль первого набора → qty=2
        item,
        modifier_ids=[21, 11],
        modifiers=[
            {"id": 11, "name": "Medium", "price_delta": "0"},
            {"id": 21, "name": "Чесночный", "price_delta": "3"},
        ],
    )
    items = cart.get_items()
    assert len(items) == 2
    qty_by_mods = {tuple(sorted(it.get("modifier_ids", []))): it["qty"] for it in items}
    assert qty_by_mods[(11, 21)] == 2
    assert qty_by_mods[(12,)] == 1


def test_cart_total_uses_modifier_deltas(qtbot):
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    item = _steak_with_groups()
    cart.add_item(
        item,
        modifier_ids=[21],
        modifiers=[{"id": 21, "name": "Чесночный", "price_delta": "3"}],
    )
    cart.add_item(
        item,
        modifier_ids=[21],
        modifiers=[{"id": 21, "name": "Чесночный", "price_delta": "3"}],
    )
    # (100 + 3) * 2 = 206
    assert "206.00" in cart._total_lbl.text()


def test_cart_get_items_omits_empty_modifier_ids(qtbot):
    """Backward-compat: для блюд без модификаторов в выходе нет ключа."""
    from pos.widgets.cart_panel import CartPanel

    cart = CartPanel()
    qtbot.addWidget(cart)
    cart.add_item({"id": 5, "name": "Чай", "price": "8"})
    items = cart.get_items()
    assert items == [{"menu_item_id": 5, "qty": 1, "note": ""}]
