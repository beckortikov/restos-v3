"""Диалог «Касса» — внесение / изъятие наличных в текущей открытой смене.

Бизнес-сценарий:
- cash_in: «положил 1000 размена», «вернул долг наличкой».
- cash_out: «шеф взял 5000 на закупку», «курьеру 200 за воду».

После успеха — сигнал `op_created(dict)` с {kind, amount, reason, ...} от backend'а.
Диалог сам тянет POST /shifts/{shift_id}/cash_op/.
"""
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class CashOpDialog(QDialog):
    """Сигналы:
        op_created(dict) — операция успешно создана на backend'е.
    """

    op_created = Signal(dict)

    def __init__(
        self,
        client: ApiClient,
        shift_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._shift_id = int(shift_id)
        self.setWindowTitle("Операция по кассе")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS['bg_white']}; }}"
        )
        self._build()

    # -------- build --------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"]
        )
        v.setSpacing(SPACING["md"])

        title = QLabel("Касса")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        v.addWidget(title)

        # Радио тип операции: Внесение / Изъятие
        radios = QHBoxLayout()
        radios.setSpacing(SPACING["md"])
        self._rb_in = QRadioButton("Внесение")
        self._rb_out = QRadioButton("Изъятие")
        self._rb_out.setChecked(True)  # чаще берут — default
        for rb in (self._rb_in, self._rb_out):
            rb.setStyleSheet(
                f"QRadioButton {{ font-size: 12pt; color: {COLORS['text_primary']}; }}"
            )
            radios.addWidget(rb)
        group = QButtonGroup(self)
        group.addButton(self._rb_in)
        group.addButton(self._rb_out)
        radios.addStretch(1)
        v.addLayout(radios)

        # Сумма
        amount_lbl = QLabel("Сумма (TJS)")
        amount_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        v.addWidget(amount_lbl)
        self._amount_input = QLineEdit()
        self._amount_input.setPlaceholderText("0.00")
        self._amount_input.setFixedHeight(48)
        self._amount_input.setStyleSheet(
            f"QLineEdit {{"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px;"
            f"  font-size: 16pt; font-weight: 700;"
            f"  color: {COLORS['text_primary']};"
            f"  background: {COLORS['bg_white']};"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        # Pseudo-numeric: разрешаем 0-9 и точку. Полная валидация — при submit.
        self._amount_input.textChanged.connect(self._on_amount_changed)
        v.addWidget(self._amount_input)

        # Причина
        reason_lbl = QLabel("Причина")
        reason_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        v.addWidget(reason_lbl)
        self._reason_input = QTextEdit()
        self._reason_input.setPlaceholderText(
            "Например: «Закупка овощей у поставщика», «Размен утром»…"
        )
        self._reason_input.setFixedHeight(80)
        self._reason_input.setStyleSheet(
            f"QTextEdit {{"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 10px;"
            f"  font-size: 12pt;"
            f"  color: {COLORS['text_primary']};"
            f"  background: {COLORS['bg_white']};"
            f"}}"
            f"QTextEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        v.addWidget(self._reason_input)

        # Footer — Отмена / Сохранить
        footer = QHBoxLayout()
        footer.setSpacing(SPACING["md"])
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(48)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)
        footer.addStretch(1)

        self._save_btn = QPushButton("Сохранить")
        self._save_btn.setFixedHeight(48)
        self._save_btn.setMinimumWidth(160)
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700; padding: 0 24px;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #DC6803; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._save_btn.clicked.connect(self._on_save)
        footer.addWidget(self._save_btn)
        v.addLayout(footer)

    # -------- handlers --------

    def _on_amount_changed(self, text: str) -> None:
        # Чистим: разрешаем только цифры и одну точку.
        cleaned = "".join(c for c in (text or "") if c.isdigit() or c == ".")
        # Только одна точка
        if cleaned.count(".") > 1:
            first = cleaned.find(".")
            cleaned = cleaned[: first + 1] + cleaned[first + 1 :].replace(".", "")
        if cleaned != text:
            self._amount_input.blockSignals(True)
            self._amount_input.setText(cleaned)
            self._amount_input.blockSignals(False)
        self._save_btn.setEnabled(self._parse_amount() is not None)

    def _parse_amount(self) -> Decimal | None:
        raw = self._amount_input.text().strip()
        if not raw or raw == ".":
            return None
        try:
            v = Decimal(raw)
        except InvalidOperation:
            return None
        if v <= 0:
            return None
        return v

    def _kind(self) -> str:
        return "cash_in" if self._rb_in.isChecked() else "cash_out"

    def _on_save(self) -> None:
        amount = self._parse_amount()
        if amount is None:
            return
        body = {
            "kind": self._kind(),
            "amount": str(amount),
            "reason": self._reason_input.toPlainText().strip(),
        }
        try:
            data = self._client.post(
                f"/shifts/{self._shift_id}/cash_op/", json=body
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось сохранить операцию:\n{e.message}\n[{e.code}]",
            )
            return
        # ApiClient разворачивает {"data": ...}, либо вернёт сам объект
        op = data.get("data") if isinstance(data, dict) and "data" in data else data
        self.op_created.emit(op or body)
        self.accept()
