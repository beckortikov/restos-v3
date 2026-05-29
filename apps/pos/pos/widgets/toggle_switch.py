"""iOS-style toggle switch (44×24) — для frame 21/22.

Сигнал toggled(bool). Состояние ON: green bg, белый кружок справа.
OFF: серый bg, кружок слева.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
    Property,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

from pos.resources.tokens import COLORS


class ToggleSwitch(QAbstractButton):
    toggled_changed = Signal(bool)

    WIDTH = 44
    HEIGHT = 24
    KNOB = 20

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(ToggleSwitch.WIDTH, ToggleSwitch.HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setChecked(checked)
        self._knob_x: float = self._target_knob_x()
        self._anim = QPropertyAnimation(self, b"knob_x", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self.toggled.connect(self._on_toggled)

    def _target_knob_x(self) -> float:
        # ON: справа (width - knob - 2px padding); OFF: слева (2px padding)
        return float(
            ToggleSwitch.WIDTH - ToggleSwitch.KNOB - 2
            if self.isChecked() else 2
        )

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_x)
        self._anim.setEndValue(self._target_knob_x())
        self._anim.start()
        self.toggled_changed.emit(checked)

    def get_knob_x(self) -> float:
        return self._knob_x

    def set_knob_x(self, v: float) -> None:
        self._knob_x = float(v)
        self.update()

    knob_x = Property(float, get_knob_x, set_knob_x)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # фон-track
        bg_color = QColor(
            COLORS["success_green"] if self.isChecked() else COLORS["border_light"]
        )
        p.setPen(Qt.NoPen)
        p.setBrush(bg_color)
        p.drawRoundedRect(
            QRectF(0, 0, self.width(), self.height()),
            self.height() / 2, self.height() / 2,
        )
        # кружок
        p.setBrush(QColor(COLORS["bg_white"]))
        p.drawEllipse(
            QRectF(self._knob_x, 2, ToggleSwitch.KNOB, ToggleSwitch.KNOB)
        )
        p.end()
