"""Модалка create/edit для PaymentProvider — used from PaymentsSection (frame 21)."""
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

KIND_CHOICES = [
    ("cash", "Наличные"),
    ("card", "Банковская карта"),
    ("qr", "QR-оплата"),
    ("wallet", "Мобильный кошелёк"),
    ("transfer", "Перевод"),
]


class PaymentEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        provider: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._provider = provider or {}
        self.saved_data: dict | None = None

        self.setWindowTitle("Способ оплаты")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        title = QLabel("Редактировать способ" if self._provider else "Новый способ оплаты")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.kind_combo = QComboBox()
        for k, label in KIND_CHOICES:
            self.kind_combo.addItem(label, k)
        cur = self._provider.get("kind", "card")
        for i, (k, _) in enumerate(KIND_CHOICES):
            if k == cur:
                self.kind_combo.setCurrentIndex(i)
                break
        self.kind_combo.setStyleSheet(self._field_qss())
        self.kind_combo.setFixedHeight(40)
        form.addRow(self._lbl("Тип"), self.kind_combo)

        self.name_edit = QLineEdit(self._provider.get("name", ""))
        self.name_edit.setPlaceholderText("Alif Pay / Kortimilli / TojPay…")
        self.name_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Название"), self.name_edit)

        self.desc_edit = QLineEdit(self._provider.get("description", ""))
        self.desc_edit.setPlaceholderText("Краткое описание / реквизиты")
        self.desc_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Описание"), self.desc_edit)

        self.commission_spin = QDoubleSpinBox()
        self.commission_spin.setRange(0.0, 100.0)
        self.commission_spin.setDecimals(2)
        self.commission_spin.setSingleStep(0.1)
        try:
            self.commission_spin.setValue(
                float(self._provider.get("commission_pct") or 0)
            )
        except (TypeError, ValueError):
            self.commission_spin.setValue(0.0)
        self.commission_spin.setSuffix(" %")
        self.commission_spin.setStyleSheet(self._field_qss())
        self.commission_spin.setFixedHeight(40)
        form.addRow(self._lbl("Комиссия"), self.commission_spin)

        outer.addLayout(form)

        self.active_cb = QCheckBox("Активен")
        self.active_cb.setChecked(bool(self._provider.get("is_active", True)))
        self.active_cb.setStyleSheet(
            f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 12pt; }}"
        )
        outer.addWidget(self.active_cb)
        outer.addStretch(1)

        # Footer
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
            "kind": self.kind_combo.currentData(),
            "name": name,
            "description": self.desc_edit.text().strip(),
            "commission_pct": f"{self.commission_spin.value():.2f}",
            "is_active": self.active_cb.isChecked(),
        }
        try:
            if self._provider.get("id"):
                data = self._client.request(
                    "PATCH",
                    f"/payment_providers/{self._provider['id']}/",
                    json=body,
                    idempotent=True,
                )
            else:
                data = self._client.request(
                    "POST", "/payment_providers/", json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e.message}")
            return
        self.saved_data = data if isinstance(data, dict) else body
        self.accept()
