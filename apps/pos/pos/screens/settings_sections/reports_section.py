"""Раздел «Отчёты» в настройках.

Список действий-карточек для перехода к существующим отчётам:
- Отчёт по текущей смене → ShiftReportScreen
- История заказов → OrderHistoryScreen
- История смен (Phase 3+) — placeholder

Никаких новых данных не вводит — навигация. Сигналы вверх → main.py
открывает соответствующие экраны.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING


class ReportsSection(QWidget):
    """Сигналы:
        open_shift_report() — открыть отчёт по текущей смене
        open_history()       — открыть OrderHistoryScreen
    """

    open_shift_report = Signal()
    open_history = Signal()
    open_shift_history = Signal()
    open_reservations = Signal()
    open_abc_menu = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"ReportsSection {{ background: {COLORS['bg_light']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])
        v.setAlignment(Qt.AlignTop)

        title = QLabel("Отчёты")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(title)

        v.addWidget(self._action_card(
            icon="receipt",
            title="Отчёт по текущей смене",
            desc="Выручка, KPI, продажи по способам оплаты, по типу заказа, по категориям",
            handler=self.open_shift_report.emit,
        ))
        v.addWidget(self._action_card(
            icon="receipt",
            title="История заказов",
            desc="Закрытые сегодня и архив с поиском",
            handler=self.open_history.emit,
        ))

        v.addWidget(self._action_card(
            icon="receipt",
            title="Архив смен",
            desc="Все смены за период с переходом в детальный отчёт",
            handler=self.open_shift_history.emit,
        ))
        v.addWidget(self._action_card(
            icon="receipt",
            title="Резервации",
            desc="Бронирования столов: создание, подтверждение, посадка гостей",
            handler=self.open_reservations.emit,
        ))
        v.addWidget(self._action_card(
            icon="receipt",
            title="ABC-анализ меню",
            desc="Топ-блюда по выручке и маржинальности с классификацией A/B/C",
            handler=self.open_abc_menu.emit,
        ))

    # -------- helpers --------

    def _action_card(self, *, icon: str, title: str, desc: str, handler) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
            f"QFrame:hover {{ border: 1px solid {COLORS['accent_orange']}; }}"
        )
        h = QHBoxLayout(card)
        h.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        h.setSpacing(SPACING["md"])

        icon_lbl = QLabel()
        from pos.resources.icons import qpixmap
        icon_lbl.setPixmap(qpixmap(icon, COLORS["accent_orange"], 28))
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background: #FFF7ED; border: none; border-radius: {RADIUS['md']}px;"
        )
        h.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        d.setWordWrap(True)
        text_col.addWidget(t)
        text_col.addWidget(d)
        h.addLayout(text_col, 1)

        btn = QPushButton()
        btn.setIcon(qicon("arrow-right", COLORS["text_secondary"], 18))
        btn.setIconSize(QSize(18, 18))
        btn.setFixedSize(40, 40)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        btn.clicked.connect(handler)
        h.addWidget(btn)
        return card

    def _stub_card(self, title: str, desc: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        h = QHBoxLayout(card)
        h.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        h.setSpacing(SPACING["md"])

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 13pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-style: italic;"
            f" border: none; background: transparent;"
        )
        d.setWordWrap(True)
        text_col.addWidget(t)
        text_col.addWidget(d)
        h.addLayout(text_col, 1)
        return card

    def reload(self) -> None:
        """Не нужно — секция статичная."""
        pass
