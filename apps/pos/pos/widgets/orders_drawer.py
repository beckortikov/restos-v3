"""Drawer «Заказы» — overlay поверх правой части TablesScreen.

Открывается по клику кнопки `Заказы` в топбаре. Даёт кассиру быстрый доступ
к двум спискам без ухода с карты зала:
- **Текущие** — открытые заказы (NEW / BILL_REQUESTED) из state.orders, без API-запроса.
- **Закрытые сегодня** — done/cancelled заказы за сегодня (GET /orders/?status=...).

Действия в строке зависят от статуса:
- **NEW / BILL_REQUESTED** (текущие): кнопка `Оплатить` (primary, оранжевый) +
  иконка-кнопка `Печать` (outline). Клик `Оплатить` эмитит `pay_requested(id)` —
  TablesScreen прокидывает на main.py, открывается PaymentDialog как для клика
  по столу. После оплаты state.orders_changed → drawer перерисуется и заказ
  пропадёт из «Текущих» (станет DONE).
- **DONE / CANCELLED** (закрытые сегодня): только `Печать чека` → reprint
  через `reprint_requested(id)`.

Это даёт кассиру замкнутый flow в drawer'е без перехода на карту зала.

Сигналы:
    closed() — клик по крестику; main скрывает drawer.
    reprint_requested(order_id: int) — POST /orders/{id}/reprint_receipt/ для DONE.
    pre_bill_requested(order_id: int) — POST /orders/{id}/print_pre_bill/ для активных.
    pay_requested(order_id: int) — открыть оплату (close order).
"""
from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as tz

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State


