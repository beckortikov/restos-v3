"""Перенос заказа — frame 7 в design/pos_cashier.pen.

Список свободных столов в зале (исключая исходный). Клик по столу = выбор,
[Перенести] подтверждает. Сервер: POST /orders/{id}/transfer/ {table_id}.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _TransferWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self, client: ApiClient, order_id: int, target_table_id: int
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.target_table_id = target_table_id

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/orders/{self.order_id}/transfer/",
                json={"table_id": self.target_table_id},
                idempotent=True,
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class TransferDialog(QDialog):
    """Карточный grid со свободными столами. Один клик — выбор + подсветка."""

    transferred = Signal(dict)

    def __init__(
        self,
        order: dict,
        tables: list[dict],
        client: ApiClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._order = order
        self._tables = tables
        self._client = client
        self._selected_id: int | None = None
        self._buttons: dict[int, QPushButton] = {}
        self._thread: QThread | None = None
        self._worker: _TransferWorker | None = None

        self.setWindowTitle("Перенос заказа")
        self.setModal(True)
        self.setFixedWidth(720)
        self.setMinimumHeight(540)
        self._build()

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
        icon.setPixmap(qpixmap("arrow-right", COLORS["primary_blue"], 22))
        layout.addWidget(icon)

        src_table = (
            self._order.get("table_name")
            or f"#{self._order.get('table', '?')}"
        )
        title = QLabel(
            f"Перенос заказа #{self._order.get('id', '?')} со «{src_table}»"
        )
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

        prompt = QLabel("Выберите свободный стол для переноса:")
        prompt.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        v.addWidget(prompt)

        # Список свободных столов (исключая исходный)
        free = [
            t for t in self._tables
            if str(t.get("status", "")) == "free"
            and int(t.get("id", 0)) != int(self._order.get("table") or 0)
        ]
        free.sort(key=lambda t: int(t.get("number", 0)))

        if not free:
            empty = QLabel("Нет свободных столов")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 13pt;"
                f" padding: 60px 0;"
                f" background: {COLORS['bg_light']};"
                f" border: 1px solid {COLORS['border_light']};"
                f" border-radius: {RADIUS['md']}px;"
            )
            v.addWidget(empty, 1)
            return body

        # Grid в scroll-area
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(SPACING["md"])

        cols = 4
        for i, t in enumerate(free):
            grid.addWidget(self._build_table_card(t), i // cols, i % cols)
        # Пустая колонка-spacer чтобы карточки не растягивались
        grid.setColumnStretch(cols, 1)
        grid.setRowStretch((len(free) // cols) + 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)
        return body

    def _build_table_card(self, table: dict) -> QPushButton:
        tid = int(table["id"])
        cap = table.get("capacity", 0)
        btn = QPushButton(f"{table.get('name', '?')}\n{cap} мест")
        btn.setFixedSize(140, 96)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        btn.setStyleSheet(self._card_qss(active=False))
        btn.clicked.connect(lambda _c=False, i=tid: self._on_select(i))
        self._buttons[tid] = btn
        return btn

    def _card_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['primary_blue']};"
                f"  color: {COLORS['text_white']};"
                f"  border: 2px solid {COLORS['primary_blue']};"
                f"  border-radius: {RADIUS['md']}px;"
                f"  font-size: 13pt; font-weight: 700;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"  font-size: 13pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _on_select(self, table_id: int) -> None:
        self._selected_id = table_id
        for tid, btn in self._buttons.items():
            is_active = (tid == table_id)
            btn.setChecked(is_active)
            btn.setStyleSheet(self._card_qss(active=is_active))
        self._submit_btn.setEnabled(True)

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])

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

        self._submit_btn = QPushButton("Перенести")
        self._submit_btn.setFixedHeight(44)
        self._submit_btn.setMinimumWidth(160)
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setEnabled(False)
        self._submit_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['primary_blue']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #1D4ED8; }}"
            f"QPushButton:disabled {{ background: #93C5FD; color: white; }}"
        )
        self._submit_btn.clicked.connect(self._submit)
        h.addWidget(self._submit_btn)
        return f

    def _submit(self) -> None:
        if self._selected_id is None or self._thread is not None:
            return
        self._submit_btn.setEnabled(False)
        self._submit_btn.setText("Перенос…")

        thread = QThread(self)
        worker = _TransferWorker(
            self._client, int(self._order["id"]), int(self._selected_id)
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_done)
        worker.error.connect(self._on_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup(self) -> None:
        t = self._thread
        self._thread = None
        self._worker = None
        if t is not None:
            t.deleteLater()

    def _on_done(self, order: dict) -> None:
        self.transferred.emit(order)
        self.accept()

    def _on_failed(self, exc: ApiError) -> None:
        self._submit_btn.setEnabled(True)
        self._submit_btn.setText("Перенести")
        QMessageBox.warning(
            self, "Ошибка переноса",
            f"Не удалось перенести заказ: {exc.message}",
        )
