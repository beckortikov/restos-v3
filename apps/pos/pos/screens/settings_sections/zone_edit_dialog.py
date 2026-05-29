"""Create/edit зоны."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class ZoneEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        zone: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._zone = zone or {}
        self.setWindowTitle("Зона")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        outer.setSpacing(SPACING["lg"])

        title = QLabel(
            "Редактировать зону" if self._zone else "Новая зона"
        )
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.name_edit = QLineEdit(self._zone.get("name", ""))
        self.name_edit.setPlaceholderText("Основной зал")
        self.name_edit.setStyleSheet(self._field_qss())
        self.name_edit.setFixedHeight(40)
        form.addRow(self._lbl("Название"), self.name_edit)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 999)
        self.sort_spin.setValue(int(self._zone.get("sort_order", 0)))
        self.sort_spin.setStyleSheet(self._field_qss())
        self.sort_spin.setFixedHeight(40)
        form.addRow(self._lbl("Порядок"), self.sort_spin)

        outer.addLayout(form)
        outer.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("Сохранить")
        save.setFixedHeight(40)
        save.setMinimumWidth(140)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(self._save_qss())
        save.clicked.connect(self._save)
        btns.addWidget(save)
        outer.addLayout(btns)

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QSpinBox:focus {{"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"}}"
        )

    def _cancel_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _save_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        body = {
            "name": name,
            "sort_order": int(self.sort_spin.value()),
        }
        try:
            if self._zone.get("id"):
                self._client.request(
                    "PATCH", f"/tables/zones/{self._zone['id']}/",
                    json=body, idempotent=True,
                )
            else:
                self._client.request(
                    "POST", "/tables/zones/", json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка сохранения",
                f"[{e.code}] {e.message}",
            )
            return
        self.accept()
