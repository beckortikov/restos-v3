"""Варка партии полуфабриката — Phase 7D-2."""
from __future__ import annotations

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


class SemiProduceDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        semi: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._semi = semi
        self.setWindowTitle("Варка партии")
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

        title = QLabel(f"Варка партии · {self._semi.get('name', '?')}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        v.addWidget(title)

        unit_lbl = UNIT_LABEL.get(
            self._semi.get("output_unit", ""), self._semi.get("output_unit", ""),
        )
        ctx = QLabel(
            f"Выход: <b>{unit_lbl}</b> · Yield: "
            f"<b>{self._semi.get('yield_percent', '100')}%</b><br/>"
            f"<span style='color:#64748B; font-size:10pt'>"
            f"Текущий остаток: {self._semi.get('current_qty', '0')} {unit_lbl} · "
            f"Себест.: {self._semi.get('avg_cost_per_unit', '0')}</span>"
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

        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setDecimals(2)
        self.qty_spin.setSuffix(f" {unit_lbl}")
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        form.addRow(self._lbl("Сколько произвести"), self.qty_spin)

        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Утренняя варка / закладка на смену")
        self.reason_edit.setStyleSheet(self._field_qss())
        self.reason_edit.setFixedHeight(40)
        form.addRow(self._lbl("Комментарий"), self.reason_edit)

        v.addLayout(form)

        info = QLabel(
            "<small style='color:#64748B'>"
            "Из склада автоматически спишутся ингредиенты согласно рецепту "
            "(с учётом yield). При недостатке — операция отменится."
            "</small>"
        )
        info.setWordWrap(True)
        v.addWidget(info)
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
        submit = QPushButton("Произвести")
        submit.setFixedHeight(40)
        submit.setMinimumWidth(140)
        submit.setCursor(Qt.PointingHandCursor)
        submit.setStyleSheet(self._submit_qss())
        submit.clicked.connect(self._submit)
        btns.addWidget(submit)
        v.addLayout(btns)

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
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
        )

    def _submit(self) -> None:
        qty = self.qty_spin.value()
        if qty <= 0:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть > 0")
            return
        body = {"qty": f"{qty:.2f}"}
        reason = self.reason_edit.text().strip()
        if reason:
            body["reason"] = reason
        try:
            self._client.post(
                f"/inventory/semi/{self._semi['id']}/produce/",
                json=body, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка варки",
                f"[{e.code}] {e.message}",
            )
            return
        self.accept()
