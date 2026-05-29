"""Защитный тест: все QWidget-экраны, использующие class-name селектор для
background, должны иметь Qt.WA_StyledBackground=True. Без этого атрибута
QSS не красит фон и сквозь дыры между карточками пробивается системный
чёрный (особенно в macOS dark mode)."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def state():
    s = MagicMock()
    s.client = MagicMock()
    s.client.get.return_value = []
    s.tables = []
    s.orders = []
    s.current_shift = None
    return s


def _check_attr(widget) -> None:
    assert widget.testAttribute(Qt.WA_StyledBackground), (
        f"{type(widget).__name__} should have WA_StyledBackground=True "
        f"to render its bg via class-name QSS selector."
    )


def test_sidebar(qtbot):
    """Sidebar — тёмный bg_dark через class-селектор, тоже требует
    WA_StyledBackground, иначе на macOS dark/light фон не красится."""
    from pos.widgets.sidebar import Sidebar

    s = Sidebar(active="tables")
    qtbot.addWidget(s)
    _check_attr(s)


def test_pin_login_screen(qtbot):
    from pos.auth.pin_login_screen import PinLoginScreen

    s = PinLoginScreen()
    qtbot.addWidget(s)
    _check_attr(s)


def test_open_shift_screen(qtbot):
    from pos.screens.open_shift_screen import OpenShiftScreen

    s = OpenShiftScreen(client=MagicMock())
    qtbot.addWidget(s)
    _check_attr(s)


def test_tables_screen(qtbot, state):
    from pos.screens.tables_screen import TablesScreen

    s = TablesScreen(state)
    qtbot.addWidget(s)
    _check_attr(s)


def test_active_orders_screen(qtbot, state):
    from pos.screens.active_orders_screen import ActiveOrdersScreen

    s = ActiveOrdersScreen(state)
    qtbot.addWidget(s)
    _check_attr(s)


def test_menu_screen(qtbot, state):
    from pos.screens.menu_screen import MenuScreen

    s = MenuScreen(state)
    qtbot.addWidget(s)
    _check_attr(s)


def test_order_history_screen(qtbot, state):
    from pos.screens.order_history_screen import OrderHistoryScreen

    s = OrderHistoryScreen(state)
    qtbot.addWidget(s)
    _check_attr(s)


def test_shift_report_screen(qtbot, state):
    from pos.screens.shift_report_screen import ShiftReportScreen

    s = ShiftReportScreen(state)
    qtbot.addWidget(s)
    _check_attr(s)


def test_settings_screen(qtbot, state):
    from pos.screens.settings_screen import SettingsScreen

    s = SettingsScreen(state)
    qtbot.addWidget(s)
    _check_attr(s)


def test_printers_section(qtbot):
    from pos.screens.settings_sections.printers_section import PrintersSection

    s = PrintersSection(client=MagicMock())
    qtbot.addWidget(s)
    _check_attr(s)


def test_menu_section(qtbot):
    from pos.screens.settings_sections.menu_section import MenuSection

    s = MenuSection(client=MagicMock())
    qtbot.addWidget(s)
    _check_attr(s)


def test_users_section(qtbot):
    from pos.screens.settings_sections.users_section import UsersSection

    s = UsersSection(client=MagicMock())
    qtbot.addWidget(s)
    _check_attr(s)
