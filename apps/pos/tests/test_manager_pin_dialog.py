"""ManagerPinDialog: numpad PIN input."""
import pytest


@pytest.fixture
def dlg(qtbot):
    from pos.screens.manager_pin_dialog import ManagerPinDialog

    d = ManagerPinDialog(message="Тест")
    qtbot.addWidget(d)
    yield d


def test_pin_starts_empty(dlg):
    assert dlg.pin == ""


def test_typing_digits_updates_pin(dlg):
    dlg._on_key("1")
    dlg._on_key("2")
    dlg._on_key("3")
    dlg._on_key("4")
    assert dlg.pin == "1234"
    # Display показывает кружочки
    assert dlg._pin_display.text() == "●●●●"


def test_backspace_removes_last_digit(dlg):
    dlg._on_key("1")
    dlg._on_key("2")
    dlg._on_key("←")
    assert dlg.pin == "1"


def test_pin_max_6_digits(dlg):
    for c in "1234567890":
        dlg._on_key(c)
    assert len(dlg.pin) == 6


def test_submit_disabled_until_4_digits(dlg):
    assert not dlg._submit_btn.isEnabled()
    dlg._on_key("1")
    dlg._on_key("2")
    dlg._on_key("3")
    assert not dlg._submit_btn.isEnabled()
    dlg._on_key("4")
    assert dlg._submit_btn.isEnabled()


def test_submit_accepts_dialog(qtbot, dlg):
    dlg._on_key("1")
    dlg._on_key("2")
    dlg._on_key("3")
    dlg._on_key("4")
    dlg._on_key("✓")
    # Dialog accepted
    assert dlg.result() == dlg.DialogCode.Accepted


def test_pin_message_shown(qtbot):
    from pos.screens.manager_pin_dialog import ManagerPinDialog
    from PySide6.QtWidgets import QLabel

    d = ManagerPinDialog(message="Кастомное сообщение")
    qtbot.addWidget(d)
    labels = d.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("Кастомное сообщение" in t for t in texts)
