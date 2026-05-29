"""OrderPaymentPanel — restos-style оплата заказа inline в OrdersDrawer.

Дизайн взят 1:1 с `restos/components/dialogs/table-detail-sheet.tsx` —
single-column scrolling view с понятной иерархией: позиции → подытог →
К оплате → toggle Наличные/Безналичные → большой CTA «Закрыть и оплатить».

Заменяет embedded PaymentDialog (compact 2-column) который был тесным
для drawer'а 480px.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _CloseOrderWorker(QObject):
    """Worker для асинхронного POST /orders/{id}/close/ (как в PaymentDialog)."""

    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self,
        client: ApiClient,
        order_id: int,
        idem_key: str,
        payment_method: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.idem_key = idem_key
        self.payment_method = payment_method

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/orders/{self.order_id}/close/",
                json={"payment_method": self.payment_method},
                extra_headers={"Idempotency-Key": self.idem_key},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


# Backend знает 3 метода (cash/card/transfer). UI показывает 2 (как в restos):
# Наличные → cash, Безналичные → card (по умолчанию).
PAYMENT_METHODS = [
    ("cash", "Наличные", "banknote"),
    ("card", "Безналичные", "credit-card"),
]


class OrderPaymentPanel(QFrame):
    """Single-column оплата заказа (restos-style) для inline-режима в drawer."""

    # order_id + выбранный payment_method ("cash" | "card")
    pay_requested = Signal(int, str)
    pre_bill_requested = Signal(int)
    cancel_requested = Signal(int)
    discount_requested = Signal(int)
    split_requested = Signal(int)
    transfer_requested = Signal(int)
    # Отмена конкретной позиции — host (drawer) открывает CancelItemDialog.
    cancel_item_requested = Signal(int, dict)
    # Эмитится после успешного закрытия — host (drawer) свернёт view.
    order_closed = Signal(dict)

    def __init__(
        self,
        order: dict,
        table: dict | None,
        client: ApiClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._order = order
        self._table = table or {}
        self._client = client
        self._payment_method: str = ""
        self._method_buttons: dict[str, QPushButton] = {}
        self._idem_key = str(uuid.uuid4())
        self._thread: QThread | None = None
        self._worker: _CloseOrderWorker | None = None

        self.setObjectName("orderPaymentPanel")
        self.setStyleSheet(
            f"#orderPaymentPanel {{ background: {COLORS['bg_white']}; }}"
        )
        self._build()

    # -------- public --------

    def update_order(self, order: dict) -> None:
        """Перерисовать после изменения заказа (скидка применена и т.п.)."""
        self._order = order
        # Полная пересборка содержимого scrollable области.
        for i in reversed(range(self._content_layout.count())):
            item = self._content_layout.takeAt(i)
            w = item.widget()
            if w:
                w.deleteLater()
        self._populate_content()
        self._refresh_cta_label()

    # -------- build --------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scrollable content (header + items + totals + method + cta).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_white']}; border: none; }}"
        )

        content = QWidget()
        content.setStyleSheet(f"background: {COLORS['bg_white']};")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(12, 10, 12, 10)
        self._content_layout.setSpacing(8)
        self._content_layout.setAlignment(Qt.AlignTop)
        self._populate_content()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # Sticky footer: 2 secondary outline buttons + cancel link.
        footer = QFrame()
        footer.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(16, 10, 16, 12)
        fv.setSpacing(8)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        prebill_btn = self._outline_btn("Пре-чек", icon_name="printer")
        prebill_btn.clicked.connect(
            lambda: self.pre_bill_requested.emit(int(self._order.get("id") or 0)),
        )
        actions.addWidget(prebill_btn, 1)

        more_btn = self._outline_btn("Дополнительно", icon_name="more-horizontal")
        more_menu = QMenu(more_btn)
        more_menu.setStyleSheet(
            f"QMenu {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px; padding: 4px 0;"
            f"}}"
            f"QMenu::item {{"
            f"  padding: 8px 16px; color: {COLORS['text_primary']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QMenu::item:selected {{ background: {COLORS['bg_gray']}; }}"
        )
        act_discount = more_menu.addAction("Скидка")
        act_discount.triggered.connect(
            lambda: self.discount_requested.emit(int(self._order.get("id") or 0)),
        )
        act_split = more_menu.addAction("Разделить счёт")
        act_split.triggered.connect(
            lambda: self.split_requested.emit(int(self._order.get("id") or 0)),
        )
        act_transfer = more_menu.addAction("Перенести")
        act_transfer.triggered.connect(
            lambda: self.transfer_requested.emit(int(self._order.get("id") or 0)),
        )
        more_btn.setMenu(more_menu)
        actions.addWidget(more_btn, 1)

        fv.addLayout(actions)

        # «Отменить заказ» — red text-link под кнопками.
        cancel_link = QPushButton("Отменить заказ")
        cancel_link.setFlat(True)
        cancel_link.setCursor(Qt.PointingHandCursor)
        cancel_link.setFocusPolicy(Qt.NoFocus)
        cancel_link.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  border: none; padding: 4px 8px;"
            f"  font-size: 10pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ color: #B91C1C; }}"
        )
        cancel_link.clicked.connect(self._on_cancel_clicked)
        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        cancel_row.addWidget(cancel_link)
        cancel_row.addStretch(1)
        fv.addLayout(cancel_row)

        root.addWidget(footer)

    # -------- content --------

    def _populate_content(self) -> None:
        """Сборка scrollable content (header, items, totals, method, CTA)."""
        self._content_layout.addWidget(self._build_header_pill())
        self._content_layout.addWidget(self._build_items_list())
        self._content_layout.addWidget(self._build_totals_block())
        self._content_layout.addWidget(self._build_to_pay_box())
        self._content_layout.addWidget(self._build_methods_toggle())
        self._content_layout.addWidget(self._build_cta())

    def _build_header_pill(self) -> QWidget:
        """Стол N · K мест + статус-бейдж + waiter."""
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"  padding: 10px 12px;"
            f"}}"
        )
        v = QVBoxLayout(wrap)
        v.setContentsMargins(2, 0, 2, 0)
        v.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        order_type = self._order.get("order_type") or "hall"
        if order_type == "takeaway":
            title_text = "С собой"
        elif order_type == "delivery":
            title_text = "Доставка"
        else:
            table_name = self._table.get("name") or f"Стол {self._table.get('number', '?')}"
            guests = int(self._order.get("guests_count") or 0)
            if guests:
                title_text = f"{table_name} · {guests} {self._guests_word(guests)}"
            else:
                title_text = table_name

        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        top.addWidget(title)
        top.addStretch(1)

        # Status badge.
        status = (self._order.get("status") or "new").lower()
        badge_colors = {
            "new": ("#DBEAFE", COLORS["primary_blue"]),
            "bill_requested": ("#FEF3C7", COLORS["warning_yellow"]),
            "done": ("#D1FAE5", COLORS["success_green"]),
        }
        badge_label = {
            "new": "ГОТОВИТСЯ",
            "bill_requested": "СЧЁТ",
            "done": "ЗАКРЫТ",
        }
        bg, fg = badge_colors.get(status, ("#E2E8F0", COLORS["text_secondary"]))
        badge = QLabel(badge_label.get(status, status.upper()))
        badge.setStyleSheet(
            f"QLabel {{"
            f"  background: {bg}; color: {fg};"
            f"  border: none; border-radius: 9px;"
            f"  padding: 2px 10px;"
            f"  font-size: 9pt; font-weight: 700;"
            f"  letter-spacing: 0.5px;"
            f"}}"
        )
        top.addWidget(badge)
        v.addLayout(top)

        waiter_name = self._order.get("waiter_name") or "—"
        waiter = QLabel(f"Официант: {waiter_name}")
        waiter.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        v.addWidget(waiter)
        return wrap

    def _build_items_list(self) -> QWidget:
        """Список позиций — divide-y эмуляция через border-top на каждой row кроме первой."""
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        items = [
            it for it in (self._order.get("items") or [])
            if not it.get("cancelled_at")
        ]
        for i, it in enumerate(items):
            v.addWidget(self._build_item_row(it, is_first=(i == 0)))
        if not items:
            empty = QLabel("Нет позиций")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
                f" padding: 16px 0; background: transparent; border: none;"
            )
            v.addWidget(empty)
        return wrap

    def _build_item_row(self, item: dict, *, is_first: bool) -> QWidget:
        row = QFrame()
        border_top = (
            f"border-top: 1px solid {COLORS['border_light']};"
            if not is_first else "border-top: none;"
        )
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: transparent;"
            f"  border: none; {border_top}"
            f"  padding: 6px 10px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        qty = int(item.get("qty") or 1)
        name = item.get("name_at_order") or "?"
        title = QLabel(f"{qty}× {name}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt;"
            f" background: transparent; border: none;"
        )
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        h.addWidget(title, 1)

        sub = item.get("subtotal") or "0.00"
        currency = self._order.get("currency") or "TJS"
        amount = QLabel(f"{sub} {currency}")
        amount.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(amount)

        # × кнопка отмены позиции — есть только пока заказ не закрыт.
        status = (self._order.get("status") or "").lower()
        if status in ("new", "bill_requested"):
            cancel_btn = QPushButton("×")
            cancel_btn.setFixedSize(24, 24)
            cancel_btn.setCursor(Qt.PointingHandCursor)
            cancel_btn.setFocusPolicy(Qt.NoFocus)
            cancel_btn.setToolTip("Отменить позицию")
            cancel_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent;"
                f"  color: {COLORS['text_secondary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 12px;"
                f"  font-size: 12pt; font-weight: 700;"
                f"  padding: 0;"
                f"}}"
                f"QPushButton:hover {{"
                f"  color: {COLORS['danger_red']};"
                f"  border-color: {COLORS['danger_red']};"
                f"}}"
            )
            cancel_btn.clicked.connect(
                lambda _c=False, it=item: self.cancel_item_requested.emit(
                    int(self._order.get("id") or 0), it,
                ),
            )
            h.addWidget(cancel_btn)
        return row

    def _build_totals_block(self) -> QWidget:
        """Подытог + Обслуживание + (опц.) Скидка — серый блок."""
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_gray']};"
            f"  border: none; border-radius: {RADIUS['md']}px;"
            f"  padding: 10px 12px;"
            f"}}"
        )
        v = QVBoxLayout(wrap)
        v.setContentsMargins(2, 0, 2, 0)
        v.setSpacing(6)

        currency = self._order.get("currency") or "TJS"

        subtotal = self._order.get("subtotal") or "0.00"
        v.addLayout(self._kv_row("Подытог", f"{subtotal} {currency}"))

        service_amount = self._order.get("service_charge_amount") or "0.00"
        service_pct = self._order.get("service_charge_pct") or ""
        try:
            pct_val = float(service_pct)
        except (TypeError, ValueError):
            pct_val = 0
        svc_label = (
            f"Обслуживание ({pct_val:.0f}%)" if pct_val else "Обслуживание"
        )
        v.addLayout(self._kv_row(svc_label, f"+{service_amount} {currency}"))

        # Скидка — всегда видна. Если применена → −X.XX, иначе кликабельный «+ Скидка».
        discount_amount = self._order.get("discount_amount") or "0.00"
        if not self._is_zero(discount_amount):
            discount_name = self._order.get("discount_name") or "Скидка"
            v.addLayout(self._kv_row(
                discount_name, f"−{discount_amount} {currency}",
                accent=COLORS["danger_red"],
            ))
        else:
            add_disc_btn = QPushButton("+ Скидка")
            add_disc_btn.setFlat(True)
            add_disc_btn.setCursor(Qt.PointingHandCursor)
            add_disc_btn.setFocusPolicy(Qt.NoFocus)
            add_disc_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_secondary']};"
                f"  border: 1px dashed {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 4px 10px; font-size: 10pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ color: {COLORS['accent_orange']};"
                f" border-color: {COLORS['accent_orange']}; }}"
            )
            add_disc_btn.clicked.connect(
                lambda: self.discount_requested.emit(
                    int(self._order.get("id") or 0),
                ),
            )
            disc_row = QHBoxLayout()
            disc_row.setContentsMargins(0, 2, 0, 0)
            disc_row.addWidget(add_disc_btn)
            disc_row.addStretch(1)
            v.addLayout(disc_row)
        return wrap

    def _build_to_pay_box(self) -> QWidget:
        """К оплате — крупно, в primary-orange-tinted box."""
        wrap = QFrame()
        wrap.setStyleSheet(
            f"QFrame {{"
            f"  background: #FFF7ED;"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"}}"
        )
        h = QHBoxLayout(wrap)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(6)

        lbl = QLabel("К оплате")
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        h.addWidget(lbl)
        h.addStretch(1)

        currency = self._order.get("currency") or "TJS"
        total = self._order.get("total") or "0.00"
        amount = QLabel(f"{total} {currency}")
        amount.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 17pt; font-weight: 800;"
            f" background: transparent; border: none;"
        )
        amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(amount)
        return wrap

    def _build_methods_toggle(self) -> QWidget:
        """Segmented toggle: Наличные / Безналичные (2 кнопки, 50/50)."""
        wrap = QFrame()
        wrap.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self._method_buttons = {}
        for code, label, icon_name in PAYMENT_METHODS:
            btn = QPushButton(f"  {label}")
            btn.setIcon(qicon(icon_name, COLORS["text_primary"], 16))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda _c=False, m=code: self._on_method_clicked(m),
            )
            self._method_buttons[code] = btn
            self._restyle_method_button(btn, active=False)
            h.addWidget(btn, 1)
        return wrap

    def _restyle_method_button(self, btn: QPushButton, *, active: bool) -> None:
        if active:
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: #FFF7ED;"
                f"  color: {COLORS['accent_orange']};"
                f"  border: 2px solid {COLORS['accent_orange']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"  text-align: center;"
                f"}}"
            )
            btn.setIcon(qicon(self._icon_for_method(btn), COLORS["accent_orange"], 16))
        else:
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 2px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  font-size: 11pt; font-weight: 600;"
                f"  text-align: center;"
                f"}}"
                f"QPushButton:hover {{ border-color: {COLORS['text_secondary']}; }}"
            )
            btn.setIcon(qicon(self._icon_for_method(btn), COLORS["text_primary"], 16))

    def _icon_for_method(self, btn: QPushButton) -> str:
        for code, btn_ref in self._method_buttons.items():
            if btn_ref is btn:
                for code2, _, icon in PAYMENT_METHODS:
                    if code2 == code:
                        return icon
        return "credit-card"

    def _build_cta(self) -> QWidget:
        """Закрыть и оплатить · X.XX TJS — full-width orange CTA."""
        self._cta_btn = QPushButton()
        self._cta_btn.setFixedHeight(44)
        self._cta_btn.setCursor(Qt.PointingHandCursor)
        self._cta_btn.setFocusPolicy(Qt.NoFocus)
        self._cta_btn.setEnabled(False)
        self._cta_btn.setIcon(qicon("credit-card", COLORS["text_white"], 16))
        self._cta_btn.setIconSize(QSize(16, 16))
        self._cta_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"  padding: 0 10px;"
            f"}}"
            f"QPushButton:pressed {{ background-color: {COLORS['accent_orange_pressed']}; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._cta_btn.clicked.connect(self._on_cta_clicked)
        self._refresh_cta_label()
        return self._cta_btn

    def _refresh_cta_label(self) -> None:
        currency = self._order.get("currency") or "TJS"
        total = self._order.get("total") or "0.00"
        self._cta_btn.setText(f"  Закрыть и оплатить · {total} {currency}")

    # -------- helpers --------

    def _kv_row(self, label: str, value: str, *, accent: str | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" background: transparent; border: none;"
        )
        v = QLabel(value)
        v.setStyleSheet(
            f"color: {accent or COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(l)
        row.addStretch(1)
        row.addWidget(v)
        return row

    def _outline_btn(self, label: str, *, icon_name: str | None = None) -> QPushButton:
        btn = QPushButton(f"  {label}" if icon_name else label)
        btn.setFixedHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        if icon_name:
            btn.setIcon(qicon(icon_name, COLORS["text_primary"], 14))
            btn.setIconSize(QSize(14, 14))
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 10px; font-size: 10pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ border-color: {COLORS['text_secondary']}; }}"
        )
        return btn

    @staticmethod
    def _is_zero(s) -> bool:
        return s in (None, "", "0", "0.00", "0.0")

    @staticmethod
    def _guests_word(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return "гость"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "гостя"
        return "гостей"

    # -------- handlers --------

    def _on_method_clicked(self, method: str) -> None:
        self._payment_method = method
        for code, btn in self._method_buttons.items():
            self._restyle_method_button(btn, active=(code == method))
        self._cta_btn.setEnabled(True)

    def _on_cta_clicked(self) -> None:
        if not self._payment_method:
            return
        if self._thread is not None:
            return
        order_id = int(self._order.get("id") or 0)
        self.pay_requested.emit(order_id, self._payment_method)

        # Disable CTA на время запроса.
        self._cta_btn.setEnabled(False)
        self._cta_btn.setText("Закрываю заказ…")

        thread = QThread(self)
        worker = _CloseOrderWorker(
            self._client, order_id, self._idem_key, self._payment_method,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_close_success)
        worker.error.connect(self._on_close_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_close_success(self, data: dict) -> None:
        self._thread = None
        self._worker = None
        payload = data.get("data") if isinstance(data, dict) and "data" in data else data
        self.order_closed.emit(payload if isinstance(payload, dict) else {})

    def _on_close_error(self, exc: ApiError) -> None:
        self._thread = None
        self._worker = None
        self._cta_btn.setEnabled(True)
        self._refresh_cta_label()
        QMessageBox.warning(
            self, "Ошибка оплаты", f"Не удалось закрыть заказ: {exc.message}",
        )

    def _on_cancel_clicked(self) -> None:
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Отменить заказ")
        confirm.setText(
            f"Отменить заказ №{self._order.get('id', '')}?\n"
            "Действие нельзя отменить."
        )
        confirm.setIcon(QMessageBox.Question)
        yes = confirm.addButton("Отменить заказ", QMessageBox.YesRole)
        confirm.addButton("Не отменять", QMessageBox.NoRole)
        confirm.exec()
        if confirm.clickedButton() == yes:
            self.cancel_requested.emit(int(self._order.get("id") or 0))
