"""Пре-чек — frame "5. Пре-чек" (id=eDfRu) в design/pos_cashier.pen.

Модалка с деталями заказа и 4 кнопками действий:
- Печать пре-чека (синяя) — POST /orders/{id}/print_pre_bill/, статус заказа не меняется
- Разделить счёт (оранжевая) — Phase 4 (disabled)
- Перенести (white outline) — Phase 4 (disabled)
- Оплата (зелёная) — emit pay_requested → main открывает PaymentDialog

MVP-cut от дизайна:
- Обслуживание 12% (Phase 4)
- «Оплата без чека» link (Phase 4)
"""
from datetime import datetime

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _PrePrintWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, order_id: int) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/orders/{self.order_id}/print_pre_bill/",
                json={},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class PreBillDialog(QDialog):
    """Сигналы:
        pay_requested(order_id) — кликнули «Оплата» → main открывает PaymentDialog
        move_requested(order_id) — Phase 4 «Перенести» (disabled пока)
        split_requested(order_id) — Phase 4 «Разделить»
    """

    pay_requested = Signal(int)
    move_requested = Signal(int)
    split_requested = Signal(int)

    def __init__(
        self,
        order: dict,
        table: dict | None,
        client: ApiClient,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._order = order
        self._table = table or {}
        self._client = client
        self._embedded = bool(embedded)
        self._thread: QThread | None = None
        self._worker: _PrePrintWorker | None = None

        self.setWindowTitle("Пре-чек")
        self.setModal(True)
        if not self._embedded:
            self.setFixedWidth(500)
        self._build()

    # -------- build --------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header пропускаем в embedded-режиме — host рисует свой.
        if not self._embedded:
            outer.addWidget(self._build_header())
        # Body: компактный receipt-style для embedded, обычный для modal.
        if self._embedded:
            outer.addWidget(self._build_body_compact(), 1)
        else:
            outer.addWidget(self._build_body(), 1)

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)

        title = QLabel("Пре-чек")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        layout.addWidget(title)
        layout.addStretch(1)

        close_btn = QPushButton()
        close_btn.setFlat(True)
        close_btn.setFixedSize(32, 32)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close_btn.setIconSize(QSize(18, 18))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; border-radius: 4px; }}"
        )
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)
        return h

    def _build_body_compact(self) -> QWidget:
        """Receipt-paper preview (restos-style): центрированная «бумажная»
        карточка чека на light-gray фоне, как на printed-чеке. Снизу 2
        кнопки — «Печать чека» (orange) + «Назад» (outline).
        """
        from PySide6.QtGui import QFont

        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_gray']};")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        outer.setAlignment(Qt.AlignTop)

        # ===== Бумажная карточка (на всю ширину drawer'а) =====
        card = QFrame()
        card.setObjectName("receiptCard")
        card.setStyleSheet(
            f"#receiptCard {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"}}"
        )
        try:
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            from PySide6.QtGui import QColor
            shadow = QGraphicsDropShadowEffect(card)
            shadow.setBlurRadius(24)
            shadow.setXOffset(0)
            shadow.setYOffset(2)
            shadow.setColor(QColor(0, 0, 0, 35))
            card.setGraphicsEffect(shadow)
        except Exception:
            pass

        c = QVBoxLayout(card)
        c.setContentsMargins(28, 24, 28, 24)
        c.setSpacing(4)

        # Чек крупнее — moncpace 12pt (было 10pt).
        mono = QFont("Menlo, Consolas, monospace", 12)
        mono.setStyleHint(QFont.Monospace)
        mono_bold = QFont(mono)
        mono_bold.setBold(True)

        # --- Restaurant header (centered) ---
        rest_name = (
            self._order.get("restaurant_name")
            or getattr(self._client, "_restaurant_name", None)
            or "RestOS"
        )
        head = QLabel(rest_name)
        head.setFont(mono_bold)
        head.setAlignment(Qt.AlignCenter)
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 15pt; font-weight: 800;"
            f" background: transparent; border: none;"
        )
        c.addWidget(head)

        rest_addr = self._order.get("restaurant_address") or ""
        if rest_addr:
            addr = QLabel(rest_addr)
            addr.setFont(mono)
            addr.setAlignment(Qt.AlignCenter)
            addr.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
                f" background: transparent; border: none;"
            )
            c.addWidget(addr)

        # --- ПРЕДВАРИТЕЛЬНЫЙ СЧЁТ (centered, after small gap) ---
        c.addSpacing(10)
        title_lbl = QLabel("ПРЕДВАРИТЕЛЬНЫЙ СЧЁТ")
        title_lbl.setFont(mono_bold)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 800;"
            f" background: transparent; border: none;"
        )
        c.addWidget(title_lbl)
        c.addSpacing(10)

        # --- Info rows: Чек № / Дата / Зал / Гостей / Кассир ---
        oid = self._order.get("id", "—")
        c.addLayout(self._receipt_row("Чек №", f"#{oid}", mono))

        time_str, date_str = self._fmt_dt(
            self._order.get("created_at") or self._order.get("updated_at")
        )
        c.addLayout(self._receipt_row("Дата", f"{date_str} {time_str}", mono))

        # Зал / тип
        order_type = self._order.get("order_type") or "hall"
        if order_type == "takeaway":
            zone_value = "С собой"
        elif order_type == "delivery":
            zone_value = "Доставка"
        else:
            zone_value = (
                self._table.get("zone_name")
                or self._order.get("table_zone_name")
                or "Зал"
            )
        c.addLayout(self._receipt_row("Зал", zone_value, mono))

        guests = int(self._order.get("guests_count") or 0)
        if guests:
            c.addLayout(self._receipt_row("Гостей", str(guests), mono))

        cashier = (
            self._order.get("cashier_name")
            or self._order.get("waiter_name")
            or "—"
        )
        c.addLayout(self._receipt_row("Кассир", cashier, mono))

        c.addSpacing(8)

        # --- Header: Наименование / Сумма ---
        c.addLayout(self._receipt_row(
            "Наименование", "Сумма", mono, label_accent=COLORS["text_secondary"],
            value_accent=COLORS["text_secondary"],
        ))

        # --- Items ---
        items = [
            it for it in (self._order.get("items") or [])
            if not it.get("cancelled_at")
        ]
        currency = self._order.get("currency") or "TJS"
        for it in items:
            qty = int(it.get("qty") or 1)
            name = it.get("name_at_order") or "?"
            sub = it.get("subtotal") or "0.00"
            label = f"{name} ×{qty}" if qty > 1 else f"{name} ×1"
            c.addLayout(self._receipt_row(label, f"{sub} {currency}", mono))

        c.addSpacing(8)

        # --- Подытог / Обслуживание / Скидка ---
        subtotal = self._order.get("subtotal") or "0.00"
        c.addLayout(self._receipt_row(
            "Подитог", f"{subtotal} {currency}", mono,
        ))

        service_amount = self._order.get("service_charge_amount") or "0.00"
        service_pct = self._order.get("service_charge_pct") or ""
        try:
            pct_val = float(service_pct)
        except (TypeError, ValueError):
            pct_val = 0
        svc_label = (
            f"Обслуживание ({pct_val:.0f}%)" if pct_val else "Обслуживание"
        )
        c.addLayout(self._receipt_row(
            svc_label, f"{service_amount} {currency}", mono,
        ))

        discount_amount = self._order.get("discount_amount") or "0.00"
        if not self._is_zero(discount_amount):
            discount_name = self._order.get("discount_name") or "Скидка"
            c.addLayout(self._receipt_row(
                discount_name, f"−{discount_amount} {currency}", mono,
                value_accent=COLORS["danger_red"],
            ))

        # --- ИТОГО (большой) ---
        c.addSpacing(10)
        total_row = QHBoxLayout()
        total_row.setContentsMargins(0, 0, 0, 0)
        total_lbl = QLabel("ИТОГО")
        total_lbl.setFont(mono_bold)
        total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 19pt; font-weight: 800;"
            f" background: transparent; border: none;"
        )
        total_val = QLabel(f"{self._order.get('total', '0.00')} {currency}")
        total_val.setFont(mono_bold)
        total_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_val.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 19pt; font-weight: 800;"
            f" background: transparent; border: none;"
        )
        total_row.addWidget(total_lbl)
        total_row.addStretch(1)
        total_row.addWidget(total_val)
        c.addLayout(total_row)

        c.addSpacing(12)

        # --- Footer notes ---
        footer1 = QLabel("Не является фискальным документом")
        footer1.setFont(mono)
        footer1.setAlignment(Qt.AlignCenter)
        footer1.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        footer2 = QLabel("Powered by RestOS")
        footer2.setFont(mono)
        footer2.setAlignment(Qt.AlignCenter)
        footer2.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        c.addWidget(footer1)
        c.addWidget(footer2)

        # Карточка на ВСЮ ширину drawer'а (без боковых stretch'ей).
        outer.addWidget(card)
        outer.addStretch(1)

        # ===== Action buttons (внизу drawer'а) =====
        actions = QVBoxLayout()
        actions.setSpacing(8)

        from PySide6.QtCore import QSize
        from pos.resources.icons import qicon

        self._print_btn = QPushButton("  Печать чека")
        self._print_btn.setIcon(qicon("printer", COLORS["text_white"], 16))
        self._print_btn.setIconSize(QSize(16, 16))
        self._print_btn.setFixedHeight(44)
        self._print_btn.setCursor(Qt.PointingHandCursor)
        self._print_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background: {COLORS['accent_orange_pressed']}; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._print_btn.clicked.connect(self._on_print_pre_bill)
        actions.addWidget(self._print_btn)

        back_btn = QPushButton("Назад")
        back_btn.setFixedHeight(44)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        back_btn.clicked.connect(self.reject)
        actions.addWidget(back_btn)

        outer.addLayout(actions)
        return body

    def _receipt_row(
        self,
        label: str,
        value: str,
        mono_font,
        *,
        label_accent: str | None = None,
        value_accent: str | None = None,
    ) -> QHBoxLayout:
        """Строка чека: label слева, value справа, mono-выравнивание."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        l = QLabel(label)
        l.setFont(mono_font)
        l.setStyleSheet(
            f"color: {label_accent or COLORS['text_primary']}; font-size: 12pt;"
            f" background: transparent; border: none;"
        )
        v = QLabel(value)
        v.setFont(mono_font)
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        v.setStyleSheet(
            f"color: {value_accent or COLORS['text_primary']}; font-size: 12pt;"
            f" background: transparent; border: none;"
        )
        row.addWidget(l)
        row.addStretch(1)
        row.addWidget(v)
        return row

    def _mono_kv(self, label: str, value: str, mono_font, *, accent: str | None = None):
        """Хелпер: monospace label-value row для compact-receipt."""
        from PySide6.QtCore import Qt as _Qt
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setFont(mono_font)
        l.setStyleSheet(
            f"color: {accent or COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        r = QLabel(value)
        r.setFont(mono_font)
        r.setAlignment(_Qt.AlignRight | _Qt.AlignVCenter)
        r.setStyleSheet(
            f"color: {accent or COLORS['text_primary']}; font-size: 10pt;"
            f" font-weight: 600; background: transparent; border: none;"
        )
        row.addWidget(l)
        row.addStretch(1)
        row.addWidget(r)
        return row

    def _dashed(self) -> QFrame:
        """Receipt-style dashed separator (1px тонкий пунктир)."""
        s = QFrame()
        s.setFixedHeight(1)
        s.setStyleSheet(
            f"border: none; border-top: 1px dashed {COLORS['border_light']};"
            f" background: transparent; margin: 4px 0;"
        )
        return s

    def _build_body(self) -> QWidget:
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        v = QVBoxLayout(body)
        v.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        v.setSpacing(SPACING["sm"])

        # Info row: стол + officant | время + дата
        info_row = self._build_info_row()
        v.addWidget(info_row)

        v.addWidget(self._sep())

        # Items
        items = [it for it in (self._order.get("items") or []) if not it.get("cancelled_at")]
        for it in items:
            v.addWidget(self._build_item_row(it))

        v.addWidget(self._sep())

        # Подитог / Скидка / Обслуживание / Чаевые — те же поля, что и в чеке.
        # Скидка и Обслуживание ВСЕГДА видны (даже когда значение 0), чтобы
        # кассир чётко видел структуру итога.
        currency = self._order.get("currency") or "TJS"
        subtotal = self._order.get("subtotal") or "0.00"
        v.addWidget(self._build_kv_row("Подитог", f"{subtotal} {currency}"))

        discount_amount = self._order.get("discount_amount") or "0.00"
        discount_name = self._order.get("discount_name") or "Скидка"
        v.addWidget(self._build_kv_row(
            discount_name, f"−{discount_amount} {currency}",
        ))

        service_amount = self._order.get("service_charge_amount") or "0.00"
        service_pct = self._order.get("service_charge_pct") or ""
        try:
            pct_val = float(service_pct)
        except (TypeError, ValueError):
            pct_val = 0
        svc_label = (
            f"Обслуживание ({pct_val:.0f}%)" if pct_val
            else "Обслуживание"
        )
        v.addWidget(self._build_kv_row(
            svc_label, f"+{service_amount} {currency}",
        ))

        tip_amount = self._order.get("tip_amount") or "0.00"
        if not self._is_zero(tip_amount):
            v.addWidget(self._build_kv_row(
                "Чаевые", f"+{tip_amount} {currency}",
            ))

        v.addWidget(self._sep())

        # ИТОГО large
        total_row = QHBoxLayout()
        total_lbl = QLabel("Итого")
        total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        total_val = QLabel(
            f"{self._order.get('total', '0.00')} {self._order.get('currency', 'TJS')}"
        )
        total_val.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 22pt; font-weight: 800;"
        )
        total_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_row.addWidget(total_lbl)
        total_row.addStretch(1)
        total_row.addWidget(total_val)
        v.addLayout(total_row)

        v.addWidget(self._sep())

        # Buttons grid 2x2
        v.addLayout(self._build_buttons())
        return body

    def _build_info_row(self) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.setSpacing(2)
        table_name = self._table.get("name") or f"Стол {self._table.get('number', '?')}"
        if self._order.get("order_type") == "takeaway":
            table_name = "С собой"
        elif self._order.get("order_type") == "delivery":
            table_name = "Доставка"
        title = QLabel(table_name)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 700;"
        )
        waiter = QLabel(f"Официант: {self._order.get('waiter_name', '—')}")
        waiter.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        left.addWidget(title)
        left.addWidget(waiter)
        h.addLayout(left)
        h.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setAlignment(Qt.AlignRight)
        time_str, date_str = self._fmt_dt(
            self._order.get("created_at") or self._order.get("updated_at")
        )
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 700;"
        )
        time_lbl.setAlignment(Qt.AlignRight)
        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        date_lbl.setAlignment(Qt.AlignRight)
        right.addWidget(time_lbl)
        right.addWidget(date_lbl)
        h.addLayout(right)
        return row

    def _build_item_row(self, item: dict) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        qty = int(item.get("qty") or 1)
        name = item.get("name_at_order") or "?"
        title = QLabel(f"{qty} × {name}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt;"
        )
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        sub = item.get("subtotal") or "0.00"
        amount = QLabel(str(sub))
        amount.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 600;"
        )
        amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h.addWidget(title, 1)
        h.addWidget(amount)
        return row

    def _build_kv_row(self, label: str, value: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11pt;")
        v = QLabel(value)
        v.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11pt;")
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(l)
        h.addStretch(1)
        h.addWidget(v)
        return row

    @staticmethod
    def _is_zero(s) -> bool:
        """Совпадает с logic в [printing/templates/receipt.py::_is_zero]."""
        return s in (None, "", "0", "0.00", "0.0")

    def _sep(self) -> QFrame:
        s = QFrame()
        s.setFixedHeight(1)
        s.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        return s

    def _build_buttons(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(SPACING["sm"])

        # Row 1: Печать (blue) + Разделить (orange)
        r1 = QHBoxLayout()
        r1.setSpacing(SPACING["sm"])

        self._print_btn = QPushButton(" Печать пре-чека")
        self._print_btn.setIcon(qicon("printer", COLORS["text_white"], 16))
        self._print_btn.setIconSize(QSize(16, 16))
        self._print_btn.setFixedHeight(52)
        self._print_btn.setCursor(Qt.PointingHandCursor)
        self._print_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['primary_blue']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background: #1D4ED8; }}"
            f"QPushButton:disabled {{ background: {COLORS['border_light']}; color: {COLORS['text_secondary']}; }}"
        )
        self._print_btn.clicked.connect(self._on_print_pre_bill)

        split_btn = QPushButton(" Разделить счёт")
        split_btn.setFixedHeight(52)
        split_btn.setCursor(Qt.PointingHandCursor)
        split_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        split_btn.clicked.connect(self._on_split)

        r1.addWidget(self._print_btn, 1)
        r1.addWidget(split_btn, 1)
        v.addLayout(r1)

        # Row 2: Перенести (outline) + Оплата (green)
        r2 = QHBoxLayout()
        r2.setSpacing(SPACING["sm"])

        move_btn = QPushButton(" Перенести")
        is_hall = self._order.get("order_type", "hall") == "hall"
        move_btn.setEnabled(is_hall)
        move_btn.setToolTip(
            "Перенос на другой стол" if is_hall
            else "Перенос только для заказов в зале"
        )
        move_btn.setFixedHeight(52)
        move_btn.setCursor(Qt.PointingHandCursor)
        move_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        move_btn.clicked.connect(self._on_move)

        pay_btn = QPushButton("Оплата")
        pay_btn.setFixedHeight(52)
        pay_btn.setCursor(Qt.PointingHandCursor)
        pay_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background: #15803D; }}"
        )
        pay_btn.clicked.connect(self._on_pay)

        r2.addWidget(move_btn, 1)
        r2.addWidget(pay_btn, 1)
        v.addLayout(r2)

        return v

    # -------- handlers --------

    def _on_print_pre_bill(self) -> None:
        if self._thread is not None:
            return
        self._print_btn.setEnabled(False)
        self._print_btn.setText("Печатается…")

        thread = QThread(self)
        worker = _PrePrintWorker(self._client, int(self._order["id"]))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_print_success)
        worker.error.connect(self._on_print_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_print_success(self, _data: dict) -> None:
        self._thread = None
        self._worker = None
        self._print_btn.setText(" ✓ Отправлено в очередь")
        # 2 секунды показываем успех, потом возвращаем default state
        from PySide6.QtCore import QTimer

        QTimer.singleShot(2000, self._reset_print_btn)

    def _reset_print_btn(self) -> None:
        self._print_btn.setText(" Печать пре-чека")
        self._print_btn.setEnabled(True)

    def _on_print_error(self, exc: ApiError) -> None:
        self._thread = None
        self._worker = None
        QMessageBox.warning(self, "Ошибка", f"{exc.message}\n[{exc.code}]")
        self._reset_print_btn()

    def _on_pay(self) -> None:
        self.pay_requested.emit(int(self._order["id"]))
        self.accept()

    def _on_move(self) -> None:
        self.move_requested.emit(int(self._order["id"]))
        self.accept()

    def _on_split(self) -> None:
        self.split_requested.emit(int(self._order["id"]))
        self.accept()

    @staticmethod
    def _fmt_dt(iso: str | None) -> tuple[str, str]:
        if not iso:
            return "—", "—"
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%H:%M"), dt.strftime("%d.%m.%Y")
        except Exception:
            return "—", "—"
