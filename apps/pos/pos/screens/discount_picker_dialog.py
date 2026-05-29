"""Выбор скидки для применения к заказу — Phase 4 (frame 9 PaymentDialog).

Список активных Discount(type='discount') ресторана + опция «Без скидки».
Никакого хардкода: данные из API /discounts/?type=discount.
"""
from __future__ import annotations

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
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _ApplyWorker(QObject):
    """POST /orders/{id}/apply_discount/ или /remove_discount/."""

    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self, client: ApiClient, order_id: int, discount_id: int | None
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.discount_id = discount_id  # None → remove

    def run(self) -> None:
        try:
            if self.discount_id is None:
                data = self.client.post(
                    f"/orders/{self.order_id}/remove_discount/", json={}
                )
            else:
                data = self.client.post(
                    f"/orders/{self.order_id}/apply_discount/",
                    json={"discount_id": self.discount_id},
                )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class DiscountPickerDialog(QDialog):
    """Сигнал discount_applied(order_dict) — после успешной операции."""

    discount_applied = Signal(dict)

    def __init__(
        self,
        order: dict,
        discounts: list[dict],
        client: ApiClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._order = order
        self._discounts = [
            d for d in (discounts or []) if d.get("is_active")
            and d.get("type") == "discount"
        ]
        self._client = client
        self._thread: QThread | None = None
        self._worker: _ApplyWorker | None = None

        self.setWindowTitle("Скидка")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setMinimumHeight(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        hl = QHBoxLayout(h)
        hl.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)
        title = QLabel("Применить скидку")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        hl.addWidget(title)
        hl.addStretch(1)
        outer.addWidget(h)

        # Body — scrollable list of discounts
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        bv.setSpacing(SPACING["sm"])

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(SPACING["sm"])
        hv.setAlignment(Qt.AlignTop)

        # «Без скидки» как первая опция (если уже была применена скидка → highlight)
        currently_applied = self._order.get("applied_discount")
        no_discount_btn = self._build_option_card(
            label="Без скидки",
            value_text="—",
            handler=lambda *_args: self._submit(None),
            highlighted=(currently_applied is None),
        )
        hv.addWidget(no_discount_btn)

        if self._discounts:
            for d in self._discounts:
                value_text = self._format_value(d)
                hv.addWidget(
                    self._build_option_card(
                        label=d.get("name", "?"),
                        value_text=value_text,
                        sub=d.get("description") or "",
                        handler=lambda *_args, did=int(d["id"]): self._submit(did),
                        highlighted=(currently_applied == int(d["id"])),
                    )
                )
        else:
            empty = QLabel(
                "Активных скидок нет.\n"
                "Добавьте в «Настройки → Скидки и сервис»."
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt;"
                f" padding: 40px 0; background: transparent;"
            )
            hv.addWidget(empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bv.addWidget(scroll, 1)
        outer.addWidget(body, 1)

        # Footer (only Cancel — выбор сразу применяется)
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        fl = QHBoxLayout(f)
        fl.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])
        fl.addStretch(1)
        cancel = QPushButton("Закрыть")
        cancel.setFixedHeight(40)
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
        fl.addWidget(cancel)
        outer.addWidget(f)

    def _format_value(self, d: dict) -> str:
        try:
            v = Decimal(str(d.get("value", "0") or "0"))
        except Exception:
            v = Decimal("0")
        if d.get("kind") == "percent":
            return f"−{float(v):g}%"
        return f"−{v:.2f} TJS"

    def _build_option_card(
        self,
        *,
        label: str,
        value_text: str,
        sub: str = "",
        handler,
        highlighted: bool = False,
    ) -> QPushButton:
        bg = "#FEF3E7" if highlighted else COLORS["bg_white"]
        border = COLORS["accent_orange"] if highlighted else COLORS["border_light"]

        btn = QPushButton()
        btn.setFixedHeight(64 if sub else 56)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg};"
            f"  border: 1.5px solid {border};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  text-align: left;"
            f"  padding: 0;"
            f"}}"
            f"QPushButton:hover {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        h = QHBoxLayout(btn)
        h.setContentsMargins(SPACING["lg"], SPACING["sm"], SPACING["lg"], SPACING["sm"])
        h.setSpacing(SPACING["md"])

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        l = QLabel(label)
        l.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(l)

        if sub:
            s = QLabel(sub)
            s.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 10pt;"
                f" border: none; background: transparent;"
            )
            text_col.addWidget(s)
        h.addLayout(text_col, 1)

        v = QLabel(value_text)
        v.setStyleSheet(
            f"color: {COLORS['danger_red'] if value_text != '—' else COLORS['text_secondary']};"
            f" font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        h.addWidget(v)

        btn.clicked.connect(handler)
        return btn

    # -------- handlers --------

    def _submit(self, discount_id: int | None) -> None:
        if self._thread is not None:
            return
        self.setEnabled(False)

        thread = QThread(self)
        worker = _ApplyWorker(self._client, int(self._order["id"]), discount_id)
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
        self.setEnabled(True)

    def _on_done(self, order: dict) -> None:
        self.discount_applied.emit(order)
        self.accept()

    def _on_failed(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось применить скидку: {exc.message}"
        )
