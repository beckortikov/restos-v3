"""Simple semi-finished dialogs — списание + инвентаризация.

Похожи на ingredient.stock_action_dialogs, но работают с
`/inventory/semi/{id}/waste/` и `/inventory_correct/`.
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

UNIT_LABEL = {
    "kg": "кг", "g": "г", "l": "л", "ml": "мл",
    "piece": "шт", "pack": "уп", "bottle": "бут",
}


class _SemiActionDialog(QDialog):
    TITLE = ""
    SUBMIT_LABEL = "Применить"
    ACTION_PATH = ""
    ACCENT = "accent_orange"

    def __init__(
        self,
        client: ApiClient,
        semi: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._semi = semi
        self.setWindowTitle(self.TITLE)
        self.setModal(True)
        self.setFixedWidth(460)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        title = QLabel(self.TITLE)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        v.addWidget(title)

        unit_lbl = UNIT_LABEL.get(
            self._semi.get("output_unit", ""), self._semi.get("output_unit", ""),
        )
        ctx = QLabel(
            f"<b>{self._semi.get('name', '?')}</b><br/>"
            f"<span style='color:#64748B; font-size:10pt'>"
            f"Остаток: {self._semi.get('current_qty', '0')} {unit_lbl}</span>"
        )
        ctx.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
            f" padding: 12px;"
        )
        v.addWidget(ctx)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])
        self._populate_form(form, unit_lbl)

        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Краткое описание")
        self.reason_edit.setStyleSheet(self._field_qss())
        self.reason_edit.setFixedHeight(40)
        form.addRow(self._lbl("Причина"), self.reason_edit)

        v.addLayout(form)
        v.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        submit = QPushButton(self.SUBMIT_LABEL)
        submit.setFixedHeight(40)
        submit.setMinimumWidth(140)
        submit.setCursor(Qt.PointingHandCursor)
        submit.setStyleSheet(self._submit_qss())
        submit.clicked.connect(self._submit)
        btns.addWidget(submit)
        v.addLayout(btns)

    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        raise NotImplementedError

    def _payload(self) -> dict | None:
        raise NotImplementedError

    def _lbl(self, t: str) -> QLabel:
        l = QLabel(t)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QDoubleSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
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

    def _submit_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS[self.ACCENT]};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
        )

    def _submit(self) -> None:
        payload = self._payload()
        if payload is None:
            return
        try:
            self._client.post(
                f"/inventory/semi/{self._semi['id']}/{self.ACTION_PATH}/",
                json=payload, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self.accept()


class SemiWasteDialog(_SemiActionDialog):
    TITLE = "Списание полуфабриката"
    SUBMIT_LABEL = "Списать"
    ACTION_PATH = "waste"
    ACCENT = "danger_red"

    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setDecimals(2)
        self.qty_spin.setSuffix(f" {unit_label}")
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        form.addRow(self._lbl("Количество"), self.qty_spin)

    def _payload(self) -> dict | None:
        qty = self.qty_spin.value()
        if qty <= 0:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть > 0")
            return None
        reason = self.reason_edit.text().strip()
        if not reason:
            QMessageBox.warning(self, "Ошибка", "Укажите причину")
            return None
        return {"qty": f"{qty:.2f}", "reason": reason}


class SemiInventoryCorrectDialog(_SemiActionDialog):
    TITLE = "Инвентаризация полуфабриката"
    SUBMIT_LABEL = "Применить"
    ACTION_PATH = "inventory_correct"
    ACCENT = "primary_blue"

    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setDecimals(2)
        self.qty_spin.setSuffix(f" {unit_label}")
        try:
            cur = float(self._semi.get("current_qty") or 0)
        except (TypeError, ValueError):
            cur = 0
        self.qty_spin.setValue(cur)
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        form.addRow(self._lbl("Фактический остаток"), self.qty_spin)

        self._delta_lbl = QLabel("")
        self._delta_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; font-style: italic;"
        )
        form.addRow("", self._delta_lbl)
        self.qty_spin.valueChanged.connect(self._update_delta)
        self._update_delta()

    def _update_delta(self) -> None:
        try:
            cur = Decimal(str(self._semi.get("current_qty") or 0))
        except Exception:
            cur = Decimal("0")
        actual = Decimal(str(self.qty_spin.value()))
        delta = actual - cur
        if delta == 0:
            self._delta_lbl.setText("Изменений нет")
            return
        sign = "+" if delta > 0 else ""
        color = COLORS["success_green"] if delta > 0 else COLORS["danger_red"]
        self._delta_lbl.setText(
            f"<span style='color:{color}'>Корректировка: {sign}{delta}</span>"
        )

    def _payload(self) -> dict | None:
        actual = self.qty_spin.value()
        if actual < 0:
            QMessageBox.warning(self, "Ошибка", "Остаток не может быть < 0")
            return None
        body: dict = {"actual_qty": f"{actual:.2f}"}
        reason = self.reason_edit.text().strip()
        if reason:
            body["reason"] = reason
        return body
