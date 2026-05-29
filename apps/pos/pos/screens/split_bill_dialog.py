"""Разделить счёт — frame 6 в design/pos_cashier.pen.

Разделение поровну на N частей. UI:
- Заголовок «Разделить счёт»
- Сумма заказа + spinner «На сколько частей»
- Превью: «Каждый платит: X TJS» (последняя часть может отличаться на копейки)
- Кнопка «Печатать N пре-чеков» → POST /orders/{id}/split_print/

После печати оплата идёт обычным [Оплата] flow — учитывая, что счёт уже разделён,
кассир вызывает PaymentDialog последовательно для каждого «гостя» с фиксированной
долей. Это упрощённый MVP-вариант (для подробной оплаты по частям — Phase 2).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _SplitWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, order_id: int, parts: int) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.parts = parts

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/orders/{self.order_id}/split_print/",
                json={"parts": self.parts},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class SplitBillDialog(QDialog):
    """Frame 6 — разделение поровну."""

    split_completed = Signal(dict)

    def __init__(
        self, order: dict, client: ApiClient, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._order = order
        self._client = client
        self._thread: QThread | None = None
        self._worker: _SplitWorker | None = None

        self.setWindowTitle("Разделить счёт")
        self.setModal(True)
        self.setFixedWidth(440)
        self._build()
        self._update_share()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)
        layout.setSpacing(SPACING["sm"])

        icon = QLabel()
        icon.setPixmap(qpixmap("receipt", COLORS["accent_orange"], 22))
        layout.addWidget(icon)

        title = QLabel("Разделить счёт")
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
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Order total
        total_lbl = QLabel(f"Сумма заказа: {self._total_decimal():.2f} TJS")
        total_lbl.setAlignment(Qt.AlignCenter)
        total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        v.addWidget(total_lbl)

        # Parts spinner
        parts_row = QHBoxLayout()
        parts_lbl = QLabel("На сколько частей разделить:")
        parts_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 600;"
        )
        parts_row.addWidget(parts_lbl)

        self._parts_spin = QSpinBox()
        self._parts_spin.setRange(2, 50)
        # По умолчанию — кол-во гостей если >= 2, иначе 2
        guests = int(self._order.get("guests_count") or 0)
        self._parts_spin.setValue(max(guests, 2))
        self._parts_spin.setFixedHeight(40)
        self._parts_spin.setFixedWidth(96)
        self._parts_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 4px 8px;"
            f"  font-size: 13pt; font-weight: 700;"
            f"}}"
        )
        self._parts_spin.valueChanged.connect(self._update_share)
        parts_row.addWidget(self._parts_spin)
        parts_row.addStretch(1)
        v.addLayout(parts_row)

        # Share preview
        share_card = QFrame()
        share_card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        scv = QVBoxLayout(share_card)
        scv.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        scv.setSpacing(4)
        scv.setAlignment(Qt.AlignCenter)

        self._share_lbl = QLabel("0.00 TJS")
        self._share_lbl.setAlignment(Qt.AlignCenter)
        self._share_lbl.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 28pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        scv.addWidget(self._share_lbl)

        self._share_sub = QLabel("на каждого гостя")
        self._share_sub.setAlignment(Qt.AlignCenter)
        self._share_sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        scv.addWidget(self._share_sub)
        v.addWidget(share_card)

        note = QLabel(
            "Будут напечатаны N пре-чеков с пометкой «Часть K из N» — "
            "по одному на каждого гостя."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        v.addWidget(note)
        return body

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

        self._submit_btn = QPushButton("Печатать пре-чеки")
        self._submit_btn.setFixedHeight(44)
        self._submit_btn.setMinimumWidth(180)
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #EA5E0C; }}"
            f"QPushButton:disabled {{ background: #FED7AA; color: white; }}"
        )
        self._submit_btn.clicked.connect(self._submit)
        h.addWidget(self._submit_btn)
        return f

    # -------- helpers --------

    def _total_decimal(self) -> Decimal:
        try:
            return Decimal(str(self._order.get("total", "0.00") or "0.00"))
        except Exception:
            return Decimal("0.00")

    def _update_share(self) -> None:
        total = self._total_decimal()
        parts = int(self._parts_spin.value())
        if parts <= 0:
            return
        share = (total / parts).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        last = total - share * (parts - 1)
        if last != share:
            self._share_lbl.setText(f"{share:.2f} TJS")
            self._share_sub.setText(
                f"на гостей 1..{parts - 1} ({last:.2f} TJS — последний)"
            )
        else:
            self._share_lbl.setText(f"{share:.2f} TJS")
            self._share_sub.setText(f"на каждого из {parts} гостей")

    # -------- handlers --------

    def _submit(self) -> None:
        if self._thread is not None:
            return
        self._submit_btn.setEnabled(False)
        self._submit_btn.setText("Печатается…")

        thread = QThread(self)
        worker = _SplitWorker(
            self._client, int(self._order["id"]), int(self._parts_spin.value())
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_done)
        worker.error.connect(self._on_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        # Удержать worker, иначе Python GC удалит его до старта потока.
        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup(self) -> None:
        t = self._thread
        self._thread = None
        self._worker = None
        if t is not None:
            t.deleteLater()

    def _on_done(self, data: dict) -> None:
        self.split_completed.emit(data)
        QMessageBox.information(
            self,
            "Готово",
            f"Напечатано {data.get('parts', '?')} пре-чеков по {data.get('share', '?')} TJS",
        )
        self.accept()

    def _on_failed(self, exc: ApiError) -> None:
        self._submit_btn.setEnabled(True)
        self._submit_btn.setText("Печатать пре-чеки")
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось разделить счёт: {exc.message}"
        )
