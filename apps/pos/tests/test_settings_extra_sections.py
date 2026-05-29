"""Settings sections: Отчёты / Общие / О системе.

Это последние три секции, которые раньше были stub'ами.
"""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = {}
    return c


# -------- ReportsSection --------


def test_reports_section_emits_open_shift_report(qtbot):
    from pos.screens.settings_sections.reports_section import ReportsSection

    s = ReportsSection()
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.open_shift_report.connect(lambda: fired.append(True))

    btns = s.findChildren(QPushButton)
    # arrow-right в первой action-карточке
    assert btns
    qtbot.mouseClick(btns[0], Qt.LeftButton)
    assert fired == [True]


def test_reports_section_emits_open_history(qtbot):
    from pos.screens.settings_sections.reports_section import ReportsSection

    s = ReportsSection()
    qtbot.addWidget(s)
    fired: list[bool] = []
    s.open_history.connect(lambda: fired.append(True))

    btns = s.findChildren(QPushButton)
    qtbot.mouseClick(btns[1], Qt.LeftButton)
    assert fired == [True]


def test_reports_section_styled_background(qtbot):
    from pos.screens.settings_sections.reports_section import ReportsSection

    s = ReportsSection()
    qtbot.addWidget(s)
    assert s.testAttribute(Qt.WA_StyledBackground)


# -------- GeneralSection --------


@pytest.fixture
def general_section(qtbot, mock_client):
    from pos.screens.settings_sections.general_section import GeneralSection

    s = GeneralSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def test_general_section_loads_me_endpoint(qtbot, general_section, mock_client):
    """reload() вызывает GET /auth/me/."""
    mock_client.get.return_value = {
        "user": {"username": "anna", "full_name": "Анна",
                 "role": "cashier"},
        "restaurant": {"name": "Кафе у Анвара", "address": "ул. Рудаки 1",
                       "phone": "+992 900 11 22 33", "currency": "TJS",
                       "timezone": "Asia/Dushanbe", "pin_lock_timeout_min": 30},
    }
    general_section.reload()
    qtbot.waitUntil(
        lambda: general_section._data.get("user", {}).get("username") == "anna",
        timeout=2000,
    )
    args, _ = mock_client.get.call_args
    assert args[0] == "/auth/me/"


def test_general_section_renders_restaurant_data(qtbot, general_section, mock_client):
    from PySide6.QtWidgets import QLabel

    mock_client.get.return_value = {
        "user": {"username": "anna", "full_name": "Анна Кассир",
                 "role": "cashier"},
        "restaurant": {"name": "Кафе у Анвара", "address": "ул. Рудаки 1",
                       "phone": "+992 900", "currency": "TJS",
                       "timezone": "Asia/Dushanbe", "pin_lock_timeout_min": 30},
    }
    general_section.reload()
    qtbot.waitUntil(
        lambda: general_section._data.get("restaurant") is not None,
        timeout=2000,
    )
    labels = [l.text() for l in general_section.findChildren(QLabel)]
    assert any("Кафе у Анвара" in t for t in labels)
    assert any("Анна Кассир" in t for t in labels)
    assert any("Кассир" == t for t in labels)


def test_general_section_styled_background(qtbot, general_section):
    assert general_section.testAttribute(Qt.WA_StyledBackground)


# -------- AboutSection --------


def test_about_section_renders(qtbot):
    from PySide6.QtWidgets import QLabel
    from pos.screens.settings_sections.about_section import AboutSection, APP_VERSION

    s = AboutSection()
    qtbot.addWidget(s)
    labels = [l.text() for l in s.findChildren(QLabel)]
    assert any(APP_VERSION in t for t in labels)
    assert any("RestOS" in t for t in labels)


def test_about_section_styled_background(qtbot):
    from pos.screens.settings_sections.about_section import AboutSection

    s = AboutSection()
    qtbot.addWidget(s)
    assert s.testAttribute(Qt.WA_StyledBackground)


# -------- SettingsScreen wiring --------


def test_settings_screen_no_more_stubs(qtbot):
    """Все 8 секций — реальные виджеты, не stub'ы."""
    from pos.screens.settings_screen import SETTINGS_SECTIONS, SettingsScreen
    from pos.screens.settings_sections.about_section import AboutSection
    from pos.screens.settings_sections.discounts_section import DiscountsSection
    from pos.screens.settings_sections.general_section import GeneralSection
    from pos.screens.settings_sections.menu_section import MenuSection
    from pos.screens.settings_sections.payments_section import PaymentsSection
    from pos.screens.settings_sections.printers_section import PrintersSection
    from pos.screens.settings_sections.reports_section import ReportsSection
    from pos.screens.settings_sections.users_section import UsersSection

    state = MagicMock()
    state.client = MagicMock()
    state.client.get.return_value = []
    s = SettingsScreen(state)
    qtbot.addWidget(s)

    expected = {
        "printers": PrintersSection,
        "menu": MenuSection,
        "users": UsersSection,
        "payment": PaymentsSection,
        "discounts": DiscountsSection,
        "reports": ReportsSection,
        "general": GeneralSection,
        "about": AboutSection,
    }
    for key, cls in expected.items():
        widget = s._section_widgets.get(key)
        assert isinstance(widget, cls), (
            f"section '{key}' should be {cls.__name__}, got {type(widget).__name__}"
        )
    # И все 8 ключей покрыты
    assert set(s._section_widgets.keys()) == {k for k, _ in SETTINGS_SECTIONS}


def test_settings_screen_emits_open_shift_report_signal(qtbot):
    """Сигнал прокидывается из ReportsSection через SettingsScreen наверх."""
    from pos.screens.settings_screen import SettingsScreen

    state = MagicMock()
    state.client = MagicMock()
    state.client.get.return_value = []
    s = SettingsScreen(state)
    qtbot.addWidget(s)

    fired: list[bool] = []
    s.open_shift_report.connect(lambda: fired.append(True))

    reports = s._section_widgets["reports"]
    btns = reports.findChildren(QPushButton)
    qtbot.mouseClick(btns[0], Qt.LeftButton)
    assert fired == [True]
