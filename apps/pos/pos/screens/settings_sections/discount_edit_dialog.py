"""Модалка create/edit для Discount — used from DiscountsSection (frame 22)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING

TYPE_CHOICES = [("discount", "Скидка"), ("service", "Сервисный сбор")]
KIND_CHOICES = [("percent", "Процент (%)"), ("fixed", "Фиксированная сумма")]


class DiscountEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        discount: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._d = discount or {}
        self.saved_data: dict | None = None

        self.setWindowTitle("Скидка")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        title = QLabel("Редактировать" if self._d else "Новая скидка")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.type_combo = QComboBox()
        for k, label in TYPE_CHOICES:
            self.type_combo.addItem(label, k)
        cur_type = self._d.get("type", "discount")
        for i, (k, _) in enumerate(TYPE_CHOICES):
            if k == cur_type:
                self.type_combo.setCurrentIndex(i)
                break
        self.type_combo.setStyleSheet(self._field_qss())
        self.type_combo.setFixedHeight(40)
        form.addRow(self._lbl("Тип"), self.type_combo)

        self.name_edit = QLineEdit(self._d.get("name", ""))
        self.name_edit.setPlaceholderText("Например: Скидка постоянного клиента")
        self.name_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Название"), self.name_edit)

        self.desc_edit = QLineEdit(self._d.get("description", ""))
        self.desc_edit.setPlaceholderText("Когда применяется")
        self.desc_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Описание"), self.desc_edit)

        self.kind_combo = QComboBox()
        for k, label in KIND_CHOICES:
            self.kind_combo.addItem(label, k)
        cur_kind = self._d.get("kind", "percent")
        for i, (k, _) in enumerate(KIND_CHOICES):
            if k == cur_kind:
                self.kind_combo.setCurrentIndex(i)
                break
        self.kind_combo.setStyleSheet(self._field_qss())
        self.kind_combo.setFixedHeight(40)
        form.addRow(self._lbl("Вид"), self.kind_combo)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.0, 1_000_000.0)
        self.value_spin.setDecimals(2)
        self.value_spin.setSingleStep(1.0)
        try:
            self.value_spin.setValue(float(self._d.get("value") or 0))
        except (TypeError, ValueError):
            self.value_spin.setValue(0.0)
        self.value_spin.setStyleSheet(self._field_qss())
        self.value_spin.setFixedHeight(40)
        form.addRow(self._lbl("Значение"), self.value_spin)

        outer.addLayout(form)

        self.active_cb = QCheckBox("Активна")
        self.active_cb.setChecked(bool(self._d.get("is_active", True)))
        self.active_cb.setStyleSheet(
            f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 12pt; }}"
        )
        outer.addWidget(self.active_cb)
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
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QComboBox, QDoubleSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{"
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
            "type": self.type_combo.currentData(),
            "name": name,
            "description": self.desc_edit.text().strip(),
            "kind": self.kind_combo.currentData(),
            "value": f"{self.value_spin.value():.2f}",
            "is_active": self.active_cb.isChecked(),
        }
        try:
            if self._d.get("id"):
                data = self._client.request(
                    "PATCH", f"/discounts/{self._d['id']}/",
                    json=body, idempotent=True,
                )
            else:
                data = self._client.request(
                    "POST", "/discounts/", json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e.message}")
            return
        self.saved_data = data if isinstance(data, dict) else body
        self.accept()
