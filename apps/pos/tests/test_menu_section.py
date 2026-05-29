"""MenuSection — frame 19 (Настройки / Меню и категории)."""
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
def section(qtbot, mock_client):
    from pos.screens.settings_sections.menu_section import MenuSection

    s = MenuSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def _wait_render(qtbot, section, *, items_min: int = 0, cats_min: int = 0):
    qtbot.waitUntil(
        lambda: len(section._items) >= items_min and len(section._categories) >= cats_min,
        timeout=2000,
    )


def test_empty_lists(qtbot, section, mock_client):
    mock_client.get.return_value = []
    section.reload()
    qtbot.waitUntil(lambda: section._categories == [], timeout=2000)
    assert section._items == []


def test_categories_and_items_render(qtbot, section, mock_client):
    cats = [
        {"id": 1, "name": "Салаты", "sort_order": 1},
        {"id": 2, "name": "Супы", "sort_order": 2},
    ]
    items = [
        {"id": 10, "category": 1, "name": "Цезарь", "price": "30.00",
         "emoji": "🥗", "sort_order": 0, "is_available": True},
        {"id": 11, "category": 2, "name": "Борщ", "price": "20.00",
         "emoji": "🍲", "sort_order": 0, "is_available": True},
    ]

    def get_side(path, **kw):
        if "categories" in path:
            return cats
        return items

    mock_client.get.side_effect = get_side
    section.reload()
    _wait_render(qtbot, section, items_min=2, cats_min=2)

    assert section._active_cat_id == 1
    # В items_layout должна быть одна карточка (Цезарь — кат 1)
    assert section._items_layout.count() == 1


def test_select_category_filters_items(qtbot, section, mock_client):
    cats = [
        {"id": 1, "name": "A", "sort_order": 1},
        {"id": 2, "name": "B", "sort_order": 2},
    ]
    items = [
        {"id": 10, "category": 1, "name": "X", "price": "1.00",
         "emoji": "", "sort_order": 0, "is_available": True},
        {"id": 11, "category": 2, "name": "Y", "price": "2.00",
         "emoji": "", "sort_order": 0, "is_available": True},
        {"id": 12, "category": 2, "name": "Z", "price": "3.00",
         "emoji": "", "sort_order": 1, "is_available": False},
    ]

    def get_side(path, **kw):
        return cats if "categories" in path else items

    mock_client.get.side_effect = get_side
    section.reload()
    _wait_render(qtbot, section, items_min=3, cats_min=2)

    section._select_category(2)
    assert section._items_layout.count() == 2


def test_toggle_item_calls_endpoint(qtbot, section, mock_client):
    cats = [{"id": 1, "name": "A", "sort_order": 0}]
    items = [
        {"id": 7, "category": 1, "name": "X", "price": "5.00",
         "emoji": "", "sort_order": 0, "is_available": True},
    ]

    def get_side(path, **kw):
        return cats if "categories" in path else items

    mock_client.get.side_effect = get_side
    mock_client.post.return_value = {"id": 7, "is_available": False}
    section.reload()
    _wait_render(qtbot, section, items_min=1, cats_min=1)

    btns = section.findChildren(QPushButton)
    toggle = next(b for b in btns if b.text() in {"В меню", "В стопе"})
    qtbot.mouseClick(toggle, Qt.LeftButton)
    qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, _ = mock_client.post.call_args
    assert args[0] == "/menu/items/7/toggle_available/"


def test_add_item_blocked_without_categories(section, mock_client):
    section._categories = []
    with patch(
        "pos.screens.settings_sections.menu_section.QMessageBox.information"
    ) as info:
        section._on_add_item()
        assert info.called
