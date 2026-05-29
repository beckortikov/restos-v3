import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def numpad(qtbot):
    from pos.widgets.numpad import Numpad

    w = Numpad()
    qtbot.addWidget(w)
    return w


def _btn(numpad, label: str):
    from PySide6.QtWidgets import QPushButton

    for b in numpad.findChildren(QPushButton):
        if b.text() == label:
            return b
    raise AssertionError(f"button {label!r} not found")


def test_digit_buttons_emit_digit_pressed(qtbot, numpad):
    seen: list[str] = []
    numpad.digit_pressed.connect(lambda d: seen.append(d))

    for d in "01234567890":
        qtbot.mouseClick(_btn(numpad, d), Qt.LeftButton)

    assert seen == list("01234567890")


def test_backspace_emits(qtbot, numpad):
    fired: list[bool] = []
    numpad.backspace_pressed.connect(lambda: fired.append(True))
    qtbot.mouseClick(_btn(numpad, "⌫"), Qt.LeftButton)
    assert fired == [True]


def test_submit_emits(qtbot, numpad):
    fired: list[bool] = []
    numpad.submit_pressed.connect(lambda: fired.append(True))
    qtbot.mouseClick(_btn(numpad, "OK"), Qt.LeftButton)
    assert fired == [True]


def test_set_submit_enabled(numpad):
    numpad.set_submit_enabled(False)
    assert not numpad.submit_btn.isEnabled()
    numpad.set_submit_enabled(True)
    assert numpad.submit_btn.isEnabled()


def test_buttons_are_80x80(numpad):
    from PySide6.QtWidgets import QPushButton

    for b in numpad.findChildren(QPushButton):
        assert b.width() == 80 and b.height() == 80
