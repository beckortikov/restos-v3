"""Выбор/ввод комментария к позиции заказа.

Chips активных MenuItemNote + textarea для своего варианта. Источник
chips — GET /menu/notes/?is_active=true (или передаёт parent через cache).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class NotePickerDialog(QDialog):
    """Сигнал note_chosen(text). Вызвать .exec() и читать .chosen_note."""

    note_chosen = Signal(str)

    def __init__(
        self,
        client: ApiClient,
        item_name: str,
        current_note: str = "",
        notes: list[dict] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._item_name = item_name
        # Фильтруем неактивные шаблоны независимо от того, передал caller
        # список или мы тянем сами через API.
        raw = notes if notes is not None else self._fetch_notes()
        self._notes = [n for n in raw if n.get("is_active", True)]
        self.chosen_note: str = current_note

        self.setWindowTitle("Комментарий к блюду")
        self.setModal(True)
        self.setFixedWidth(480)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build(current_note)

    def _fetch_notes(self) -> list[dict]:
        try:
            data = self._client.get(
                "/menu/notes/", params={"is_active": "true"}
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            return [n for n in items if n.get("is_active", True)]
        except ApiError:
            return []

    def _build(self, current_note: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        title = QLabel(f"Комментарий: {self._item_name}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        title.setWordWrap(True)
        outer.addWidget(title)

        # Чипы шаблонов
        if self._notes:
            chips_lbl = QLabel("Быстрый выбор:")
            chips_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            )
            outer.addWidget(chips_lbl)

            chips_holder = QWidget()
            grid = QGridLayout(chips_holder)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(SPACING["sm"])
            cols = 2
            sorted_notes = sorted(
                self._notes,
                key=lambda n: (int(n.get("sort_order", 0)), n.get("label", "")),
            )
            for i, n in enumerate(sorted_notes):
                chip = QPushButton(n.get("label", ""))
                chip.setFixedHeight(36)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {COLORS['bg_light']};"
                    f"  color: {COLORS['text_primary']};"
                    f"  border: 1px solid {COLORS['border_light']};"
                    f"  border-radius: 18px;"
                    f"  padding: 0 14px;"
                    f"  font-size: 11pt; font-weight: 500;"
                    f"  text-align: center;"
                    f"}}"
                    f"QPushButton:hover {{"
                    f"  background: #FEF3E7;"
                    f"  border-color: {COLORS['accent_orange']};"
                    f"  color: {COLORS['accent_orange']};"
                    f"}}"
                )
                chip.clicked.connect(
                    lambda _c=False, label=n.get("label", ""):
                    self._note_edit.setText(label)
                )
                grid.addWidget(chip, i // cols, i % cols)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setMaximumHeight(220)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setWidget(chips_holder)
            outer.addWidget(scroll)

        # Textarea для своего варианта
        custom_lbl = QLabel("Свой комментарий:")
        custom_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" margin-top: 4px;"
        )
        outer.addWidget(custom_lbl)

        self._note_edit = QLineEdit(current_note)
        self._note_edit.setPlaceholderText(
            "Можно вписать вручную или выбрать чип сверху"
        )
        self._note_edit.setMaxLength(255)
        self._note_edit.setFixedHeight(40)
        self._note_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        outer.addWidget(self._note_edit)
        outer.addStretch(1)

        # Footer
        btns = QHBoxLayout()
        clear = QPushButton("Очистить")
        clear.setFixedHeight(40)
        clear.setMinimumWidth(120)
        clear.setCursor(Qt.PointingHandCursor)
        clear.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 500;"
            f"}}"
            f"QPushButton:hover {{ background: #FEE2E2; }}"
        )
        clear.clicked.connect(lambda: self._note_edit.setText(""))
        btns.addWidget(clear)
        btns.addStretch(1)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        save = QPushButton("Сохранить")
        save.setFixedHeight(40)
        save.setMinimumWidth(140)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        save.clicked.connect(self._save)
        btns.addWidget(save)
        outer.addLayout(btns)

    def _save(self) -> None:
        self.chosen_note = self._note_edit.text().strip()
        self.note_chosen.emit(self.chosen_note)
        self.accept()
