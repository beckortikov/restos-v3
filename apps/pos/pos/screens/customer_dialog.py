"""Единый диалог ввода данных клиента для takeaway / delivery.

Один экран с полями:
- Имя (required для UX, но backend не требует — оставляем soft)
- Телефон (опционально)
- Адрес (только для delivery; backend требует customer_address)
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING


class CustomerDialog(QDialog):
    """Возвращает кортеж (name, phone, address) или None если отмена.

    Используется одинаково для takeaway/delivery — поле address скрывается
    для takeaway."""

    def __init__(
        self,
        order_type: str,  # "takeaway" | "delivery"
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._order_type = order_type
        self.setWindowTitle("С собой" if order_type == "takeaway" else "Доставка")
        self.setModal(True)
        self.setFixedWidth(480)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)
        title_text = (
            "Новый заказ: С собой"
            if self._order_type == "takeaway"
            else "Новый заказ: Доставка"
        )
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        close = QPushButton()
        close.setFlat(True)
        close.setFixedSize(32, 32)
        close.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close.setIconSize(QSize(18, 18))
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; border-radius: 4px; }}"
        )
        close.clicked.connect(self.reject)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(close)
        outer.addWidget(header)

        # Body
        body = QWidget()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        v = QVBoxLayout(body)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        v.addLayout(self._field("Имя клиента", placeholder="Например: Иван"))
        self._name_input = self._last_input

        v.addLayout(self._field("Телефон", placeholder="+992 90 000 00 00"))
        self._phone_input = self._last_input

        if self._order_type == "delivery":
            v.addLayout(
                self._field("Адрес доставки *", placeholder="Улица, дом, квартира")
            )
            self._address_input = self._last_input
            note = QLabel("* Обязательно для доставки")
            note.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 9pt;"
            )
            v.addWidget(note)
        else:
            self._address_input = None

        outer.addWidget(body, 1)

        # Footer
        footer = QFrame()
        footer.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])
        fh.setSpacing(SPACING["md"])

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(44)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 600;"
            f"  padding: 0 24px;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("Дальше →")
        ok_btn.setFixedHeight(44)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"  padding: 0 32px;"
            f"}}"
            f"QPushButton:pressed {{ background-color: {COLORS['accent_orange_pressed']}; }}"
        )
        ok_btn.clicked.connect(self._on_accept)

        fh.addWidget(cancel_btn)
        fh.addStretch(1)
        fh.addWidget(ok_btn)
        outer.addWidget(footer)

    def _field(self, label: str, placeholder: str = "") -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(SPACING["sm"])
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10pt;")
        v.addWidget(lbl)

        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 10px 14px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {COLORS['primary_blue']}; }}"
        )
        v.addWidget(edit)
        self._last_input = edit
        return v

    def _on_accept(self) -> None:
        if self._order_type == "delivery" and not self._address_input.text().strip():
            self._address_input.setStyleSheet(
                self._address_input.styleSheet()
                + f"QLineEdit {{ border: 2px solid {COLORS['danger_red']}; }}"
            )
            self._address_input.setFocus()
            return
        self.accept()

    # public getters
    @property
    def name(self) -> str:
        return self._name_input.text().strip()

    @property
    def phone(self) -> str:
        return self._phone_input.text().strip()

    @property
    def address(self) -> str:
        return self._address_input.text().strip() if self._address_input else ""
