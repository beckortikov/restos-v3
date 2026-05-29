"""Возврат — frame 13 в design/pos_cashier.pen.

Возврат по закрытому (DONE) заказу. UI:
- Header: «Возврат — Заказ #N»
- Информация о заказе (сумма, метод оплаты, дата)
- Список позиций с qty-spinner: сколько вернуть из каждой (по умолчанию 0)
- Поле «Причина» (textarea) — обязательно
- Footer: [Отмена] [Возврат всего] [Вернуть выбранное]

Сервер: POST /orders/{id}/refund/ с Idempotency-Key.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING

PAYMENT_LABELS = {"cash": "Наличные", "card": "Карта", "transfer": "Перевод"}


class _RefundWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self, client: ApiClient, order_id: int, items: list[dict],
        reason: str, idem_key: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.items = items
        self.reason = reason
        self.idem_key = idem_key

    def run(self) -> None:
        try:
            data = self.client.request(
                "POST",
                f"/orders/{self.order_id}/refund/",
                json={"items": self.items, "reason": self.reason},
                extra_headers={"Idempotency-Key": self.idem_key},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class RefundDialog(QDialog):
    refund_completed = Signal(dict)

    def __init__(
        self, order: dict, client: ApiClient, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._order = order
        self._client = client
        self._idem_key = str(uuid.uuid4())
        self._spinners: dict[int, QSpinBox] = {}  # order_item_id → spin
        self._items_subtotal_label: QLabel | None = None
        self._thread: QThread | None = None
        self._worker: _RefundWorker | None = None

        self.setWindowTitle("Возврат")
        self.setModal(True)
        self.setFixedWidth(640)
        self.setMinimumHeight(620)
        self._build()

    # -------- build --------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(60)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)
        layout.setSpacing(SPACING["sm"])

        icon = QLabel()
        icon.setPixmap(qpixmap("refresh-cw", COLORS["danger_red"], 22))
        layout.addWidget(icon)

        title = QLabel(f"Возврат — Заказ #{self._order.get('id', '?')}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        layout.addWidget(title)
        layout.addStretch(1)
        return h

    def _build_body(self) -> QWidget:
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        v = QVBoxLayout(body)
        v.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # Order info card
        v.addWidget(self._build_order_info())

        # Items list
        items_label = QLabel("Позиции к возврату")
        items_label.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" margin-top: 8px;"
        )
        v.addWidget(items_label)

        self._items_holder = QWidget()
        self._items_layout = QVBoxLayout(self._items_holder)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(6)
        self._items_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._items_holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)

        self._render_items()

        # Sum
        self._items_subtotal_label = QLabel("Сумма к возврату: 0.00 TJS")
        self._items_subtotal_label.setStyleSheet(
            f"color: {COLORS['danger_red']}; font-size: 14pt; font-weight: 700;"
            f" padding-top: 4px;"
        )
        self._items_subtotal_label.setAlignment(Qt.AlignRight)
        v.addWidget(self._items_subtotal_label)

        # Reason
        reason_lbl = QLabel("Причина возврата")
        reason_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" margin-top: 4px;"
        )
        v.addWidget(reason_lbl)

        self._reason_edit = QTextEdit()
        self._reason_edit.setFixedHeight(72)
        self._reason_edit.setPlaceholderText(
            "Опишите причину возврата (обязательно)…"
        )
        self._reason_edit.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
            f"QTextEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        v.addWidget(self._reason_edit)
        return body

    def _build_order_info(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        h = QHBoxLayout(card)
        h.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        h.setSpacing(SPACING["xl"])

        def col(title: str, value: str, color: str = COLORS["text_primary"]) -> QVBoxLayout:
            cv = QVBoxLayout()
            cv.setSpacing(2)
            t = QLabel(title)
            t.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 10pt;"
                f" border: none; background: transparent;"
            )
            cv.addWidget(t)
            v = QLabel(value)
            v.setStyleSheet(
                f"color: {color}; font-size: 13pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            cv.addWidget(v)
            return cv

        total = self._order.get("total", "0.00")
        method = PAYMENT_LABELS.get(
            self._order.get("payment_method") or "", "—"
        )
        closed = (self._order.get("closed_at") or "")[:16].replace("T", " ")

        h.addLayout(col("Сумма заказа", f"{total} TJS"))
        h.addLayout(col("Метод оплаты", method))
        h.addLayout(col("Закрыт", closed or "—"))
        h.addStretch(1)
        return card

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])
        h.setSpacing(SPACING["sm"])

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
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
        h.addWidget(cancel)
        h.addStretch(1)

        all_btn = QPushButton("Возврат всего заказа")
        all_btn.setFixedHeight(44)
        all_btn.setMinimumWidth(180)
        all_btn.setCursor(Qt.PointingHandCursor)
        all_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['danger_red']};"
            f"  border: 1.5px solid {COLORS['danger_red']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #FEE2E2; }}"
        )
        all_btn.clicked.connect(self._submit_full)
        h.addWidget(all_btn)

        self._submit_btn = QPushButton("Вернуть выбранное")
        self._submit_btn.setFixedHeight(44)
        self._submit_btn.setMinimumWidth(180)
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #B91C1C; }}"
            f"QPushButton:disabled {{ background: #FCA5A5; color: white; }}"
        )
        self._submit_btn.clicked.connect(self._submit_selected)
        h.addWidget(self._submit_btn)
        return f

    def _render_items(self) -> None:
        items = self._order.get("items") or []
        active = [i for i in items if not i.get("cancelled_at")]
        if not active:
            empty = QLabel("В заказе нет активных позиций")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; padding: 40px 0;"
                f" border: none;"
            )
            self._items_layout.addWidget(empty)
            return

        for item in active:
            self._items_layout.addWidget(self._build_item_row(item))

    def _build_item_row(self, item: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(SPACING["md"])

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(item.get("name_at_order", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(name)
        try:
            price = Decimal(str(item.get("price_at_order", "0.00")))
        except Exception:
            price = Decimal("0.00")
        sub = QLabel(
            f"{price:.2f} TJS × {item.get('qty', 0)} = {price * int(item.get('qty', 0)):.2f} TJS"
        )
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(sub)
        h.addLayout(text_col, 1)

        qty_lbl = QLabel("Вернуть:")
        qty_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        h.addWidget(qty_lbl)

        spin = QSpinBox()
        spin.setRange(0, int(item.get("qty", 0)))
        spin.setValue(0)
        spin.setFixedWidth(72)
        spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 4px 8px; min-height: 24px;"
            f"}}"
        )
        spin.valueChanged.connect(self._update_subtotal)
        h.addWidget(spin)
        self._spinners[int(item["id"])] = spin

        of_lbl = QLabel(f"из {item.get('qty', 0)}")
        of_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        h.addWidget(of_lbl)
        return row

    def _update_subtotal(self) -> None:
        if self._items_subtotal_label is None:
            return
        items = self._order.get("items") or []
        by_id = {int(i["id"]): i for i in items}
        total = Decimal("0.00")
        for oid, spin in self._spinners.items():
            qty = int(spin.value())
            if qty <= 0:
                continue
            try:
                price = Decimal(str(by_id[oid].get("price_at_order", "0.00")))
            except Exception:
                price = Decimal("0.00")
            total += price * qty
        self._items_subtotal_label.setText(f"Сумма к возврату: {total:.2f} TJS")

    # -------- handlers --------

    def _gather_selected(self) -> list[dict]:
        return [
            {"order_item_id": oid, "qty": int(s.value())}
            for oid, s in self._spinners.items()
            if int(s.value()) > 0
        ]

    def _validate_reason(self) -> str | None:
        reason = self._reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Ошибка", "Укажите причину возврата")
            return None
        return reason

    def _submit_full(self) -> None:
        reason = self._validate_reason()
        if reason is None:
            return
        ans = QMessageBox.question(
            self, "Подтверждение",
            "Вернуть заказ полностью? Эту операцию нельзя отменить.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn(items=[], reason=reason)

    def _submit_selected(self) -> None:
        reason = self._validate_reason()
        if reason is None:
            return
        items = self._gather_selected()
        if not items:
            QMessageBox.warning(self, "Ошибка", "Выберите позиции для возврата")
            return
        self._spawn(items=items, reason=reason)

    def _spawn(self, *, items: list[dict], reason: str) -> None:
        if self._thread is not None:
            return  # уже идёт
        self._submit_btn.setEnabled(False)
        self._submit_btn.setText("Возврат…")

        thread = QThread(self)
        worker = _RefundWorker(
            self._client, int(self._order["id"]),
            items=items, reason=reason, idem_key=self._idem_key,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_done)
        worker.error.connect(self._on_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._cleanup_thread)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup_thread(self) -> None:
        t = self._thread
        self._thread = None
        self._worker = None
        if t is not None:
            t.deleteLater()

    def _on_done(self, refund: dict) -> None:
        self.refund_completed.emit(refund)
        QMessageBox.information(
            self, "Возврат выполнен",
            f"Возвращено: {refund.get('amount', '?')} TJS",
        )
        self.accept()

    def _on_failed(self, exc: ApiError) -> None:
        self._submit_btn.setEnabled(True)
        self._submit_btn.setText("Вернуть выбранное")
        QMessageBox.warning(
            self, "Ошибка возврата",
            f"Не удалось выполнить возврат: {exc.message}",
        )
