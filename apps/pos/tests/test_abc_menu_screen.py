"""Smoke-тесты экрана ABC-анализа."""
from unittest.mock import MagicMock


def test_abc_screen_renders_rows(qtbot):
    from pos.screens.abc_menu_screen import AbcMenuScreen

    state = MagicMock()
    state.client = MagicMock()
    screen = AbcMenuScreen(state)
    qtbot.addWidget(screen)

    # Подсунем готовый payload в обработчик
    screen._on_loaded({
        "period": {"from": "2026-04-10", "to": "2026-05-10"},
        "totals": {
            "revenue": "500.00", "cogs": "180.00", "margin": "320.00",
            "margin_pct": "64.00", "items_count": 2,
        },
        "rows": [
            {
                "menu_item_id": 1, "name": "Плов",
                "category_name": "Горячее", "sold_qty": 10,
                "revenue": "450.00", "cogs_total": "150.00",
                "margin": "300.00", "margin_pct": "66.67",
                "revenue_share_pct": "90.00",
                "cumulative_share_pct": "90.00", "abc_class": "A",
            },
            {
                "menu_item_id": 2, "name": "Чай",
                "category_name": "Напитки", "sold_qty": 5,
                "revenue": "50.00", "cogs_total": "30.00",
                "margin": "20.00", "margin_pct": "40.00",
                "revenue_share_pct": "10.00",
                "cumulative_share_pct": "100.00", "abc_class": "B",
            },
        ],
    })
    assert screen._table.rowCount() == 2
    # Класс A в первой строке
    assert screen._table.item(0, 0).text() == "A"
    # Имя блюда
    assert screen._table.item(0, 1).text() == "Плов"
    # Totals
    assert "500.00" in screen._totals_lbl.text()
    assert "Маржа: 320.00" in screen._totals_lbl.text()


def test_abc_screen_inverted_dates_show_warning(qtbot, monkeypatch):
    from PySide6.QtCore import QDate

    from pos.screens.abc_menu_screen import AbcMenuScreen

    state = MagicMock()
    state.client = MagicMock()
    screen = AbcMenuScreen(state)
    qtbot.addWidget(screen)

    warned = {}

    def fake_warning(*args, **kwargs):
        warned["called"] = True

    monkeypatch.setattr(
        "pos.screens.abc_menu_screen.QMessageBox.warning", fake_warning,
    )
    # from > to
    screen._from_edit.setDate(QDate(2026, 6, 1))
    screen._to_edit.setDate(QDate(2026, 5, 1))
    screen.reload()
    assert warned.get("called") is True
    # GET не дёрнули
    state.client.get.assert_not_called()
