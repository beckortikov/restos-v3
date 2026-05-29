"""MenuScreen: поиск блюда по названию (плоский результат по всем категориям)."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = []
    return c


@pytest.fixture
def state(mock_client):
    s = MagicMock()
    s.client = mock_client
    s.tables = []
    s.orders = []
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.menu_screen import MenuScreen

    s = MenuScreen(state)
    qtbot.addWidget(s)
    s.show()
    yield s


def _seed(screen):
    screen._categories = [
        {"id": 1, "name": "Супы"},
        {"id": 2, "name": "Горячее"},
    ]
    screen._items_by_cat = {
        1: [
            {"id": 10, "category": 1, "name": "Шурбо", "price": "20.00",
             "is_available": True},
            {"id": 11, "category": 1, "name": "Лагман", "price": "25.00",
             "is_available": True},
        ],
        2: [
            {"id": 20, "category": 2, "name": "Плов", "price": "45.00",
             "is_available": True},
            {"id": 21, "category": 2, "name": "Шашлык", "price": "60.00",
             "is_available": True},
        ],
    }
    screen._render_categories()


def test_search_input_present(screen):
    assert hasattr(screen, "_search_input")
    assert screen._search_input.isEnabled()


def test_search_filters_dishes_by_name(qtbot, screen):
    """После рефакторинга topbar'а MenuPanel заголовок «Поиск: …» удалён.
    Проверяем что поиск сработал: state обновился и в grid'е есть только
    подходящие карточки + back-чип «← Все категории»."""
    from pos.widgets.dish_card import DishCard

    _seed(screen)
    screen._search_input.setText("плов")
    assert screen._search_query == "плов"
    cards = screen._work_holder.findChildren(DishCard)
    ids = {c._item_id for c in cards}
    assert 20 in ids  # Плов
    assert 11 not in ids  # Лагман не должен подойти


def test_search_shows_empty_state_when_no_matches(qtbot, screen):
    _seed(screen)
    screen._search_input.setText("суши")
    # Должна появиться метка «Ничего не найдено»
    assert hasattr(screen, "_empty_search_lbl")
    assert "не найдено" in screen._empty_search_lbl.text().lower()


def test_search_clearing_returns_to_categories(qtbot, screen):
    """Очистка поиска возвращает grid к категориям (CategoryCard)."""
    from pos.widgets.category_card import CategoryCard

    _seed(screen)
    screen._search_input.setText("плов")
    assert screen._search_query == "плов"
    screen._search_input.clear()
    assert screen._search_query == ""
    qtbot.wait(20)  # дать Qt обработать deleteLater
    # В grid'е снова категории.
    assert screen._work_holder.findChildren(CategoryCard)


def test_search_is_case_insensitive(qtbot, screen):
    _seed(screen)
    screen._search_input.setText("ПЛОВ")
    # Поиск сравнивается lower() — должна остаться карточка «Плов».
    from pos.widgets.dish_card import DishCard
    cards = screen._work_holder.findChildren(DishCard)
    ids = {c._item_id for c in cards}
    assert 20 in ids  # «Плов»
    assert 11 not in ids  # «Лагман» — не должен быть


def test_back_button_clears_search_first(qtbot, screen):
    _seed(screen)
    screen._search_input.setText("плов")
    assert screen._search_query == "плов"
    screen._on_back()
    assert screen._search_query == ""
    # Search input очищен
    assert screen._search_input.text() == ""