class OrdersDrawer(QFrame):
    """Overlay-панель 420px справа: 2 таба + список + reprint actions."""

    closed = Signal()
    reprint_requested = Signal(int)
    pre_bill_requested = Signal(int)
    pay_requested = Signal(int)
    # Drawer запросил resize своей ширины (для inline-payment 420 → 540).
    # TablesScreen подписывается → reposition.
    width_change_requested = Signal(int)

    # Единая ширина (= OrderDetailPanel) для всех режимов drawer'а: список
    # заказов, оплата, пре-чек. Drawer всегда overlay (y=0, full-height) и
    # полностью перекрывает правый сайдбар «Выберите стол».
    PANEL_WIDTH = 360
    PAYMENT_WIDTH = 360
    PRE_BILL_WIDTH = 360

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._active_tab: str = "current"  # "current" | "closed_today"
        self._closed_orders: list[dict] = []
        self._closed_loaded: bool = False

        self.setObjectName("ordersDrawer")
        self.setFixedWidth(OrdersDrawer.PANEL_WIDTH)
        self.setStyleSheet(
            f"#ordersDrawer {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        # Тень для overlay-эффекта (лёгкая).
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._build()
        # Перерисовка при изменении state.orders (новые заказы / закрытие).
        self.state.orders_changed.connect(self._on_orders_changed)

    # -------- public API --------

    def refresh(self) -> None:
        """Принудительно перерисовать списки. Для «закрытые» — повторно тянем API."""
        self._closed_loaded = False
        self._render_list()

    def show_payment(self, order: dict, table: dict | None) -> None:
        """Inline-режим оплаты: новый OrderPaymentPanel (restos-style
        single-column) в page 1 body_stack'а. Заменил embedded PaymentDialog —
        в drawer'е выглядит компактнее и понятнее."""
        from pos.widgets.order_payment_panel import OrderPaymentPanel

        if self._payment_widget is not None:
            self._payment_layout.removeWidget(self._payment_widget)
            self._payment_widget.deleteLater()
            self._payment_widget = None

        panel = OrderPaymentPanel(
            order=order,
            table=table or {},
            client=self.state.client,
            parent=self._payment_holder,
        )
        # Успешное закрытие заказа → drawer возвращается к списку + refresh.
        panel.order_closed.connect(self._on_payment_done)
        # Pre-bill из panel → swap на embedded pre-bill view внутри того же drawer'а.
        panel.pre_bill_requested.connect(
            lambda oid, o=order, t=table: self.show_pre_bill(o, t),
        )
        # Cancel заказа → bubble up через сигнал drawer'а (host разрулит).
        panel.cancel_requested.connect(self._on_cancel_order_from_panel)
        # Скидка → DiscountPickerDialog как modal (явная модалка OK).
        panel.discount_requested.connect(
            lambda oid, o=order, t=table: self._open_discount_picker(o, t),
        )
        # × на позиции → CancelItemDialog с reason picker.
        panel.cancel_item_requested.connect(self._on_cancel_item_from_panel)
        # «Дополнительно» → Разделить счёт / Перенести (open modal dialogs).
        panel.split_requested.connect(self._on_split_from_panel)
        panel.transfer_requested.connect(self._on_transfer_from_panel)

        self._payment_layout.addWidget(panel)
        self._payment_widget = panel
        self._header_title.setText(f"Оплата №{order.get('id', '')}")

        # Payment теперь так же overlay как pre-bill — 360px, перекрывает
        # OrderDetailPanel, accent-orange border-left для подсветки sidebar'а.
        self.setStyleSheet(
            f"#ordersDrawer {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 4px solid {COLORS['accent_orange']};"
            f"}}"
        )
        self.overlay_mode = True
        self.setFixedWidth(OrdersDrawer.PAYMENT_WIDTH)
        self.width_change_requested.emit(OrdersDrawer.PAYMENT_WIDTH)
        self._body_stack.setCurrentIndex(1)

    def _on_cancel_order_from_panel(self, order_id: int) -> None:
        """Из OrderPaymentPanel пришёл cancel — POST /orders/{id}/cancel/."""
        from uuid import uuid4
        try:
            self.state.client.post(
                f"/orders/{order_id}/cancel/",
                json={"reason": "Отменён кассиром"},
                extra_headers={"Idempotency-Key": str(uuid4())},
            )
        except ApiError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Ошибка отмены", f"Не удалось отменить: {e.message}",
            )
            return
        try:
            self.state.refresh()
        except Exception:
            pass
        self._close_payment()

    def _open_discount_picker(self, order: dict, table: dict | None) -> None:
        """Открыть DiscountPickerDialog. После применения — обновить order
        в текущей panel."""
        from pos.http_client import ApiError as _ApiError
        from pos.screens.discount_picker_dialog import DiscountPickerDialog

        try:
            data = self.state.client.get(
                "/discounts/", params={"type": "discount", "is_active": "true"},
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            discounts = [d for d in items if d.get("is_active", True)]
        except _ApiError:
            discounts = []

        dlg = DiscountPickerDialog(
            order=order,
            discounts=discounts,
            client=self.state.client,
            parent=self,
        )
        dlg.discount_applied.connect(
            lambda new_order: self._on_discount_applied(new_order, table),
        )
        dlg.exec()

    def _on_split_from_panel(self, order_id: int) -> None:
        """«Разделить счёт» из OrderPaymentPanel → SplitBillDialog (modal)."""
        from pos.screens.split_bill_dialog import SplitBillDialog
        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)),
            None,
        )
        if order is None:
            return
        dlg = SplitBillDialog(order=order, client=self.state.client, parent=self)
        dlg.exec()
        try:
            self.state.refresh()
        except Exception:
            pass

    def _on_transfer_from_panel(self, order_id: int) -> None:
        """«Перенести» из OrderPaymentPanel → TransferDialog (modal). После
        успешного переноса заказ уходит на другой стол → закрываем drawer-view."""
        from pos.screens.transfer_dialog import TransferDialog
        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)),
            None,
        )
        if order is None:
            return
        dlg = TransferDialog(
            order=order,
            tables=list(self.state.tables),
            client=self.state.client,
            parent=self,
        )
        dlg.transferred.connect(lambda _o: self._on_after_transfer())
        dlg.exec()

    def _on_after_transfer(self) -> None:
        try:
            self.state.refresh()
        except Exception:
            pass
        self._close_payment()

    def _on_cancel_item_from_panel(self, order_id: int, item: dict) -> None:
        """× на позиции внутри OrderPaymentPanel → CancelItemDialog (modal —
        нужна обязательная причина из справочника). После успешной отмены
        обновляем order в panel чтобы пересчитать subtotal/total."""
        from pos.screens.cancel_item_dialog import CancelItemDialog

        dlg = CancelItemDialog(
            order_id=order_id, item=item, client=self.state.client, parent=self,
        )
        dlg.item_cancelled.connect(self._on_item_cancelled)
        dlg.exec()

    def _on_item_cancelled(self, data: dict) -> None:
        """Backend вернул обновлённый order — синхронизируем panel + state."""
        from pos.widgets.order_payment_panel import OrderPaymentPanel
        order = data.get("data") if isinstance(data, dict) and "data" in data else data
        if isinstance(self._payment_widget, OrderPaymentPanel) and isinstance(order, dict):
            merged = {**self._payment_widget._order, **order}
            self._payment_widget.update_order(merged)
        try:
            self.state.refresh()
        except Exception:
            pass

    def _on_discount_applied(self, new_order: dict, table: dict | None) -> None:
        """Скидка применена — обновим order в текущей payment panel."""
        from pos.widgets.order_payment_panel import OrderPaymentPanel
        if isinstance(self._payment_widget, OrderPaymentPanel):
            merged = {**self._payment_widget._order, **new_order}
            self._payment_widget.update_order(merged)

    def _close_payment(self) -> None:
        """Вернуться к списку заказов. Чистим payment-widget, восстанавливаем
        размеры drawer'а и обычный border-style."""
        if self._payment_widget is not None:
            self._payment_layout.removeWidget(self._payment_widget)
            self._payment_widget.deleteLater()
            self._payment_widget = None
        # Восстанавливаем дефолтный 1px border-left (снимаем pre-bill accent).
        self.setStyleSheet(
            f"#ordersDrawer {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        # Список заказов тоже overlay — drawer всегда покрывает правый
        # сайдбар целиком, чтобы переходы между режимами были бесшовны.
        self.overlay_mode = True
        self._header_title.setText("Заказы")
        self.setFixedWidth(OrdersDrawer.PANEL_WIDTH)
        self.width_change_requested.emit(OrdersDrawer.PANEL_WIDTH)
        self._body_stack.setCurrentIndex(0)
        # Перерисовать список — оплаченный заказ должен пропасть из «Текущих»
        # (state.orders_changed обновится после refresh).
        self._closed_loaded = False
        self._render_list()

    def _on_payment_done(self, *args) -> None:
        """Оплата успешна — закрываем payment-view, refresh state.
        Принимает args для совместимости с разными сигналами
        (OrderPaymentPanel.order_closed(dict), legacy PaymentDialog.order_paid(dict, dict))."""
        try:
            self.state.refresh()
        except Exception:
            pass
        self._close_payment()

    def _on_payment_cancelled(self) -> None:
        """Кассир закрыл payment без оплаты — возврат к списку."""
        self._close_payment()

    def show_pre_bill(self, order: dict, table: dict | None) -> None:
        """Inline-режим пре-чека (тот же подход что show_payment) — PreBillDialog
        как embeddable widget в page 1 body_stack'а."""
        from PySide6.QtCore import Qt as _Qt
        from pos.screens.pre_bill_dialog import PreBillDialog

        if self._payment_widget is not None:
            self._payment_layout.removeWidget(self._payment_widget)
            self._payment_widget.deleteLater()
            self._payment_widget = None

        # Подсветить sidebar drawer'а как «pre-bill mode» — accent border-left.
        self.setStyleSheet(
            f"#ordersDrawer {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 4px solid {COLORS['accent_orange']};"
            f"}}"
        )
        # Пре-чек = ширина правой панели, перекрывает её полностью (overlay).
        self.overlay_mode = True

        dlg = PreBillDialog(
            order=order,
            table=table or {},
            client=self.state.client,
            parent=self._payment_holder,
            embedded=True,
        )
        dlg.setWindowFlags(_Qt.Widget)
        dlg.setModal(False)
        dlg.setMinimumWidth(0)
        dlg.setMaximumWidth(16777215)
        # Из пре-чека пользователь может нажать «Оплата» → переключаемся
        # на inline-payment в том же drawer'е.
        dlg.pay_requested.connect(
            lambda oid, o=order, t=table: self._switch_prebill_to_payment(o, t),
        )
        # Move/Split — Phase 4, в drawer'е пока не обрабатываем (просто
        # закроем pre-bill view, чтобы кассир видел список).
        dlg.move_requested.connect(lambda _oid: self._close_payment())
        dlg.split_requested.connect(lambda _oid: self._close_payment())
        dlg.rejected.connect(self._close_payment)

        self._payment_layout.addWidget(dlg)
        self._payment_widget = dlg
        self._header_title.setText(f"Пре-чек №{order.get('id', '')}")

        # Пре-чек = 360px (как OrderDetailPanel), полностью перекрывает её.
        self.setFixedWidth(OrdersDrawer.PRE_BILL_WIDTH)
        self.width_change_requested.emit(OrdersDrawer.PRE_BILL_WIDTH)
        self._body_stack.setCurrentIndex(1)

    def _switch_prebill_to_payment(self, order: dict, table: dict | None) -> None:
        """Пользователь нажал «Оплата» внутри пре-чека → swap view на payment.
        Payment теперь тот же 360px overlay+accent, что и pre-bill —
        переключение бесшовное, drawer-стиль не меняется."""
        self.show_payment(order, table)

    def _on_pre_bill_clicked(self, order: dict) -> None:
        """Клик «Пре-чек» в строке списка → inline PreBillDialog в drawer."""
        table_id = order.get("table")
        table = None
        if table_id:
            table = next(
                (t for t in self.state.tables if int(t["id"]) == int(table_id)),
                None,
            )
        self.show_pre_bill(order, table)

    def _on_pay_clicked(self, order: dict) -> None:
        """Клик «Оплатить» на строке → inline-payment в drawer (без модалки).
        Также эмитим pay_requested (для observability / резерв-flow), но host
        теперь делегирует оплату обратно в drawer через show_payment."""
        table_id = order.get("table")
        table = None
        if table_id:
            table = next(
                (t for t in self.state.tables if int(t["id"]) == int(table_id)),
                None,
            )
        self.pay_requested.emit(int(order.get("id") or 0))
        self.show_payment(order, table)

    def _on_header_close(self) -> None:
        """Крестик в header'е: в payment-режиме возвращает к списку, иначе
        закрывает весь drawer."""
        if self._body_stack.currentIndex() == 1:
            self._close_payment()
            return
        self.closed.emit()

    # -------- build --------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header (всегда виден, заголовок меняется в payment-режиме).
        # Высота 52px = высота основного POS topbar (TablesScreen._build_topbar),
        # чтобы drawer-header визуально стоял на одном уровне с топбаром POS.
        self._header = QFrame()
        header = self._header  # alias для legacy кода
        header.setObjectName("ordersDrawerHeader")
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"#ordersDrawerHeader {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 0, 12, 0)

        self._header_title = QLabel("Заказы")
        self._header_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 15pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        h.addWidget(self._header_title)
        h.addStretch(1)

        close_btn = QPushButton()
        close_btn.setFixedSize(36, 36)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close_btn.setIconSize(QSize(18, 18))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']};"
            f" border-radius: 6px; }}"
        )
        # Close-X: в payment-режиме возвращает к списку, иначе закрывает drawer.
        close_btn.clicked.connect(self._on_header_close)
        h.addWidget(close_btn)
        root.addWidget(header)

        # Body — QStackedWidget c 2 страницами: 0=list, 1=payment (inline).
        self._body_stack = QStackedWidget()
        root.addWidget(self._body_stack, 1)

        # Page 0: tabs + scrollable list.
        list_page = QWidget()
        lpv = QVBoxLayout(list_page)
        lpv.setContentsMargins(0, 0, 0, 0)
        lpv.setSpacing(0)

        tabs_bar = QFrame()
        tabs_bar.setFixedHeight(44)
        tabs_bar.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        tb = QHBoxLayout(tabs_bar)
        tb.setContentsMargins(8, 0, 8, 0)
        tb.setSpacing(0)

        self._tab_current = self._make_tab("Текущие", "current")
        self._tab_closed = self._make_tab("Закрытые сегодня", "closed_today")
        tb.addWidget(self._tab_current)
        tb.addWidget(self._tab_closed)
        tb.addStretch(1)
        lpv.addWidget(tabs_bar)

        self._list_holder = QWidget()
        self._list_holder.setStyleSheet(f"background: {COLORS['bg_white']};")
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_white']}; border: none; }}"
        )
        scroll.setWidget(self._list_holder)
        lpv.addWidget(scroll, 1)

        self._body_stack.addWidget(list_page)

        # Page 1: payment placeholder (содержимое подменяется в show_payment).
        self._payment_holder = QWidget()
        self._payment_holder.setStyleSheet(
            f"background: {COLORS['bg_white']};"
        )
        self._payment_layout = QVBoxLayout(self._payment_holder)
        self._payment_layout.setContentsMargins(0, 0, 0, 0)
        self._payment_layout.setSpacing(0)
        self._body_stack.addWidget(self._payment_holder)

        # Текущий embedded payment-виджет (для clean-up при close).
        self._payment_widget: QWidget | None = None
        # True когда drawer должен перекрывать всю правую sidebar.
        # Host (TablesScreen) использует флаг в _position_drawer чтобы
        # позиционировать y=0 / full-height. Drawer ВСЕГДА overlay в
        # текущем дизайне — список заказов / оплата / пре-чек все 360px.
        self.overlay_mode: bool = True

        self._render_tabs()
        self._render_list()

    def _make_tab(self, label: str, key: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFlat(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setProperty("tab_key", key)
        btn.clicked.connect(lambda _c=False, k=key: self._on_tab(k))
        return btn

    def _render_tabs(self) -> None:
        for btn in (self._tab_current, self._tab_closed):
            key = btn.property("tab_key")
            active = (key == self._active_tab)
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: transparent; border: none;"
                    f"  border-bottom: 2px solid {COLORS['accent_orange']};"
                    f"  color: {COLORS['accent_orange']};"
                    f"  font-size: 11pt; font-weight: 700;"
                    f"  padding: 8px 16px;"
                    f"}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: transparent; border: none;"
                    f"  color: {COLORS['text_secondary']};"
                    f"  font-size: 11pt; font-weight: 600;"
                    f"  padding: 8px 16px;"
                    f"}}"
                    f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
                )

    def _on_tab(self, key: str) -> None:
        if self._active_tab == key:
            return
        self._active_tab = key
        self._render_tabs()
        self._render_list()

    def _on_orders_changed(self, *_args) -> None:
        if self._active_tab == "current":
            self._render_list()

    # -------- rendering --------

    def _clear_list(self) -> None:
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _render_list(self) -> None:
        self._clear_list()
        if self._active_tab == "current":
            orders = [
                o for o in self.state.orders
                if o.get("status") in ("new", "bill_requested")
            ]
            self._render_orders(orders)
            return

        # closed_today: lazy fetch
        if not self._closed_loaded:
            self._fetch_closed_today()
        self._render_orders(self._closed_orders)

    def _fetch_closed_today(self) -> None:
        today_iso = date.today().isoformat()
        try:
            resp = self.state.client.get(
                "/orders/",
                params={
                    "status": "done,cancelled",
                    "date_from": today_iso,
                },
            )
        except ApiError:
            self._closed_orders = []
            self._closed_loaded = True
            return
        # resp может быть list (без paginator) или dict {results, count}
        if isinstance(resp, dict) and "results" in resp:
            self._closed_orders = list(resp.get("results") or [])
        elif isinstance(resp, list):
            self._closed_orders = resp
        else:
            self._closed_orders = []
        self._closed_loaded = True

    def _render_orders(self, orders: list[dict]) -> None:
        if not orders:
            empty = QLabel("Нет заказов")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
                f" font-style: italic; padding: 32px 0;"
                f" background: transparent; border: none;"
            )
            self._list_layout.addWidget(empty)
            return
        for o in orders:
            self._list_layout.addWidget(self._build_row(o))

    def _build_row(self, order: dict) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(8)

        # Левый столбец: №, стол/тип
        left = QWidget()
        left.setStyleSheet("background: transparent; border: none;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(2)

        oid = int(order.get("id") or 0)
        order_type = order.get("order_type") or "hall"
        table_id = order.get("table")
        if order_type == "hall" and table_id:
            # Для зала subtitle = «<zone_name> • <table_name>». Это критично
            # для ресторанов с несколькими зонами (Зал / Веранда / Куча …):
            # хардкод «Зал» путал бы кассира, если стол на самом деле в Веранде.
            # Источники по приоритету:
            # 1) `order.table_zone_name` — снапшот из backend OrderSerializer
            #    (всегда корректен, даже если стол потом перенесли в др. зону).
            # 2) `state.tables[*].zone_name` — fallback для активных заказов,
            #    если backend не вернул поле (old client cache, etc.).
            # 3) «Зал» — крайний fallback.
            table = next(
                (t for t in self.state.tables if int(t["id"]) == int(table_id)),
                None,
            )
            tname = (
                order.get("table_name")
                or (table or {}).get("name")
                or f"Стол {(table or {}).get('number', table_id)}"
            )
            zone_name = (
                order.get("table_zone_name")
                or (table or {}).get("zone_name")
                or "Зал"
            )
            subtitle = f"{zone_name} • {tname}"
        else:
            # Takeaway / delivery / hall без table_id — показываем тип заказа.
            type_lbl = {
                "takeaway": "С собой",
                "delivery": "Доставка",
            }.get(order_type, "Зал")
            subtitle = type_lbl

        num_lbl = QLabel(f"№{oid}")
        num_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        lv.addWidget(num_lbl)
        lv.addWidget(sub_lbl)
        h.addWidget(left, 1)

        # Сумма + время
        center = QWidget()
        center.setStyleSheet("background: transparent; border: none;")
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(2)
        total = order.get("total") or "0"
        total_lbl = QLabel(f"{total} TJS")
        total_lbl.setAlignment(Qt.AlignRight)
        total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        time_str = self._fmt_time(order.get("created_at"))
        time_lbl = QLabel(time_str)
        time_lbl.setAlignment(Qt.AlignRight)
        time_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        cv.addWidget(total_lbl)
        cv.addWidget(time_lbl)
        h.addWidget(center)

        # Actions
        status = order.get("status") or ""
        is_active = status in ("new", "bill_requested")

        if is_active:
            # Primary: «Оплатить» (orange) — открывает PaymentDialog в main.
            pay_btn = QPushButton("  Оплатить")
            pay_btn.setIcon(qicon("credit-card", COLORS["text_white"], 14))
            pay_btn.setIconSize(QSize(14, 14))
            pay_btn.setFixedHeight(32)
            pay_btn.setCursor(Qt.PointingHandCursor)
            pay_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 12px; font-size: 10pt; font-weight: 700;"
                f"}}"
                f"QPushButton:pressed {{ background: {COLORS['accent_orange_pressed']}; }}"
            )
            pay_btn.clicked.connect(
                lambda _c=False, o=order: self._on_pay_clicked(o),
            )
            h.addWidget(pay_btn)

            # Пре-чек — icon-only. Для активного заказа `reprint_receipt`
            # вернёт 422 (доступен только для DONE), поэтому используем
            # `print_pre_bill` — печатает пре-чек без смены статуса заказа.
            prebill_btn = QPushButton()
            prebill_btn.setIcon(qicon("printer", COLORS["text_primary"], 16))
            prebill_btn.setIconSize(QSize(16, 16))
            prebill_btn.setFixedSize(32, 32)
            prebill_btn.setToolTip("Пре-чек")
            prebill_btn.setCursor(Qt.PointingHandCursor)
            prebill_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            prebill_btn.clicked.connect(
                lambda _c=False, o=order: self._on_pre_bill_clicked(o),
            )
            h.addWidget(prebill_btn)
        elif status == "done":
            # Закрытые оплаченные: reprint чека работает.
            print_btn = QPushButton("  Печать")
            print_btn.setIcon(qicon("printer", COLORS["text_primary"], 14))
            print_btn.setIconSize(QSize(14, 14))
            print_btn.setFixedHeight(32)
            print_btn.setCursor(Qt.PointingHandCursor)
            print_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 10px; font-size: 10pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            print_btn.clicked.connect(
                lambda _c=False, oid=oid: self.reprint_requested.emit(oid),
            )
            h.addWidget(print_btn)
        else:
            # Отменённые: чек реально не печатался, reprint вернёт 422.
            # Показываем нейтральный бейдж «Отменён» вместо кнопки.
            cancelled_lbl = QLabel("Отменён")
            cancelled_lbl.setAlignment(Qt.AlignCenter)
            cancelled_lbl.setStyleSheet(
                f"QLabel {{"
                f"  background: {COLORS['bg_gray']};"
                f"  color: {COLORS['text_secondary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 6px 12px; font-size: 10pt; font-weight: 600;"
                f"}}"
            )
            h.addWidget(cancelled_lbl)
        return row

    @staticmethod
    def _fmt_time(iso: str | None) -> str:
        if not iso:
            return ""
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            # Локальное время кассира
            local = dt.astimezone()
            return local.strftime("%H:%M")
        except Exception:
            return str(iso)[:16].replace("T", " ")
