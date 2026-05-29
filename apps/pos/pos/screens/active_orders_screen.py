"""Экран 3. Активные заказы — frame "10. Активные заказы" в design/pos_cashier.pen."""
import math
import uuid

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, SPACING
from pos.state import State
from pos.widgets.order_card import OrderCard
from pos.widgets.sidebar import Sidebar

GRID_MIN_COLUMNS = 2
GRID_MAX_COLUMNS = 6
GRID_PADDING_H = 16
GRID_PADDING_V = 16


class _CancelWorker(QObject):
    success = Signal(int)
    error = Signal(int, object)

    def __init__(
        self, client: ApiClient, order_id: int, manager_pin: str = "",
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.manager_pin = manager_pin

    def run(self) -> None:
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        if self.manager_pin:
            headers["X-Manager-Pin"] = self.manager_pin
        try:
            self.client.post(
                f"/orders/{self.order_id}/cancel/",
                json={"reason": "Отменён кассиром"},
                extra_headers=headers,
            )
            self.success.emit(self.order_id)
        except ApiError as e:
            self.error.emit(self.order_id, e)


class ActiveOrdersScreen(QWidget):
    """Сетка активных заказов. Подписан на state.orders_changed.

    Сигналы:
        pay_requested(order_id) — открыть Payment screen (next iteration)
        order_clicked(order_id) — открыть OrderDetail модалку (next iteration)
        logout_requested
        nav_requested(name) — переключение на другой экран из sidebar
    """

    pay_requested = Signal(int)
    order_clicked = Signal(int)
    logout_requested = Signal()
    nav_requested = Signal(str)
    nav_to_history = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._cards: list[OrderCard] = []
        self._columns = GRID_MIN_COLUMNS
        self._cancel_threads: list[QThread] = []
        # Текущий фильтр по типу заказа: "all" | "hall" | "takeaway" | "delivery"
        # (frame 10 + frame 11 — это один экран с tabs).
        self._type_filter: str = "all"
        self._tab_buttons: dict[str, QPushButton] = {}

        self._build()
        self.state.orders_changed.connect(self._render_orders)
        self.state.online_changed.connect(self._render_status)

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"ActiveOrdersScreen {{ background-color: {COLORS['bg_light']}; }}"
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(active="orders")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        cv.addWidget(self._build_topbar())
        cv.addWidget(self._build_grid_scroll(), 1)
        cv.addWidget(self._build_statusbar())

        root.addWidget(center, 1)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(52)
        bar.setStyleSheet(
            f"#topBar {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(SPACING["md"])

        # Tabs по типу заказа (frame 10 + frame 11 — единый экран).
        # active = "all" — текущая активная вкладка (оранжевый pill).
        for key, label in (
            ("all", "Все заказы"),
            ("hall", "Зал"),
            ("takeaway", "С собой"),
            ("delivery", "Доставка"),
        ):
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._tab_qss(active=(key == self._type_filter)))
            btn.clicked.connect(lambda _c=False, k=key: self.set_type_filter(k))
            self._tab_buttons[key] = btn
            h.addWidget(btn)

        # «Закрытые сегодня» / «Архив» — отдельный navigation, переключают
        # на OrderHistoryScreen.
        sep = QFrame()
        sep.setFixedSize(1, 24)
        sep.setStyleSheet(f"background: {COLORS['border_light']};")
        h.addWidget(sep)

        history_btn = QPushButton("Закрытые сегодня")
        history_btn.setFlat(True)
        history_btn.setCursor(Qt.PointingHandCursor)
        history_btn.setStyleSheet(self._tab_qss(active=False))
        history_btn.clicked.connect(self.nav_to_history.emit)
        h.addWidget(history_btn)

        archive_btn = QPushButton("Архив")
        archive_btn.setFlat(True)
        archive_btn.setCursor(Qt.PointingHandCursor)
        archive_btn.setStyleSheet(self._tab_qss(active=False))
        archive_btn.clicked.connect(self.nav_to_history.emit)
        h.addWidget(archive_btn)

        h.addStretch(1)

        # Счётчик «N заказов в очереди» — оранжевый bold (по дизайну frame 11)
        self._queue_count_lbl = QLabel("")
        self._queue_count_lbl.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 11pt; font-weight: 700;"
        )
        h.addWidget(self._queue_count_lbl)

        self._cashier_lbl = QLabel("")
        self._cashier_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        h.addWidget(self._cashier_lbl)
        return bar

    def _tab_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 6px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"  padding: 6px 14px;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none;"
            f"  font-size: 11pt; font-weight: 500;"
            f"  padding: 6px 14px;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
        )

    def set_type_filter(self, key: str) -> None:
        """Переключить вкладку (all / hall / takeaway / delivery)."""
        if key not in {"all", "hall", "takeaway", "delivery"}:
            return
        self._type_filter = key
        for k, btn in self._tab_buttons.items():
            btn.setStyleSheet(self._tab_qss(active=(k == key)))
        self._render_orders()

    def set_cashier_name(self, name: str) -> None:
        self._cashier_lbl.setText(name)

    def _build_grid_scroll(self) -> QWidget:
        self._grid_holder = QWidget()
        self._grid = QGridLayout(self._grid_holder)
        self._grid.setContentsMargins(
            GRID_PADDING_H, GRID_PADDING_V, GRID_PADDING_H, GRID_PADDING_V
        )
        self._grid.setHorizontalSpacing(SPACING["md"])
        self._grid.setVerticalSpacing(SPACING["md"])

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidget(self._grid_holder)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {COLORS['bg_light']}; border: none; }}"
            f" QWidget {{ background-color: {COLORS['bg_light']}; }}"
        )
        return self._scroll

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(
            f"#statusBar {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        self._status_label = QLabel("● Online")
        self._status_label.setStyleSheet(
            f"color: {COLORS['success_green']}; font-size: 11pt;"
        )
        h.addStretch(1)
        h.addWidget(self._status_label)
        return bar

    # ------- rendering -------

    def _compute_columns(self) -> int:
        n = max(1, len(self.state.orders))
        viewport = self._scroll.viewport().width() if hasattr(self, "_scroll") else self.width()
        usable = max(0, viewport - 2 * GRID_PADDING_H)
        cell = OrderCard.MIN_WIDTH + SPACING["md"]
        max_by_width = max(
            GRID_MIN_COLUMNS,
            min(GRID_MAX_COLUMNS, (usable + SPACING["md"]) // cell or 1),
        )
        target = math.ceil(math.sqrt(n))
        return max(GRID_MIN_COLUMNS, min(int(max_by_width), target))

    def _clear_grid_stretches(self) -> None:
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)

    def _render_orders(self) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._clear_grid_stretches()

        # Фильтр по типу заказа (вкладки frame 10/11).
        all_orders = list(self.state.orders)
        if self._type_filter != "all":
            filtered = [
                o for o in all_orders
                if (o.get("order_type") or "hall") == self._type_filter
            ]
        else:
            filtered = all_orders

        # сначала bill_requested, потом new — оба отсортированы по created_at desc
        def _key(o: dict) -> tuple:
            return (
                0 if o.get("status") == "bill_requested" else 1,
                -(_iso_to_seconds(o.get("created_at"))),
            )

        orders = sorted(filtered, key=_key)

        cols = self._compute_columns_for(len(orders))
        self._columns = cols

        for i, order in enumerate(orders):
            row, col = divmod(i, cols)
            card = OrderCard(order)
            card.pay_clicked.connect(self.pay_requested.emit)
            card.cancel_clicked.connect(self._on_cancel)
            card.clicked.connect(self.order_clicked.emit)
            self._grid.addWidget(card, row, col)
            self._cards.append(card)

        if orders:
            rows = math.ceil(len(orders) / cols)
            for c in range(cols):
                self._grid.setColumnStretch(c, 1)
            for r in range(rows):
                self._grid.setRowStretch(r, 1)

        # Счётчик в шапке: «N заказов в очереди»
        n = len(orders)
        if n > 0:
            self._queue_count_lbl.setText(
                f"{n} {self._orders_word(n)} в очереди"
            )
        else:
            self._queue_count_lbl.setText("")

    def _compute_columns_for(self, n: int) -> int:
        n = max(1, n)
        viewport = self._scroll.viewport().width() if hasattr(self, "_scroll") else self.width()
        usable = max(0, viewport - 2 * GRID_PADDING_H)
        cell = OrderCard.MIN_WIDTH + SPACING["md"]
        max_by_width = max(
            GRID_MIN_COLUMNS,
            min(GRID_MAX_COLUMNS, (usable + SPACING["md"]) // cell or 1),
        )
        target = math.ceil(math.sqrt(n))
        return max(GRID_MIN_COLUMNS, min(int(max_by_width), target))

    @staticmethod
    def _orders_word(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return "заказ"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "заказа"
        return "заказов"

    def _render_status(self, online: bool) -> None:
        if online:
            self._status_label.setText("● Online")
            self._status_label.setStyleSheet(
                f"color: {COLORS['success_green']}; font-size: 11pt;"
            )
        else:
            self._status_label.setText("● Offline — нет связи с backend")
            self._status_label.setStyleSheet(
                f"color: {COLORS['danger_red']}; font-size: 11pt;"
            )

    # ------- handlers -------

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        else:
            self.nav_requested.emit(name)

    def _on_cancel(self, order_id: int, manager_pin: str = "") -> None:
        if not manager_pin:
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Отменить заказ")
            confirm.setText(f"Отменить заказ #{order_id}?")
            confirm.setIcon(QMessageBox.Question)
            yes = confirm.addButton("Отменить", QMessageBox.YesRole)
            confirm.addButton("Не отменять", QMessageBox.NoRole)
            confirm.exec()
            if confirm.clickedButton() != yes:
                return

        thread = QThread(self)
        worker = _CancelWorker(self.state.client, order_id, manager_pin)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_cancel_done)
        worker.error.connect(self._on_cancel_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cancel_threads.remove(thread)
                                if thread in self._cancel_threads else None)
        # Удержать worker, иначе Python GC удалит его до старта потока.
        thread._worker = worker  # noqa: SLF001
        self._cancel_threads.append(thread)
        thread.start()

    def _on_cancel_done(self, order_id: int) -> None:
        # SSE-событие order.updated с status=cancelled удалит карточку из state.
        # Если SSE буферизирует — форсируем refresh.
        self.state.refresh()

    def _on_cancel_failed(self, order_id: int, exc: ApiError) -> None:
        if exc.code in ("MANAGER_OVERRIDE_REQUIRED", "MANAGER_OVERRIDE_INVALID_PIN"):
            from pos.screens.manager_pin_dialog import ManagerPinDialog

            msg = (
                "Неверный PIN. Попробуйте ещё раз."
                if exc.code == "MANAGER_OVERRIDE_INVALID_PIN"
                else "Эта операция требует подтверждения менеджера"
            )
            dlg = ManagerPinDialog(message=msg, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted and dlg.pin:
                self._on_cancel(order_id, manager_pin=dlg.pin)
            return
        QMessageBox.warning(
            self, "Ошибка отмены", f"Не удалось отменить #{order_id}: {exc.message}"
        )

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._cards and self._compute_columns_for(len(self._cards)) != self._columns:
            self._render_orders()


def _iso_to_seconds(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        from datetime import datetime as _dt
        return int(_dt.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0
