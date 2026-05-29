"""AuditSection — раздел «Журнал действий» в настройках."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.get.return_value = {
        "data": [], "meta": {"total": 0, "page": 1, "page_size": 50, "pages": 1},
    }
    return c


@pytest.fixture
def section(qtbot, mock_client):
    from pos.screens.settings_sections.audit_section import AuditSection

    s = AuditSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def test_audit_section_styled_background(section):
    assert section.testAttribute(Qt.WA_StyledBackground)


def test_audit_section_load_renders_rows(qtbot, section, mock_client):
    mock_client.get.return_value = {
        "data": [
            {"id": 1, "user_full_name": "Анна",
             "action": "login", "action_label": "Вход",
             "target_type": "PinSession", "target_id": 1, "payload": {},
             "created_at": "2026-05-08T10:00:00"},
            {"id": 2, "user_full_name": "Анна",
             "action": "order_create", "action_label": "Создание заказа",
             "target_type": "Order", "target_id": 42,
             "payload": {"items_count": 3, "total": "120.00"},
             "created_at": "2026-05-08T10:05:00"},
        ],
        "meta": {"total": 2, "page": 1, "page_size": 50, "pages": 1},
    }
    section.reload()
    qtbot.waitUntil(lambda: len(section._entries) == 2, timeout=2000)
    # Header row + 2 data rows = 3 widgets
    assert section._rows_layout.count() == 2
    assert "2 из 2" in section._count_lbl.text()


def test_audit_section_filter_change_calls_api_with_action(
    qtbot, section, mock_client
):
    section.reload()
    qtbot.waitUntil(lambda: mock_client.get.called, timeout=2000)
    mock_client.reset_mock()
    mock_client.get.return_value = {
        "data": [], "meta": {"total": 0, "page": 1, "page_size": 50, "pages": 1},
    }

    # Найти индекс «Создание заказа»
    for i in range(section.action_combo.count()):
        if section.action_combo.itemData(i) == "order_create":
            section.action_combo.setCurrentIndex(i)
            break

    qtbot.waitUntil(lambda: mock_client.get.called, timeout=2000)
    args, kwargs = mock_client.get.call_args
    assert args[0] == "/audit/"
    assert kwargs["params"]["action"] == "order_create"


def test_audit_section_load_more_pagination(qtbot, section, mock_client):
    """Load-more увеличивает page и аппендит в существующие entries."""
    # Первая страница: 50 из 75
    mock_client.get.return_value = {
        "data": [
            {"id": i, "user_full_name": "X",
             "action": "login", "action_label": "Вход",
             "target_type": "", "target_id": None, "payload": {},
             "created_at": "2026-05-08T10:00:00"}
            for i in range(1, 51)
        ],
        "meta": {"total": 75, "page": 1, "page_size": 50, "pages": 2},
    }
    section.reload()
    qtbot.waitUntil(lambda: len(section._entries) == 50, timeout=2000)
    assert section._more_btn.isEnabled()

    # Вторая страница: 25 + предыдущие 50 = 75
    mock_client.get.return_value = {
        "data": [
            {"id": i, "user_full_name": "X",
             "action": "login", "action_label": "Вход",
             "target_type": "", "target_id": None, "payload": {},
             "created_at": "2026-05-08T10:00:00"}
            for i in range(51, 76)
        ],
        "meta": {"total": 75, "page": 2, "page_size": 50, "pages": 2},
    }
    qtbot.mouseClick(section._more_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: len(section._entries) == 75, timeout=2000)
    assert not section._more_btn.isEnabled()  # больше нет страниц


def test_audit_section_empty_state(qtbot, section, mock_client):
    mock_client.get.return_value = {
        "data": [], "meta": {"total": 0, "page": 1, "page_size": 50, "pages": 1},
    }
    section.reload()
    # Wait for render: count_lbl shows the formatted text after _render
    qtbot.waitUntil(
        lambda: "0 из 0" in section._count_lbl.text(), timeout=2000
    )
    # 1 виджет — placeholder «Записей нет»
    assert section._rows_layout.count() == 1


def test_settings_screen_has_audit_section(qtbot):
    from pos.screens.settings_screen import SETTINGS_SECTIONS, SettingsScreen
    from pos.screens.settings_sections.audit_section import AuditSection

    state = MagicMock()
    state.client = MagicMock()
    state.client.get.return_value = []
    s = SettingsScreen(state)
    qtbot.addWidget(s)
    assert "audit" in {k for k, _ in SETTINGS_SECTIONS}
    assert isinstance(s._section_widgets.get("audit"), AuditSection)
