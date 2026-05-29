"""Модалка создания/редактирования принтера — used from PrintersSection (frame 18).

Поля:
- Название (name)
- Тип (kind: usb / tcp / serial / virtual)
- Адрес (address) — IP:port для tcp, /dev/ttyUSB0 для serial, путь для virtual
- По умолчанию (is_default)
- Активен (is_active)
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
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

KIND_CHOICES: list[tuple[str, str]] = [
    ("usb", "USB"),
    ("tcp", "TCP/IP"),
    ("serial", "Serial"),
    ("virtual", "Виртуальный (файл)"),
]
PAPER_CHOICES: list[tuple[str, str]] = [
    ("58mm", "58 мм"),
    ("76mm", "76 мм"),
    ("80mm", "80 мм"),
]


class PrinterEditDialog(QDialog):
    """Создание (printer=None) или редактирование принтера."""

    def __init__(
        self,
        client: ApiClient,
        printer: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._printer = printer or {}
        self.saved_data: dict | None = None

        self.setWindowTitle("Принтер")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        title = QLabel("Редактировать принтер" if self._printer else "Добавить принтер")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])
        form.setLabelAlignment(Qt.AlignLeft)

        self.name_edit = QLineEdit(self._printer.get("name", ""))
        self.name_edit.setPlaceholderText("Касса / Кухня / Бар")
        self.name_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Название"), self.name_edit)

        self.kind_combo = QComboBox()
        for key, label in KIND_CHOICES:
            self.kind_combo.addItem(label, key)
        cur_kind = self._printer.get("kind", "virtual")
        for i, (k, _) in enumerate(KIND_CHOICES):
            if k == cur_kind:
                self.kind_combo.setCurrentIndex(i)
                break
        self.kind_combo.setStyleSheet(self._field_qss())
        self.kind_combo.setFixedHeight(40)
        form.addRow(self._lbl("Тип"), self.kind_combo)

        self.addr_edit = QLineEdit(self._printer.get("address", ""))
        self.addr_edit.setPlaceholderText("192.168.1.100:9100  /  /dev/usb/lp0  /  printouts")
        self.addr_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Адрес"), self.addr_edit)

        # Размер бумаги (ширина рулона) — 58/76/80мм
        self.paper_combo = QComboBox()
        for key, label in PAPER_CHOICES:
            self.paper_combo.addItem(label, key)
        cur_paper = self._printer.get("paper_size", "80mm")
        for i, (k, _) in enumerate(PAPER_CHOICES):
            if k == cur_paper:
                self.paper_combo.setCurrentIndex(i)
                break
        self.paper_combo.setStyleSheet(self._field_qss())
        self.paper_combo.setFixedHeight(40)
        form.addRow(self._lbl("Размер бумаги"), self.paper_combo)

        outer.addLayout(form)

        self.default_cb = QCheckBox("Принтер по умолчанию")
        self.default_cb.setChecked(bool(self._printer.get("is_default", False)))
        self.default_cb.setStyleSheet(
            f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 12pt; }}"
        )
        outer.addWidget(self.default_cb)

        self.active_cb = QCheckBox("Активен (использовать для печати)")
        self.active_cb.setChecked(bool(self._printer.get("is_active", True)))
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
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 600;"
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

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QComboBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"  min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus {{"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"}}"
        )

    # -------- save --------

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        body = {
            "name": name,
            "kind": self.kind_combo.currentData(),
            "address": self.addr_edit.text().strip(),
            "paper_size": self.paper_combo.currentData(),
            "is_default": self.default_cb.isChecked(),
            "is_active": self.active_cb.isChecked(),
        }
        try:
            if self._printer.get("id"):
                data = self._client.request(
                    "PATCH",
                    f"/printing/printers/{self._printer['id']}/",
                    json=body,
                    idempotent=True,
                )
            else:
                data = self._client.request(
                    "POST", "/printing/printers/", json=body, idempotent=True
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e.message}")
            return
        self.saved_data = data if isinstance(data, dict) else body
        self.accept()
