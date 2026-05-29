"""UsersSection — frame 20 (Настройки / Пользователи)."""
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
    from pos.screens.settings_sections.users_section import UsersSection

    s = UsersSection(client=mock_client)
    qtbot.addWidget(s)
    s.show()
    yield s


def test_empty_state(qtbot, section, mock_client):
    mock_client.get.return_value = []
    section.reload()
    qtbot.waitUntil(lambda: section._empty_label.isVisible(), timeout=2000)
    assert section._items == []


def test_render_users(qtbot, section, mock_client):
    mock_client.get.return_value = [
        {"id": 1, "username": "anna", "full_name": "Анна Кассир",
         "role": "cashier", "is_active": True, "has_pin": True},
        {"id": 2, "username": "karim", "full_name": "Карим Официант",
         "role": "waiter", "is_active": False, "has_pin": False},
    ]
    section.reload()
    qtbot.waitUntil(lambda: section._list_layout.count() == 2, timeout=2000)
    assert not section._empty_label.isVisible()


def test_set_pin_with_valid_input(qtbot, section, mock_client):
    mock_client.get.return_value = [
        {"id": 7, "username": "anna", "full_name": "Анна",
         "role": "cashier", "is_active": True, "has_pin": True},
    ]
    mock_client.post.return_value = {"id": 7, "has_pin": True}
    section.reload()
    qtbot.waitUntil(lambda: section._list_layout.count() == 1, timeout=2000)

    btns = section.findChildren(QPushButton)
    pin_btn = next(b for b in btns if b.text() == "Сменить PIN")

    with patch(
        "pos.screens.settings_sections.users_section.QInputDialog.getText",
        return_value=("4321", True),
    ), patch(
        "pos.screens.settings_sections.users_section.QMessageBox.information"
    ):
        qtbot.mouseClick(pin_btn, Qt.LeftButton)
        qtbot.waitUntil(lambda: mock_client.post.called, timeout=2000)

    args, kwargs = mock_client.post.call_args
    assert args[0] == "/users/7/set_pin/"
    assert kwargs["json"] == {"pin": "4321"}


def test_set_pin_rejects_invalid(qtbot, section, mock_client):
    mock_client.get.return_value = [
        {"id": 7, "username": "anna", "full_name": "Анна",
         "role": "cashier", "is_active": True, "has_pin": True},
    ]
    section.reload()
    qtbot.waitUntil(lambda: section._list_layout.count() == 1, timeout=2000)

    btns = section.findChildren(QPushButton)
    pin_btn = next(b for b in btns if b.text() == "Сменить PIN")

    with patch(
        "pos.screens.settings_sections.users_section.QInputDialog.getText",
        return_value=("12", True),
    ), patch(
        "pos.screens.settings_sections.users_section.QMessageBox.warning"
    ) as warn:
        qtbot.mouseClick(pin_btn, Qt.LeftButton)
        assert warn.called
    # POST не вызван — PIN отклонён клиентом
    assert not mock_client.post.called


def test_set_pin_cancelled(qtbot, section, mock_client):
    mock_client.get.return_value = [
        {"id": 7, "username": "anna", "full_name": "Анна",
         "role": "cashier", "is_active": True, "has_pin": True},
    ]
    section.reload()
    qtbot.waitUntil(lambda: section._list_layout.count() == 1, timeout=2000)
    btns = section.findChildren(QPushButton)
    pin_btn = next(b for b in btns if b.text() == "Сменить PIN")

    with patch(
        "pos.screens.settings_sections.users_section.QInputDialog.getText",
        return_value=("", False),
    ):
        qtbot.mouseClick(pin_btn, Qt.LeftButton)
    assert not mock_client.post.called
