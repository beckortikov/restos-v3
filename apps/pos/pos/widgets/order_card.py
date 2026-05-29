"""Карточка активного заказа. Frame: order card o1/o2 в "10. Активные заказы" в pos_cashier.pen."""
from datetime import datetime
from datetime import timezone as tz

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING

DUSHANBE = tz.utc  # PRD: время храним в UTC, на клиенте показываем локально

# По дизайну левая полоса 4px различает тип заказа.
# В MVP backend знает только "Зал" (table FK обязателен) — остальные типы
# (С собой / Доставка) добавятся в Phase 8.
TYPE_BORDER_COLOR = {
    "hall": COLORS["accent_orange"],
    "takeaway": COLORS["success_green"],
    "delivery": COLORS["primary_blue"],
}
TYPE_LABEL = {
    "hall": "Зал",
    "takeaway": "С собой",
    "delivery": "Доставка",
}

# Карточка с разным border-left в зависимости от типа.
def _card_qss(type_color: str) -> str:
    return (
        f"#orderCard {{"
        f"  background-color: {COLORS['bg_white']};"
        f"  border: 1px solid {COLORS['border_light']};"
        f"  border-left: 4px solid {type_color};"
        f"  border-radius: {RADIUS['sm']}px;"
        f"}}"
    )


class OrderCard(QFrame):
    """Frame: o1/o2 в design — vertical layout с header, items, footer, кнопками."""

    pay_clicked = Signal(int)
    cancel_clicked = Signal(int)
    clicked = Signal(int)

    MIN_WIDTH = 240
    MIN_HEIGHT = 200

    def __init__(self, order: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("orderCard")
        self._order_id: int = int(order["id"])
        self._order_type: str = order.get("order_type", "hall")  # MVP: всегда "hall"

        type_color = TYPE_BORDER_COLOR.get(self._order_type, COLORS["accent_orange"])
        self.setStyleSheet(_card_qss(type_color))

        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)

        self._build(order)

    def _build(self, order: dict) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(SPACING["sm"])

        v.addLayout(self._build_header(order))
        v.addWidget(self._build_table_line(order))
        v.addWidget(self._build_items_line(order))
        v.addStretch(1)
        v.addWidget(self._build_footer(order))
        v.addLayout(self._build_buttons(order))

    def _build_header(self, order: dict) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        num = QLabel(f"#{order['id']}")
        num.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none;"
        )

        type_color = TYPE_BORDER_COLOR.get(self._order_type, COLORS["accent_orange"])
        type_lbl = TYPE_LABEL.get(self._order_type, "Зал")
        badge = QLabel(type_lbl)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {type_color}; color: {COLORS['text_white']};"
            f" border-radius: 10px; padding: 3px 8px;"
            f" font-size: 10pt; font-weight: 700;"
        )

        time_text = self._format_time(order.get("created_at"))
        time_lbl = QLabel(time_text)
        time_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; border: none;"
        )

        h.addWidget(num)
        h.addWidget(badge)
        h.addStretch(1)
        h.addWidget(time_lbl)
        return h

    def _build_table_line(self, order: dict) -> QLabel:
        # Зал: «Стол 5 • 4 гостя»
        # С собой: «С собой • {customer_name}» (phone опционально)
        # Доставка: «Доставка • {customer_name}» (address как 2-я строка опционально)
        parts: list[str] = []
        if self._order_type == "hall":
            table_name = order.get("table_name") or ""
            guests = int(order.get("guests_count") or 0)
            if table_name:
                parts.append(table_name)
            if guests:
                parts.append(f"{guests} {self._guests_word(guests)}")
        else:
            type_label = TYPE_LABEL.get(self._order_type, "Заказ")
            parts.append(type_label)
            customer = (order.get("customer_name") or "").strip()
            if customer:
                parts.append(customer)
            elif order.get("customer_phone"):
                parts.append(order["customer_phone"])

        text = " • ".join(parts) if parts else ""

        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; border: none;"
        )
        return lbl

    def _build_items_line(self, order: dict) -> QLabel:
        items = order.get("items") or []
        active = [it for it in items if not it.get("cancelled_at")]
        parts: list[str] = []
        for it in active:
            name = it.get("name_at_order") or "?"
            qty = int(it.get("qty") or 1)
            parts.append(f"{name} ×{qty}" if qty > 1 else name)
        text = ", ".join(parts) if parts else "—"

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; line-height: 140%;"
        )
        return lbl

    def _build_footer(self, order: dict) -> QWidget:
        f = QWidget()
        f.setStyleSheet(
            f"background-color: transparent;"
            f" border: none; border-top: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(0, 6, 0, 0)
        h.setSpacing(SPACING["sm"])

        # Подсветка статуса bill_requested — слева снизу, контрастно
        status = order.get("status", "new")
        if status == "bill_requested":
            badge = QLabel("Счёт")
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"background-color: {COLORS['danger_red']};"
                f" color: {COLORS['text_white']};"
                f" border-radius: 4px; padding: 2px 8px;"
                f" font-size: 9pt; font-weight: 700;"
            )
            h.addWidget(badge)
        else:
            waiter = order.get("waiter_name") or "—"
            wlbl = QLabel(waiter)
            wlbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 10pt; border: none;"
            )
            h.addWidget(wlbl)

        h.addStretch(1)

        total = order.get("total") or "0.00"
        currency = order.get("currency") or "TJS"
        total_lbl = QLabel(f"{total} {currency}")
        total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 15pt; font-weight: 700;"
            f" border: none;"
        )
        h.addWidget(total_lbl)
        return f

    def _build_buttons(self, _order: dict) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        pay = QPushButton("Оплатить")
        pay.setFixedHeight(28)
        pay.setCursor(Qt.PointingHandCursor)
        pay.setFocusPolicy(Qt.NoFocus)
        pay.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 6px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:pressed {{ background-color: #15803D; }}"
        )
        pay.clicked.connect(lambda: self.pay_clicked.emit(self._order_id))

        cancel = QPushButton("Закрыть")
        cancel.setFixedHeight(28)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFocusPolicy(Qt.NoFocus)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: #FFF7ED;"
            f"  color: {COLORS['accent_orange']};"
            f"  border: 1px solid {COLORS['accent_orange']};"
            f"  border-radius: 6px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:pressed {{ background-color: #FED7AA; }}"
        )
        cancel.clicked.connect(lambda: self.cancel_clicked.emit(self._order_id))

        h.addWidget(pay, 1)
        h.addWidget(cancel, 1)
        return h

    @staticmethod
    def _format_time(iso: str | None) -> str:
        if not iso:
            return ""
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M")
        except Exception:
            return ""

    @staticmethod
    def _guests_word(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return "гость"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "гостя"
        return "гостей"

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._order_id)
        super().mousePressEvent(event)
