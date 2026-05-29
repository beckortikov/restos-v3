"""Закрытие смены — frame "17. Закрытие смены" (id=7MWqM) в design/pos_cashier.pen.

Модальный диалог:
- header: «Закрытие смены №X» + ✕
- step indicator (1) Пересчёт кассы → (2) Закрытие смены
- stats row: открыта / сейчас / заказов / гостей / ср. чек
- revenue cards (3 цвета): cash green / card blue / transfer purple
- result section: Ожидаемо / Фактически / Расхождение
- input «Фактический остаток» + match badge
- footer: Отмена + «ЗАКРЫТЬ СМЕНУ» red
"""
from datetime import datetime
from datetime import timezone as tz
from decimal import Decimal

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING

DUSHANBE = tz.utc  # отображение HH:MM в локальном поясе уже учтено в backend ISO


class _CloseShiftWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self, client: ApiClient, shift_id: int, actual_balance: Decimal, note: str
    ) -> None:
        super().__init__()
        self.client = client
        self.shift_id = shift_id
        self.actual_balance = actual_balance
        self.note = note

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/shifts/{self.shift_id}/close/",
                json={
                    "actual_balance": str(self.actual_balance),
                    "note": self.note,
                },
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class CloseShiftScreen(QDialog):
    """Сигнал shift_closed(closed_shift: dict)."""

    shift_closed = Signal(dict)

    def __init__(
        self, shift: dict, client: ApiClient, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._shift = dict(shift)
        self._client = client
        self._thread: QThread | None = None
        self._worker: _CloseShiftWorker | None = None
        self.setWindowTitle("Закрытие смены")
        self.setModal(True)
        self.setFixedWidth(640)
        self._build()

    # -------- build --------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())
        # Первичный расчёт diff после того как все виджеты построены.
        self._update_diff()

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)

        title = QLabel(f"Закрытие смены №{self._shift.get('number', '?')}")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        close_btn = QPushButton()
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(32, 32)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close_btn.setIconSize(QSize(18, 18))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; border-radius: 4px; }}"
        )
        close_btn.clicked.connect(self.reject)

        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(close_btn)
        return h

    def _build_body(self) -> QWidget:
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        v = QVBoxLayout(body)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        v.addWidget(self._build_step_indicator())
        v.addWidget(self._build_stats_row())
        v.addWidget(self._build_revenue_row())
        v.addWidget(self._build_result_section())
        v.addLayout(self._build_balance_input())
        v.addWidget(self._build_match_badge())
        return body

    def _build_step_indicator(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_gray']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(8)

        s1 = QLabel("① Пересчёт кассы")
        s1.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11pt;")

        s2 = QLabel("② Закрытие смены")
        s2.setStyleSheet(
            f"color: {COLORS['accent_orange']};"
            f" font-size: 11pt; font-weight: 700;"
        )

        h.addWidget(s1)
        h.addWidget(arrow)
        h.addWidget(s2)
        h.addStretch(1)
        return f

    def _build_stats_row(self) -> QFrame:
        f = QFrame()
        h = QHBoxLayout(f)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        opened_at = self._fmt_time(self._shift.get("opened_at"))
        now_str = datetime.now().strftime("%H:%M")
        orders = int(self._shift.get("orders_count") or 0)
        guests = int(self._shift.get("guests_count") or 0)
        avg = self._shift.get("average_check") or "0.00"

        for label, value in (
            ("Открыта", opened_at),
            ("Сейчас", now_str),
            ("Заказов", str(orders)),
            ("Гостей", str(guests)),
            ("Ср. чек", str(avg)),
        ):
            h.addWidget(self._stat_card(label, value), 1)
        return f

    def _stat_card(self, label: str, value: str) -> QFrame:
        c = QFrame()
        c.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        v = QVBoxLayout(c)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(2)
        v.setAlignment(Qt.AlignCenter)

        l = QLabel(label)
        l.setAlignment(Qt.AlignCenter)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none;"
        )
        val = QLabel(value)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 14pt; font-weight: 700; border: none;"
        )
        v.addWidget(l)
        v.addWidget(val)
        return c

    def _build_revenue_row(self) -> QFrame:
        f = QFrame()
        h = QHBoxLayout(f)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        cash = self._shift.get("cash_revenue") or "0.00"
        card = self._shift.get("card_revenue") or "0.00"
        tr = self._shift.get("transfer_revenue") or "0.00"

        h.addWidget(self._rev_card("Наличные", cash, COLORS["success_green"]), 1)
        h.addWidget(self._rev_card("Карта", card, COLORS["primary_blue"]), 1)
        h.addWidget(self._rev_card("Перевод", tr, "#7C3AED"), 1)
        return f

    def _rev_card(self, label: str, value: str, color: str) -> QFrame:
        c = QFrame()
        c.setStyleSheet(
            f"background: {color};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        v = QVBoxLayout(c)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)

        l = QLabel(label)
        l.setStyleSheet(
            f"color: rgba(255,255,255,0.95); font-size: 10pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        val = QLabel(value)
        val.setStyleSheet(
            f"color: {COLORS['text_white']};"
            f" font-size: 16pt; font-weight: 800;"
            f" border: none; background: transparent;"
        )
        v.addWidget(l)
        v.addWidget(val)
        return c

    def _build_result_section(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_gray']};"
            f" border-radius: {RADIUS['sm']}px;"
            f" border: 1px solid {COLORS['border_light']};"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        title = QLabel("Результат пересчёта")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(title)

        expected = self._shift.get("expected_balance") or "0.00"
        v.addLayout(self._result_row("Ожидаемо:", f"{expected} TJS", COLORS["text_secondary"]))
        self._fact_row_value = QLabel(f"{expected} TJS")
        self._fact_row_value.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 600; border: none;"
            f" background: transparent;"
        )
        self._fact_row_value.setAlignment(Qt.AlignRight)
        # row для фактически
        fact_row = QHBoxLayout()
        fact_label = QLabel("Фактически:")
        fact_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        fact_row.addWidget(fact_label)
        fact_row.addStretch(1)
        fact_row.addWidget(self._fact_row_value)
        v.addLayout(fact_row)

        # diff
        self._diff_label = QLabel("0.00 TJS")
        self._diff_label.setAlignment(Qt.AlignRight)
        diff_row = QHBoxLayout()
        diff_lbl = QLabel("Расхождение:")
        diff_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        diff_row.addWidget(diff_lbl)
        diff_row.addStretch(1)
        diff_row.addWidget(self._diff_label)
        v.addLayout(diff_row)
        return f

    def _result_row(self, label: str, value: str, color: str) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {color}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        v = QLabel(value)
        v.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        v.setAlignment(Qt.AlignRight)
        h.addWidget(l)
        h.addStretch(1)
        h.addWidget(v)
        return h

    def _build_balance_input(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(SPACING["sm"])

        lbl = QLabel("Фактический остаток")
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10pt;")
        v.addWidget(lbl)

        expected_str = str(self._shift.get("expected_balance") or "0.00")
        self._balance_input = QLineEdit(expected_str)
        self._balance_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 12px 14px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 16pt; font-weight: 700;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {COLORS['primary_blue']}; }}"
        )
        self._balance_input.textChanged.connect(self._update_diff)
        v.addWidget(self._balance_input)

        sys_lbl = QLabel(f"По системе: {expected_str} TJS")
        sys_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt;"
        )
        v.addWidget(sys_lbl)
        # Первичный расчёт diff отложен — _match_badge ещё не построен.
        return v

    def _build_match_badge(self) -> QFrame:
        self._match_badge = QFrame()
        self._match_badge.setStyleSheet(
            f"background: #DCFCE7; border-radius: 16px;"
        )
        h = QHBoxLayout(self._match_badge)
        h.setContentsMargins(12, 4, 12, 4)
        h.setSpacing(6)
        h.setAlignment(Qt.AlignCenter)

        chk = QLabel()
        chk.setPixmap(qicon("check", COLORS["success_green"], 14).pixmap(14, 14))

        self._badge_text = QLabel("совпадает")
        self._badge_text.setStyleSheet(
            f"color: {COLORS['success_green']}; font-size: 10pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        h.addWidget(chk)
        h.addWidget(self._badge_text)

        wrap = QFrame()
        wrap.setStyleSheet("background: transparent;")
        wh = QHBoxLayout(wrap)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.addWidget(self._match_badge, 0, Qt.AlignLeft)
        wh.addStretch(1)
        return wrap

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        h.setSpacing(SPACING["md"])

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(48)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 600; padding: 0 24px;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)

        self._close_btn = QPushButton("ЗАКРЫТЬ СМЕНУ")
        self._close_btn.setFixedHeight(56)
        self._close_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 13pt; font-weight: 700; padding: 0 24px;"
            f"}}"
            f"QPushButton:pressed {{ background-color: #B91C1C; }}"
            f"QPushButton:disabled {{ background: {COLORS['border_light']}; color: {COLORS['text_secondary']}; }}"
        )
        self._close_btn.clicked.connect(self._on_close_shift)

        h.addWidget(cancel)
        h.addStretch(1)
        h.addWidget(self._close_btn, 1)
        return f

    # -------- handlers --------

    def _read_balance(self) -> Decimal:
        text = self._balance_input.text().replace(",", ".").replace(" ", "").strip()
        try:
            return Decimal(text)
        except Exception:
            return Decimal("0")

    def _update_diff(self) -> None:
        actual = self._read_balance()
        try:
            expected = Decimal(str(self._shift.get("expected_balance") or "0"))
        except Exception:
            expected = Decimal("0")
        diff = actual - expected
        sign = "" if diff >= 0 else ""
        diff_text = f"{diff:+.2f} TJS"
        if diff == 0:
            color = COLORS["success_green"]
            badge_color = "#DCFCE7"
            text = "совпадает"
        else:
            color = COLORS["danger_red"]
            badge_color = "#FEE2E2"
            text = "недостача" if diff < 0 else "излишек"
        self._diff_label.setText(diff_text)
        self._diff_label.setStyleSheet(
            f"color: {color}; font-size: 11pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        self._fact_row_value.setText(f"{actual:.2f} TJS")
        self._match_badge.setStyleSheet(f"background: {badge_color}; border-radius: 16px;")
        self._badge_text.setText(text)
        self._badge_text.setStyleSheet(
            f"color: {color}; font-size: 10pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )

    def _on_close_shift(self) -> None:
        if self._thread is not None:
            return
        actual = self._read_balance()
        self._close_btn.setEnabled(False)
        self._close_btn.setText("Закрываем…")

        thread = QThread(self)
        worker = _CloseShiftWorker(
            self._client, int(self._shift["id"]), actual, ""
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
        self.shift_closed.emit(data)
        self.accept()

    def _on_close_error(self, exc: ApiError) -> None:
        self._thread = None
        self._worker = None
        QMessageBox.warning(self, "Ошибка", f"{exc.message}\n[{exc.code}]")
        self._close_btn.setEnabled(True)
        self._close_btn.setText("ЗАКРЫТЬ СМЕНУ")

    @staticmethod
    def _fmt_time(iso: str | None) -> str:
        if not iso:
            return "—"
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M")
        except Exception:
            return "—"
