"""Диалоги операций склада: Приёмка / Списание / Инвентаризация.

Все 3 — на одной базе `_StockActionDialog` (общий layout: header + 1-2
числовых поля + reason + footer).
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
# Phase 8E — дискретные единицы (целые числа без дробной части)
DISCRETE_UNITS = {"piece", "pack", "bottle"}


def _configure_qty_spin(spin, unit: str) -> None:
    """Настроить spin под единицу: для шт/уп/бут — целые, для веса/объёма — 2dp."""
    if unit in DISCRETE_UNITS:
        spin.setDecimals(0)
        spin.setSingleStep(1)
        if spin.minimum() < 1:
            spin.setMinimum(1)
    else:
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        if spin.minimum() < 0.01:
            spin.setMinimum(0.01)


class _StockActionDialog(QDialog):
    """База — общий layout."""

    TITLE: str = ""
    SUBMIT_LABEL: str = "Применить"
    ACTION_PATH: str = ""  # purchase / waste / inventory_correct
    ACCENT: str = "accent_orange"

    def __init__(
        self,
        client: ApiClient,
        ingredient: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._ing = ingredient
        self.setWindowTitle(self.TITLE)
        self.setModal(True)
        self.setFixedWidth(460)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        outer.setSpacing(SPACING["lg"])

        title = QLabel(self.TITLE)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        # Контекст ингредиента
        unit_lbl = UNIT_LABEL.get(self._ing.get("unit", ""), self._ing.get("unit", ""))
        ctx = QLabel(
            f"<b>{self._ing.get('name', '?')}</b><br/>"
            f"<span style='color:#64748B; font-size:10pt'>"
            f"Текущий остаток: {self._ing.get('current_qty', '0')} {unit_lbl} · "
            f"Себест.: {self._ing.get('avg_cost_per_unit', '0')}</span>"
        )
        ctx.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
            f" padding: 12px;"
        )
        outer.addWidget(ctx)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])
        self._populate_form(form, unit_lbl)
        outer.addLayout(form)

        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText(self._reason_placeholder())
        self.reason_edit.setStyleSheet(self._field_qss())
        self.reason_edit.setFixedHeight(40)
        form.addRow(self._lbl("Причина"), self.reason_edit)

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

        submit = QPushButton(self.SUBMIT_LABEL)
        submit.setFixedHeight(40)
        submit.setMinimumWidth(140)
        submit.setCursor(Qt.PointingHandCursor)
        submit.setStyleSheet(self._submit_qss())
        submit.clicked.connect(self._submit)
        btns.addWidget(submit)
        outer.addLayout(btns)

    # Override-able
    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        raise NotImplementedError

    def _reason_placeholder(self) -> str:
        return "Краткое описание (накладная, причина и т.д.)"

    def _payload(self) -> dict:
        raise NotImplementedError

    # --------

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
            return  # валидация показала ошибку
        try:
            self._client.post(
                f"/inventory/ingredients/{self._ing['id']}/{self.ACTION_PATH}/",
                json=payload, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"[{e.code}] {e.message}",
            )
            return
        self.accept()


class PurchaseDialog(_StockActionDialog):
    TITLE = "Приёмка (накладная)"
    SUBMIT_LABEL = "Принять"
    ACTION_PATH = "purchase"
    ACCENT = "accent_orange"

    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setSuffix(f" {unit_label}")
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        _configure_qty_spin(self.qty_spin, (self._ing or {}).get("unit", ""))
        form.addRow(self._lbl("Количество"), self.qty_spin)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 1_000_000)
        self.cost_spin.setDecimals(2)  # цена — всегда деньги, 2dp
        self.cost_spin.setSuffix(" / ед.")
        self.cost_spin.setStyleSheet(self._field_qss())
        self.cost_spin.setFixedHeight(40)
        form.addRow(self._lbl("Цена закупки"), self.cost_spin)

    def _reason_placeholder(self) -> str:
        return "Накладная № 4521"

    def _payload(self) -> dict | None:
        qty = self.qty_spin.value()
        if qty <= 0:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть > 0")
            return None
        body: dict = {"qty": f"{qty:.2f}"}
        cost = self.cost_spin.value()
        if cost > 0:
            body["unit_cost"] = f"{cost:.2f}"
        reason = self.reason_edit.text().strip()
        if reason:
            body["reason"] = reason
        return body


class WasteDialog(_StockActionDialog):
    TITLE = "Списание"
    SUBMIT_LABEL = "Списать"
    ACTION_PATH = "waste"
    ACCENT = "danger_red"

    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setSuffix(f" {unit_label}")
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        _configure_qty_spin(self.qty_spin, (self._ing or {}).get("unit", ""))
        form.addRow(self._lbl("Количество"), self.qty_spin)

    def _reason_placeholder(self) -> str:
        return "Истёк срок, порча, бой"

    def _payload(self) -> dict | None:
        qty = self.qty_spin.value()
        if qty <= 0:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть > 0")
            return None
        reason = self.reason_edit.text().strip()
        if not reason:
            QMessageBox.warning(self, "Ошибка", "Укажите причину списания")
            return None
        return {"qty": f"{qty:.2f}", "reason": reason}


class InventoryCorrectDialog(_StockActionDialog):
    TITLE = "Инвентаризация"
    SUBMIT_LABEL = "Применить"
    ACTION_PATH = "inventory_correct"
    ACCENT = "primary_blue"

    def _populate_form(self, form: QFormLayout, unit_label: str) -> None:
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setSuffix(f" {unit_label}")
        _configure_qty_spin(self.qty_spin, (self._ing or {}).get("unit", ""))
        # Минимум для инвентаризации = 0 (можно зафиксировать что закончилось)
        self.qty_spin.setMinimum(0)
        try:
            cur = float(self._ing.get("current_qty") or 0)
        except (TypeError, ValueError):
            cur = 0
        self.qty_spin.setValue(cur)
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        form.addRow(self._lbl("Фактический остаток"), self.qty_spin)

        # delta preview
        self._delta_lbl = QLabel("")
        self._delta_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; font-style: italic;"
        )
        form.addRow("", self._delta_lbl)
        self.qty_spin.valueChanged.connect(self._update_delta)
        self._update_delta()

    def _update_delta(self) -> None:
        try:
            cur = Decimal(str(self._ing.get("current_qty") or 0))
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

    def _reason_placeholder(self) -> str:
        return "Подсчёт за смену"

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
