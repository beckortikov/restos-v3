"""Диалог при снятии блюда со стоп-листа: ввод причины + опц. дата возврата.

После accept у диалога доступны:
- `reason: str` — текст причины (может быть пустым)
- `until_iso: str | None` — дата в формате YYYY-MM-DD или None
"""
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING


class StopReasonDialog(QDialog):
    def __init__(self, item_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Снять с продажи")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS['bg_white']}; }}"
        )
        self._item_name = item_name
        self.reason: str = ""
        self.until_iso: str | None = None
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"],
        )
        v.setSpacing(SPACING["md"])

        title = QLabel(f"Снять «{self._item_name}» с продажи")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 14pt; font-weight: 700;"
        )
        title.setWordWrap(True)
        v.addWidget(title)

        # Причина
        reason_lbl = QLabel("Причина (опц.)")
        reason_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        v.addWidget(reason_lbl)
        self._reason_input = QTextEdit()
        self._reason_input.setPlaceholderText(
            "Например: «Закончилась говядина», «Сломался гриль»…"
        )
        self._reason_input.setFixedHeight(72)
        self._reason_input.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 6px 10px; font-size: 11pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
            f"QTextEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        v.addWidget(self._reason_input)

        # Дата возврата (опц.)
        self._until_chk = QCheckBox("Указать дату возврата")
        self._until_chk.setStyleSheet(
            f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
        )
        self._until_chk.toggled.connect(self._on_until_toggled)
        v.addWidget(self._until_chk)

        self._until_input = QDateEdit(QDate.currentDate().addDays(1))
        self._until_input.setCalendarPopup(True)
        self._until_input.setDisplayFormat("dd.MM.yyyy")
        self._until_input.setFixedHeight(36)
        self._until_input.setEnabled(False)
        self._until_input.setStyleSheet(
            f"QDateEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 12pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
            f"QDateEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
            f"QDateEdit:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        v.addWidget(self._until_input)

        # Footer
        footer = QHBoxLayout()
        footer.setSpacing(SPACING["md"])
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        footer.addStretch(1)

        save = QPushButton("Снять с продажи")
        save.setFixedHeight(40)
        save.setMinimumWidth(180)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 24px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #B91C1C; }}"
        )
        save.clicked.connect(self._on_save)
        footer.addWidget(save)
        v.addLayout(footer)

    def _on_until_toggled(self, checked: bool) -> None:
        self._until_input.setEnabled(checked)

    def _on_save(self) -> None:
        self.reason = self._reason_input.toPlainText().strip()
        if self._until_chk.isChecked():
            d = self._until_input.date().toPython()
            if isinstance(d, date):
                self.until_iso = d.isoformat()
        else:
            self.until_iso = None
        self.accept()
