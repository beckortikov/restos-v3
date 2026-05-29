"""SettingsScreen + PrintersSection — frame 18."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = []
    return c


@pytest.fixture
def state(mock_client):
    s = MagicMock()
    s.client = mock_client
    return s


@pytest.fixture
def screen(qtbot, state):
    from pos.screens.settings_screen import SettingsScreen

    s = SettingsScreen(state)
    qtbot.addWidget(s)
    yield s


def test_default_section_is_printers(screen):
    assert screen._active_section == "printers"
    assert screen._nav_buttons["printers"].isChecked()


def test_set_section_switches(screen):
    screen.set_section("users")
    assert screen._active_section == "users"
    assert screen._nav_buttons["users"].isChecked()
    assert not screen._nav_buttons["printers"].isChecked()


def test_unknown_section_ignored(screen):
    screen.set_section("does-not-exist")
    assert screen._active_section == "printers"


def test_logout_signal_via_sidebar(qtbot, screen):
    seen: list[bool] = []
    screen.logout_requested.connect(lambda: seen.append(True))
    qtbot.mouseClick(screen.sidebar._buttons["logout"], Qt.LeftButton)
    assert seen == [True]


def test_nav_to_tables_signal(qtbot, screen):
    seen: list[str] = []
    screen.nav_requested.connect(lambda n: seen.append(n))
    qtbot.mouseClick(screen.sidebar._buttons["tables"], Qt.LeftButton)
    assert seen == ["tables"]


# -------- PrintersSection --------


@pytest.fixture
def printers_section(qtbot, mock_client):
    from pos.screens.settings_sections.printers_section import PrintersSection

    section = PrintersSection(client=mock_client)
    qtbot.addWidget(section)
    section.show()
    yield section


def _wait_until_no_threads(qtbot, section):
    """Ждём пока все QThread удалятся (deleteLater отрабатывает после finished)."""
    qtbot.waitUntil(lambda: section._render_calls > 0, timeout=2000)


def test_printers_empty_state(qtbot, printers_section, mock_client):
    mock_client.get.return_value = []
    printers_section._render_calls = 0
    orig = printers_section._render
    printers_section._render = lambda: (setattr(printers_section, "_render_calls", printers_section._render_calls + 1), orig())[-1]
    printers_section.reload()
    _wait_until_no_threads(qtbot, printers_section)
    assert printers_section._items == []
    assert printers_section._empty_label.isVisible()


def test_printers_render_cards(qtbot, printers_section, mock_client):
    mock_client.get.return_value = [
        {"id": 1, "name": "Касса", "kind": "virtual",
         "address": "printouts", "is_default": True, "is_active": True},
        {"id": 2, "name": "Кухня", "kind": "tcp",
         "address": "192.168.1.50:9100", "is_default": False, "is_active": False},
    ]
    printers_section.reload()
    qtbot.waitUntil(
        lambda: printers_section._list_layout.count() == 2, timeout=2000
    )
    assert not printers_section._empty_label.isVisible()


def test_test_print_action(qtbot, printers_section, mock_client):
    mock_client.get.return_value = [
        {"id": 7, "name": "Касса", "kind": "virtual",
         "address": "printouts", "is_default": True, "is_active": True},
    ]
    mock_client.post.return_value = {"print_job": {"id": 1, "status": "pending"}}
    printers_section.reload()
    qtbot.waitUntil(
        lambda: printers_section._list_layout.count() == 1, timeout=2000
    )

    btns = printers_section.findChildren(QPushButton)
    test_btn = next(b for b in btns if b.text() == "Тест печати")

    from unittest.mock import patch
    with patch("pos.screens.settings_sections.printers_section.QMessageBox.information"):
        qtbot.mouseClick(test_btn, Qt.LeftButton)
        qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)
    args, _ = mock_client.post.call_args
    assert args[0] == "/printing/printers/7/test_print/"
