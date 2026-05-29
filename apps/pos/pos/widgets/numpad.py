from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from pos.resources.tokens import COLORS, RADIUS

BUTTON_QSS = f"""
QPushButton {{
    background-color: {COLORS["bg_gray"]};
    color: {COLORS["text_primary"]};
    border: none;
    border-radius: {RADIUS["sm"]}px;
    font-size: 24pt;
    font-weight: 700;
}}
QPushButton:pressed {{
    background-color: {COLORS["border_light"]};
}}
QPushButton#submit {{
    background-color: {COLORS["success_green"]};
    color: {COLORS["text_white"]};
    font-size: 20pt;
}}
QPushButton#submit:pressed {{
    background-color: #15803D;
}}
QPushButton#submit:disabled {{
    background-color: {COLORS["border_light"]};
    color: {COLORS["text_secondary"]};
}}
QPushButton#backspace {{
    color: {COLORS["text_secondary"]};
}}
"""


class Numpad(QWidget):
    """4×3 цифровая клавиатура: 1-9, ←(backspace), 0, ✓(submit). Кнопки 80×80."""

    digit_pressed = Signal(str)
    backspace_pressed = Signal()
    submit_pressed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        self.setStyleSheet(BUTTON_QSS)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        layout = [
            [("1", "digit"), ("2", "digit"), ("3", "digit")],
            [("4", "digit"), ("5", "digit"), ("6", "digit")],
            [("7", "digit"), ("8", "digit"), ("9", "digit")],
            [("⌫", "back"), ("0", "digit"), ("OK", "submit")],
        ]
        for r, row in enumerate(layout):
            for c, (label, kind) in enumerate(row):
                btn = QPushButton(label)
                btn.setFixedSize(80, 80)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFocusPolicy(Qt.NoFocus)
                if kind == "digit":
                    btn.clicked.connect(
                        lambda _checked=False, d=label: self.digit_pressed.emit(d)
                    )
                elif kind == "back":
                    btn.setObjectName("backspace")
                    btn.clicked.connect(lambda: self.backspace_pressed.emit())
                elif kind == "submit":
                    btn.setObjectName("submit")
                    self.submit_btn = btn
                    btn.clicked.connect(lambda: self.submit_pressed.emit())
                grid.addWidget(btn, r, c)

    def set_submit_enabled(self, enabled: bool) -> None:
        if hasattr(self, "submit_btn"):
            self.submit_btn.setEnabled(enabled)
