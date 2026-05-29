"""Переиспользуемые виджеты для секции «Склад» (Phase 8D redesign).

KpiCard / KpiStrip — компактные счётчики «Всего / Заканчивается / Закончилось».
StatusBadge — pill-стиль с цветом для статуса остатка.
SearchBar — поиск + chip-фильтры.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING


# Цветовые пресеты для статусов остатка
STATUS_PRESETS = {
    "ok":       ("В наличии",    COLORS["success_green"], "#DCFCE7"),
    "low":      ("Заканчивается", COLORS["warning_yellow"], "#FEF3C7"),
    "out":      ("Нет на складе", COLORS["danger_red"],    "#FEE2E2"),
    "off":      ("Отключён",     COLORS["text_secondary"], COLORS["bg_gray"]),
    "stopped":  ("Авто-стоп",    COLORS["danger_red"],    "#FEE2E2"),
    "oversell": ("В минус ок",   "#7C3AED",               "#EDE9FE"),
    "manual":   ("Ручной стоп",  COLORS["text_secondary"], COLORS["bg_gray"]),
}


class StatusBadge(QLabel):
    """Pill-метка статуса. Использование: StatusBadge('ok') или StatusBadge.custom('текст', fg, bg)."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        text, fg, bg = STATUS_PRESETS.get(key, ("?", COLORS["text_primary"], COLORS["bg_gray"]))
        super().__init__(text, parent)
        self._apply(fg, bg)

    @classmethod
    def custom(cls, text: str, fg: str, bg: str, parent: QWidget | None = None) -> "StatusBadge":
        w = cls.__new__(cls)
        QLabel.__init__(w, text, parent)
        w._apply(fg, bg)
        return w

    def _apply(self, fg: str, bg: str) -> None:
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{"
            f"  background: {bg};"
            f"  color: {fg};"
            f"  border-radius: 10px;"
            f"  padding: 3px 10px;"
            f"  font-size: 9pt; font-weight: 700;"
            f"  border: none;"
            f"  min-width: 80px;"
            f"  max-height: 22px;"
            f"}}"
        )


class KpiCard(QFrame):
    """Один счётчик: значение + подпись с боковой цветной полосой (4px) по макету."""

    def __init__(
        self,
        label: str,
        value: str | int,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Phase 8D — боковой акцент 4px и рамка 1px (frame `Cgpwn` в pos_cashier.pen)
        self.setStyleSheet(
            f"KpiCard {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-left: 4px solid {color};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        self.setFixedHeight(96)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 12)
        v.setSpacing(4)
        self._value_lbl = QLabel(str(value))
        self._value_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 800;"
            f" background: transparent; border: none;"
        )
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        v.addWidget(self._value_lbl)
        v.addWidget(lbl)

    def set_value(self, value: str | int) -> None:
        self._value_lbl.setText(str(value))


class KpiStrip(QWidget):
    """Горизонтальная полоса с KPI-карточками. update_kpis({key: value})."""

    def __init__(self, specs: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        """specs: [(key, label, color), ...]"""
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"KpiStrip {{ background: transparent; }}")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])
        self._cards: dict[str, KpiCard] = {}
        for key, label, color in specs:
            card = KpiCard(label, 0, color)
            self._cards[key] = card
            h.addWidget(card)

    def update_kpis(self, values: dict[str, int | str]) -> None:
        for k, v in values.items():
            if k in self._cards:
                self._cards[k].set_value(v)


class SearchBar(QWidget):
    """Поле поиска + опц. кнопка справа (например, «Сбросить фильтр»)."""

    text_changed = Signal(str)

    def __init__(self, placeholder: str = "Поиск…", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setFixedHeight(38)
        self._input.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px 0 34px; color: {COLORS['text_primary']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {COLORS['accent_orange']}; }}"
        )
        from pos.resources.icons import qicon
        self._input.addAction(qicon("search", COLORS["text_secondary"], 16), QLineEdit.LeadingPosition)
        self._input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._input.textChanged.connect(lambda t: self.text_changed.emit(t))
        h.addWidget(self._input, 1)

        self._chips_holder = QHBoxLayout()
        self._chips_holder.setSpacing(6)
        h.addLayout(self._chips_holder)

    @property
    def text(self) -> str:
        return self._input.text()

    def add_chip(self, label: str, on_click) -> QPushButton:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(38)
        b.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_secondary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 10pt; font-weight: 600;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border-color: {COLORS['accent_orange']};"
            f"}}"
            f"QPushButton:hover:!checked {{ background: {COLORS['bg_gray']}; }}"
        )
        b.clicked.connect(lambda _checked, btn=b: on_click(btn))
        self._chips_holder.addWidget(b)
        return b
