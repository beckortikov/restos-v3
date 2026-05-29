"""Экран 5a. Оплата заказа — frame "9. Оплата заказа" (id=SaCxK) в design/pos_cashier.pen.

Модалка 720×auto над Tables/ActiveOrders:
- Левая колонка: краткая сводка заказа (стол, позиции, ИТОГО)
- Правая колонка: выбор способа оплаты (Наличные / Карта / Перевод)
- Футер: «ОПЛАТИТЬ И ПЕЧАТЬ ЧЕК →»

MVP-cut от дизайна:
- Подытог / Скидка / Обслуживание — Phase 4
- Смешанная оплата + поля Получено/Сдача — Phase 4
- QR (отдельный способ) — Phase 4 (у нас бэкенд знает cash/card/transfer)
- «Оплата без чека» — Phase 4
"""
import uuid
from decimal import Decimal

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING


PAYMENT_METHODS = [
    ("cash", "Наличные", COLORS["success_green"], "#15803D"),
    ("card", "Карта", COLORS["primary_blue"], "#1D4ED8"),
    ("transfer", "Перевод", "#7C3AED", "#5B21B6"),  # фиолетовый из дизайна (QR-цвет)
]


class _CloseOrderWorker(QObject):
    success = Signal(dict)            # {"order": {...}, "print_job": {...}}
    error = Signal(object)             # ApiError

    def __init__(
        self,
        client: ApiClient,
        order_id: int,
        idem_key: str,
        *,
        payment_method: str | None = None,
        payments: list[dict] | None = None,
        tip_amount: str | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.payment_method = payment_method
        self.payments = payments
        self.tip_amount = tip_amount
        self.idem_key = idem_key

    def run(self) -> None:
        body: dict = {}
        if self.payments is not None:
            body["payments"] = self.payments
        else:
            body["payment_method"] = self.payment_method
        if self.tip_amount is not None:
            body["tip_amount"] = self.tip_amount
        try:
            data = self.client.post(
                f"/orders/{self.order_id}/close/",
                json=body,
                extra_headers={"Idempotency-Key": self.idem_key},
            )
            self.success.emit(data)
        except ApiError as e:
            self.error.emit(e)


class PaymentDialog(QDialog):
    """Модалка оплаты заказа.

    Сигналы:
        order_paid(order_dict, print_job_dict) — успешный close → main открывает ReceiptStatusDialog
    """

    order_paid = Signal(dict, dict)

    def __init__(
        self,
        order: dict,
        table: dict | None,
        client: ApiClient,
        parent: QWidget | None = None,
        *,
        compact: bool = False,
        embedded: bool = False,
    ) -> None:
        """compact=True → frame 8 layout (520px): уже модалка, меньше кнопки
        методов (52px), правая колонка с bg-gray, footer с двумя равными
        кнопками [Отмена] [Оплатить и печать]. Используется для table-payment
        flow (когда жмём «Оплата» из правой панели TablesScreen).

        compact=False (дефолт) → frame 9 layout (720px): большие 72px кнопки,
        Footer с одной зелёной кнопкой + pill «Без чека» снизу.
        """
        super().__init__(parent)
        self._order = order
        self._table = table or {}
        self._client = client
        self._compact = bool(compact)
        self._embedded = bool(embedded)
        self._payment_method: str = ""
        self._idem_key = str(uuid.uuid4())  # один на жизнь модалки → ретрай == тот же ключ
        self._method_buttons: dict[str, QPushButton] = {}
        self._thread: QThread | None = None
        self._worker: _CloseOrderWorker | None = None
        # Если True — main не показывает ReceiptStatusDialog (оплата без чека).
        self._silent: bool = False

        self.setWindowTitle("Оплата")
        self.setModal(True)
        self.setStyleSheet(
            f"PaymentDialog {{ background-color: {COLORS['bg_white']}; }}"
        )
        self.setFixedWidth(520 if self._compact else 720)

        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header пропускаем для embedded-режима — host (drawer) сам рисует
        # заголовок и кнопку закрытия, чтобы не было двойного header'а.
        if not self._embedded:
            outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: transparent;"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)

        title = QLabel(f"Оплата заказа №{self._order['id']}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
        )
        close = QPushButton()
        close.setFlat(True)
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(32, 32)
        close.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close.setIconSize(QSize(18, 18))
        close.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; border-radius: 4px; }}"
        )
        close.clicked.connect(self.reject)
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(close)
        return h

    def _build_body(self) -> QWidget:
        body = QFrame()
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        h.addWidget(self._build_left_col())
        h.addWidget(self._build_right_col(), 1)
        return body

    def _build_left_col(self) -> QWidget:
        col = QFrame()
        # Compact: уже + правая колонка с серым фоном (по дизайну frame 8).
        # Embedded в drawer (480px) — ещё уже (240) чтобы правая колонка
        # с кнопками методов оплаты влезла без обрезаний.
        if self._embedded:
            col.setFixedWidth(220)
        else:
            col.setFixedWidth(280 if self._compact else 350)
        col.setStyleSheet(
            f"background: transparent;"
            f" border-right: 1px solid {COLORS['border_light']};"
        )
        v = QVBoxLayout(col)
        if self._embedded:
            v.setContentsMargins(14, 14, 14, 14)
            v.setSpacing(SPACING["sm"])
        else:
            v.setContentsMargins(
                SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"],
            )
            v.setSpacing(SPACING["md"])

        # «Стол N · K гостей»
        table_name = self._table.get("name") or f"Стол {self._table.get('number', '?')}"
        guests = int(self._order.get("guests_count") or 0)
        head = QLabel(
            f"{table_name} · {guests} {self._guests_word(guests)}"
            if guests else table_name
        )
        head.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        v.addWidget(head)

        # Список позиций
        items = [it for it in (self._order.get("items") or []) if not it.get("cancelled_at")]
        for it in items:
            v.addWidget(self._build_item_row(it))

        # Separator + Подитог / Скидка / Обслуживание (placeholder для Phase 4)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        v.addWidget(sep)

        from decimal import Decimal

        def _dec(key: str, default: str = "0.00") -> Decimal:
            try:
                return Decimal(str(self._order.get(key, default) or default))
            except Exception:
                return Decimal(default)

        subtotal = _dec("subtotal")
        service_amount = _dec("service_charge_amount")
        service_pct = _dec("service_charge_pct")
        discount_amount = _dec("discount_amount")
        total = _dec("total")
        # Старые сериализаторы могут не вернуть subtotal — fallback.
        if subtotal == 0 and total > 0:
            subtotal = total + discount_amount - service_amount
        currency = self._order.get("currency") or "TJS"

        v.addWidget(self._build_subtotal_row("Подитог", f"{subtotal:.2f}"))

        # Скидка — кликабельная строка, открывает DiscountPickerDialog.
        discount_name = self._order.get("discount_name") or ""
        discount_label = (
            f"Скидка ({discount_name})" if discount_name else "Скидка"
        )
        v.addWidget(
            self._build_clickable_row(
                discount_label,
                f"−{discount_amount:.2f}",
                value_color=COLORS["danger_red"],
                handler=self._open_discount_picker,
                action_hint="изменить",
            )
        )

        # Сервисный сбор — реальный из snapshot'а заказа.
        svc_label = (
            f"Обслуживание ({float(service_pct):g}%)" if service_pct > 0
            else "Обслуживание"
        )
        v.addWidget(self._build_subtotal_row(svc_label, f"+{service_amount:.2f}"))

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        v.addWidget(sep2)

        # ИТОГО — в embedded режиме stack вертикально (маленький лейбл сверху,
        # большая сумма снизу), чтобы влезть в узкую колонку 220px без обрезания.
        # В modal режиме — горизонтально как раньше.
        if self._embedded:
            total_row = QWidget()
            tr = QVBoxLayout(total_row)
            tr.setContentsMargins(0, 6, 0, 0)
            tr.setSpacing(2)
            lbl = QLabel("ИТОГО")
            lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 700;"
                f" letter-spacing: 1px; background: transparent; border: none;"
            )
            amount = QLabel(f"{total:.2f} {currency}")
            amount.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 22pt; font-weight: 800;"
                f" background: transparent; border: none;"
            )
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tr.addWidget(lbl)
            tr.addWidget(amount)
        else:
            total_row = QWidget()
            tr = QHBoxLayout(total_row)
            tr.setContentsMargins(0, 6, 0, 0)
            lbl = QLabel("ИТОГО")
            lbl.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
                f" background: transparent; border: none;"
            )
            amount = QLabel(f"{total:.2f} {currency}")
            amount.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 28pt; font-weight: 800;"
                f" background: transparent; border: none;"
            )
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tr.addWidget(lbl)
            tr.addStretch(1)
            tr.addWidget(amount)
        v.addWidget(total_row)
        v.addStretch(1)
        return col

    def _build_clickable_row(
        self,
        label: str,
        value: str,
        *,
        value_color: str | None = None,
        handler=None,
        action_hint: str = "",
    ) -> QWidget:
        """Subtotal-строка, по клику открывает что-то (например DiscountPicker)."""
        from PySide6.QtCore import QSize
        row = QPushButton()
        row.setFlat(True)
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  padding: 4px 6px;"
            f"  text-align: left;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['bg_gray']};"
            f"  border-radius: 4px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" background: transparent; border: none;"
        )
        v_lbl = QLabel(value)
        v_lbl.setStyleSheet(
            f"color: {value_color or COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        v_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(l)
        h.addStretch(1)
        if action_hint:
            hint = QLabel(action_hint)
            hint.setStyleSheet(
                f"color: {COLORS['primary_blue']}; font-size: 9pt; font-weight: 500;"
                f" background: transparent; border: none;"
            )
            h.addWidget(hint)
        h.addWidget(v_lbl)
        if handler:
            row.clicked.connect(handler)
        return row

    def _build_subtotal_row(
        self, label: str, value: str, value_color: str | None = None
    ) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" background: transparent; border: none;"
        )
        v = QLabel(value)
        v.setStyleSheet(
            f"color: {value_color or COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(l)
        h.addStretch(1)
        h.addWidget(v)
        return row

    def _build_item_row(self, item: dict) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        name = item.get("name_at_order") or "?"
        qty = int(item.get("qty") or 1)
        title = QLabel(f"{qty}× {name}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt;"
        )
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        sub = item.get("subtotal") or "0.00"
        amount = QLabel(str(sub))
        amount.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt;"
        )
        amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(title, 1)
        h.addWidget(amount)
        return row

    def _build_right_col(self) -> QWidget:
        col = QFrame()
        # Compact: серый фон в правой колонке (по дизайну frame 8).
        if self._compact:
            col.setStyleSheet(f"background: {COLORS['bg_gray']};")
        v = QVBoxLayout(col)
        if self._embedded:
            v.setContentsMargins(14, 14, 14, 14)
            v.setSpacing(SPACING["md"])
        else:
            v.setContentsMargins(
                SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"],
            )
            v.setSpacing(SPACING["lg"])

        head = QLabel("Способ оплаты")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 700;"
        )
        v.addWidget(head)

        # Кнопки методов в одну строку (как в дизайне)
        buttons_row = QWidget()
        bh = QHBoxLayout(buttons_row)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(SPACING["sm"])
        for code, label, color, dark in PAYMENT_METHODS:
            btn = self._build_method_button(code, label, color, dark)
            self._method_buttons[code] = btn
            bh.addWidget(btn, 1)
        v.addWidget(buttons_row)

        # Чаевые — простое поле, не выделяется тогглом. Сумма добавляется к
        # итогу заказа на стороне backend (close_order(tip_amount=...)),
        # и уже распределяется по payments в multi-payment режиме.
        tip_row = QWidget()
        tip_h = QHBoxLayout(tip_row)
        tip_h.setContentsMargins(0, 0, 0, 0)
        tip_h.setSpacing(SPACING["sm"])
        tip_lbl = QLabel("Чаевые")
        tip_lbl.setFixedWidth(80)
        tip_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        self._tip_input = QLineEdit()
        self._tip_input.setPlaceholderText("0.00")
        self._tip_input.setFixedHeight(36)
        self._tip_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 10px; font-size: 12pt; font-weight: 600;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        self._tip_input.textChanged.connect(self._on_tip_changed)
        tip_h.addWidget(tip_lbl)
        tip_h.addWidget(self._tip_input, 1)
        v.addWidget(tip_row)

        self._tip_total_lbl = QLabel("")
        self._tip_total_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" padding-left: 88px;"
        )
        self._tip_total_lbl.setVisible(False)
        v.addWidget(self._tip_total_lbl)

        # Toggle «Смешанная оплата» (Phase 4 multi-payment).
        # Когда включено — показываем 3 поля ввода (cash / card / transfer)
        # с running «Осталось: X TJS». Pay-кнопка активна когда сумма == total.
        # В embedded режиме укорачиваем подпись чтобы не обрезалось в drawer'е.
        mixed_label = (
            "  Смешанная оплата"
            if self._embedded
            else "  Смешанная оплата (наличка + карта)"
        )
        self._mixed_chk = QPushButton(mixed_label)
        self._mixed_chk.setCheckable(True)
        self._mixed_chk.setCursor(Qt.PointingHandCursor)
        self._mixed_chk.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_secondary']};"
            f"  border: 1px dashed {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  font-size: 10pt; font-weight: 600;"
            f"  text-align: left;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
            f"QPushButton:checked {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"}}"
        )
        self._mixed_chk.toggled.connect(self._on_mixed_toggled)
        v.addWidget(self._mixed_chk)

        # Контейнер с полями ввода — скрыт по умолчанию.
        self._mixed_inputs_box = QFrame()
        self._mixed_inputs_box.setVisible(False)
        mb = QVBoxLayout(self._mixed_inputs_box)
        mb.setContentsMargins(0, SPACING["sm"], 0, 0)
        mb.setSpacing(SPACING["sm"])
        self._mixed_inputs: dict[str, QLineEdit] = {}
        for code, label, _color, _dark in PAYMENT_METHODS:
            row = QHBoxLayout()
            row.setSpacing(SPACING["sm"])
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 11pt;"
            )
            inp = QLineEdit()
            inp.setPlaceholderText("0.00")
            inp.setFixedHeight(36)
            inp.setStyleSheet(
                f"QLineEdit {{"
                f"  background: {COLORS['bg_white']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 10px;"
                f"  font-size: 12pt; font-weight: 600;"
                f"  color: {COLORS['text_primary']};"
                f"}}"
                f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
            )
            inp.textChanged.connect(self._on_mixed_amount_changed)
            self._mixed_inputs[code] = inp
            row.addWidget(lbl)
            row.addWidget(inp, 1)
            mb.addLayout(row)
        # Running balance label
        self._mixed_balance_lbl = QLabel("Осталось: —")
        self._mixed_balance_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; font-weight: 700;"
            f" padding-top: 4px;"
        )
        mb.addWidget(self._mixed_balance_lbl)
        v.addWidget(self._mixed_inputs_box)

        v.addStretch(1)
        return col

    def _on_mixed_toggled(self, checked: bool) -> None:
        self._mixed_inputs_box.setVisible(checked)
        if checked:
            # Сбрасываем выбор «single method», блокируем кнопки методов.
            self._payment_method = ""
            for c, btn in self._method_buttons.items():
                btn.setChecked(False)
                btn.setEnabled(False)
            self._on_mixed_amount_changed("")  # пересчёт
        else:
            for c, btn in self._method_buttons.items():
                btn.setEnabled(True)
            for inp in self._mixed_inputs.values():
                inp.blockSignals(True)
                inp.clear()
                inp.blockSignals(False)
            self._pay_btn.setEnabled(False)
            self._no_receipt_btn.setEnabled(False)

    def _parse_dec(self, text: str) -> Decimal:
        try:
            return Decimal((text or "").strip()) if text and text.strip() else Decimal("0")
        except Exception:
            return Decimal("0")

    def _mixed_payments_list(self) -> list[dict]:
        """Список {method, amount} только для непустых > 0 полей."""
        out: list[dict] = []
        for code, inp in self._mixed_inputs.items():
            v = self._parse_dec(inp.text())
            if v > 0:
                out.append({"method": code, "amount": str(v)})
        return out

    def _on_mixed_amount_changed(self, _text: str = "") -> None:
        # Чистим non-numeric в полях
        for inp in self._mixed_inputs.values():
            t = inp.text()
            cleaned = "".join(c for c in t if c.isdigit() or c == ".")
            if cleaned.count(".") > 1:
                first = cleaned.find(".")
                cleaned = cleaned[: first + 1] + cleaned[first + 1 :].replace(".", "")
            if cleaned != t:
                inp.blockSignals(True)
                inp.setText(cleaned)
                inp.blockSignals(False)

        total = self._effective_total()
        paid = sum(
            (self._parse_dec(inp.text()) for inp in self._mixed_inputs.values()),
            Decimal("0"),
        )
        remaining = total - paid
        if remaining > 0:
            self._mixed_balance_lbl.setText(f"Осталось: {remaining} TJS")
            self._mixed_balance_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 10pt; font-weight: 700;"
                f" padding-top: 4px;"
            )
        elif remaining == 0 and paid > 0:
            self._mixed_balance_lbl.setText("✓ Сумма совпадает")
            self._mixed_balance_lbl.setStyleSheet(
                f"color: #16A34A; font-size: 10pt; font-weight: 700;"
                f" padding-top: 4px;"
            )
        else:
            # paid > total → перебор
            over = paid - total
            self._mixed_balance_lbl.setText(f"Перебор: {over} TJS")
            self._mixed_balance_lbl.setStyleSheet(
                f"color: #DC2626; font-size: 10pt; font-weight: 700;"
                f" padding-top: 4px;"
            )
        is_valid = (remaining == 0 and paid == total and paid > 0)
        self._pay_btn.setEnabled(is_valid)
        self._no_receipt_btn.setEnabled(is_valid)

    def _build_method_button(
        self, code: str, label: str, color: str, dark: str
    ) -> QPushButton:
        btn = QPushButton(label)
        # Compact: 52px (frame 8); полный режим: 72px (frame 9).
        btn.setFixedHeight(52 if self._compact else 72)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCheckable(True)
        # Хранение кастомных цветов в свойствах не работает в QSS,
        # делаем стиль через ID-селектор по objectName.
        btn.setObjectName(f"payBtn_{code}")
        btn.setStyleSheet(
            f"QPushButton#payBtn_{code} {{"
            f"  background-color: {color};"
            f"  color: {COLORS['text_white']};"
            f"  border: 3px solid transparent;"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 13pt; font-weight: 700;"
            f"}}"
            f"QPushButton#payBtn_{code}:pressed {{ background-color: {dark}; }}"
            f"QPushButton#payBtn_{code}:checked {{ border: 3px solid {COLORS['text_primary']}; }}"
        )
        btn.clicked.connect(lambda _checked=False, c=code: self._select_method(c))
        return btn

    def _select_method(self, code: str) -> None:
        self._payment_method = code
        for c, btn in self._method_buttons.items():
            btn.setChecked(c == code)
        self._pay_btn.setEnabled(True)
        self._no_receipt_btn.setEnabled(True)

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: transparent;"
            f" border-top: 1px solid {COLORS['border_light']};"
        )

        # ----- Compact (frame 8) — две равные кнопки в ряд + pill снизу -----
        if self._compact:
            v = QVBoxLayout(f)
            if self._embedded:
                v.setContentsMargins(14, 10, 14, 10)
                v.setSpacing(SPACING["sm"])
            else:
                v.setContentsMargins(
                    SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"],
                )
                v.setSpacing(SPACING["md"])

            row = QHBoxLayout()
            row.setSpacing(SPACING["md"])

            cancel = QPushButton("Отмена")
            cancel.setFixedHeight(48)
            cancel.setCursor(Qt.PointingHandCursor)
            cancel.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 10px;"
                f"  font-size: 12pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            cancel.clicked.connect(self.reject)
            row.addWidget(cancel, 1)

            self._pay_btn = QPushButton("Оплатить и печать")
            self._pay_btn.setFixedHeight(48)
            self._pay_btn.setCursor(Qt.PointingHandCursor)
            self._pay_btn.setFocusPolicy(Qt.NoFocus)
            self._pay_btn.setEnabled(False)
            self._pay_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {COLORS['success_green']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 10px;"
                f"  font-size: 13pt; font-weight: 700;"
                f"}}"
                f"QPushButton:pressed {{ background-color: #15803D; }}"
                f"QPushButton:disabled {{"
                f"  background-color: {COLORS['border_light']};"
                f"  color: {COLORS['text_secondary']};"
                f"}}"
            )
            self._pay_btn.clicked.connect(self._on_pay)
            row.addWidget(self._pay_btn, 1)
            v.addLayout(row)

            # Pill «Без чека» — небольшая, по центру.
            pill_row = QHBoxLayout()
            pill_row.addStretch(1)
            self._no_receipt_btn = QPushButton("  Оплата без чека →")
            self._no_receipt_btn.setFixedHeight(36)
            self._no_receipt_btn.setMinimumWidth(220)
            self._no_receipt_btn.setCursor(Qt.PointingHandCursor)
            self._no_receipt_btn.setFocusPolicy(Qt.NoFocus)
            self._no_receipt_btn.setEnabled(False)
            self._no_receipt_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: #FFF7ED;"
                f"  color: {COLORS['accent_orange']};"
                f"  border: 1px solid {COLORS['accent_orange']};"
                f"  border-radius: 18px;"
                f"  padding: 0 18px;"
                f"  font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover:enabled {{ background-color: #FFEDD5; }}"
                f"QPushButton:disabled {{"
                f"  background-color: {COLORS['bg_white']};"
                f"  color: {COLORS['text_secondary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"}}"
            )
            self._no_receipt_btn.clicked.connect(self._on_pay_no_receipt)
            pill_row.addWidget(self._no_receipt_btn)
            pill_row.addStretch(1)
            v.addLayout(pill_row)
            return f

        # ----- Full (frame 9) — большая зелёная + pill снизу -----
        v = QVBoxLayout(f)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["md"])

        # Главная зелёная кнопка
        self._pay_btn = QPushButton("ОПЛАТИТЬ И ПЕЧАТЬ ЧЕК  →")
        self._pay_btn.setFixedHeight(56)
        self._pay_btn.setCursor(Qt.PointingHandCursor)
        self._pay_btn.setFocusPolicy(Qt.NoFocus)
        self._pay_btn.setEnabled(False)
        self._pay_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 16pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background-color: #15803D; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._pay_btn.clicked.connect(self._on_pay)
        v.addWidget(self._pay_btn)

        # Вторичная: «Оплата без чека →» — по дизайну frame 9.
        self._no_receipt_btn = QPushButton("  Оплата без чека  →")
        self._no_receipt_btn.setFixedHeight(44)
        self._no_receipt_btn.setCursor(Qt.PointingHandCursor)
        self._no_receipt_btn.setFocusPolicy(Qt.NoFocus)
        self._no_receipt_btn.setEnabled(False)
        # Иконка чека слева — по дизайну frame 9 (receipt + arrow).
        self._no_receipt_btn.setIcon(qicon("receipt", COLORS["accent_orange"], 18))
        self._no_receipt_btn.setIconSize(QSize(18, 18))
        self._no_receipt_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: #FFF7ED;"
            f"  color: {COLORS['accent_orange']};"
            f"  border: 1px solid {COLORS['accent_orange']};"
            f"  border-radius: 10px;"
            f"  font-size: 14pt; font-weight: 600;"
            f"  padding: 0 10px;"
            f"}}"
            f"QPushButton:hover:enabled {{ background-color: #FFEDD5; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  color: {COLORS['text_secondary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        self._no_receipt_btn.clicked.connect(self._on_pay_no_receipt)
        v.addWidget(self._no_receipt_btn)
        return f

    # ------- handlers -------

    def _open_discount_picker(self) -> None:
        """Открыть DiscountPickerDialog и обновить заказ после применения."""
        # Lazy-import чтобы избежать циклов.
        from pos.screens.discount_picker_dialog import DiscountPickerDialog

        # Получаем список через глобальный State — кэшируется.
        # PaymentDialog не имеет ссылки на State, но client есть → используем
        # его для прямого fetch.
        from pos.http_client import ApiError
        try:
            data = self._client.get(
                "/discounts/", params={"type": "discount", "is_active": "true"}
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            discounts = [d for d in items if d.get("is_active", True)]
        except ApiError:
            discounts = []

        dlg = DiscountPickerDialog(
            order=self._order,
            discounts=discounts,
            client=self._client,
            parent=self,
        )
        dlg.discount_applied.connect(self._on_discount_applied)
        dlg.exec()

    def _on_discount_applied(self, order: dict) -> None:
        """Скидка применена / снята — пересоздаём содержимое диалога."""
        self._order = {**self._order, **order}
        # Сбрасываем состояние выбора метода, ссылки на старые кнопки.
        self._payment_method = ""
        self._method_buttons = {}
        self._silent = False
        # Удаляем все виджеты текущего layout и собираем заново через _build_*.
        outer = self.layout()
        while outer.count():
            child = outer.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _tip_value(self) -> Decimal:
        """Распарсить введённую сумму чаевых; возвращает Decimal('0') при пусто/невалидно."""
        if not hasattr(self, "_tip_input"):
            return Decimal("0")
        raw = (self._tip_input.text() or "").strip()
        if not raw or raw == ".":
            return Decimal("0")
        try:
            v = Decimal(raw)
        except Exception:
            return Decimal("0")
        return max(v, Decimal("0"))

    def _on_tip_changed(self, _text: str = "") -> None:
        # Фильтр: только цифры + 1 точка
        t = self._tip_input.text()
        cleaned = "".join(c for c in t if c.isdigit() or c == ".")
        if cleaned.count(".") > 1:
            first = cleaned.find(".")
            cleaned = cleaned[: first + 1] + cleaned[first + 1 :].replace(".", "")
        if cleaned != t:
            self._tip_input.blockSignals(True)
            self._tip_input.setText(cleaned)
            self._tip_input.blockSignals(False)
        # Live-обновление: показать «Итого с чаевыми: X TJS»
        tip = self._tip_value()
        if tip > 0:
            try:
                base_total = Decimal(str(self._order.get("total", "0") or "0"))
            except Exception:
                base_total = Decimal("0")
            new_total = base_total + tip
            self._tip_total_lbl.setText(f"Итого: {new_total} TJS")
            self._tip_total_lbl.setVisible(True)
        else:
            self._tip_total_lbl.setVisible(False)
        # Если включён mixed — пересчитаем баланс
        if self._is_mixed_mode():
            self._on_mixed_amount_changed("")

    def _effective_total(self) -> Decimal:
        """Итог с учётом чаевых — для проверки mixed-payment баланса."""
        try:
            base = Decimal(str(self._order.get("total", "0") or "0"))
        except Exception:
            base = Decimal("0")
        return base + self._tip_value()

    def _is_mixed_mode(self) -> bool:
        return getattr(self, "_mixed_chk", None) is not None and self._mixed_chk.isChecked()

    def _has_valid_payment(self) -> bool:
        if self._is_mixed_mode():
            return self._pay_btn.isEnabled()  # toggled выше через _on_mixed_amount_changed
        return bool(self._payment_method)

    def _on_pay_no_receipt(self) -> None:
        """Закрыть заказ без печати чека.

        В v3-бэке всегда есть PrintJob (для аудита/повтора), но печать клиенту
        мы не показываем — просто не открываем ReceiptStatusDialog.
        Сигнал order_paid эмитим с пустым print_job, чтобы main решил не показывать."""
        if not self._has_valid_payment() or self._thread is not None:
            return
        # Помечаем «без чека» — main по пустому print_job не открывает ReceiptStatusDialog.
        self._silent = True
        self._on_pay()

    def _on_pay(self) -> None:
        if not self._has_valid_payment() or self._thread is not None:
            return
        self._pay_btn.setEnabled(False)
        self._pay_btn.setText("Подождите…")

        tip = self._tip_value()
        tip_str = str(tip) if tip > 0 else None

        thread = QThread(self)
        if self._is_mixed_mode():
            worker = _CloseOrderWorker(
                self._client, int(self._order["id"]), self._idem_key,
                payments=self._mixed_payments_list(),
                tip_amount=tip_str,
            )
        else:
            worker = _CloseOrderWorker(
                self._client, int(self._order["id"]), self._idem_key,
                payment_method=self._payment_method,
                tip_amount=tip_str,
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
        order = data.get("order") or {}
        print_job = data.get("print_job") or {}
        # При оплате «без чека» очищаем print_job — main не покажет ReceiptStatusDialog.
        if self._silent:
            print_job = {}
        self.order_paid.emit(order, print_job)
        self.accept()

    def _on_close_error(self, exc: ApiError) -> None:
        self._thread = None
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Ошибка оплаты", f"{exc.message}\n[{exc.code}]")
        self._pay_btn.setEnabled(True)
        self._pay_btn.setText("ОПЛАТИТЬ И ПЕЧАТЬ ЧЕК  →")

    @staticmethod
    def _guests_word(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return "гость"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "гостя"
        return "гостей"
