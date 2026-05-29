"""Экран 2bis. Открытие смены — frame "2. Открытие смены" в design/pos_cashier.pen.

Реальный backend: POST /shifts/open/ {opening_balance}.
"""
from decimal import Decimal

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
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


class _OpenShiftWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, opening_balance: Decimal) -> None:
        super().__init__()
        self.client = client
        self.opening_balance = opening_balance

    def run(self) -> None:
        try:
            data = self.client.post(
                "/shifts/open/",
                json={"opening_balance": str(self.opening_balance)},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class OpenShiftScreen(QWidget):
    """Frame: 2. Открытие смены. Принимает стартовый остаток, дёргает API.

    Сигналы:
        shift_opened(shift: dict) — успех (или текущая открытая смена)
        cancelled() — назад на PIN Login
    """

    shift_opened = Signal(dict)
    cancelled = Signal()

    def __init__(
        self,
        client: ApiClient | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client or ApiClient()
        self._thread: QThread | None = None
        self._existing_shift: dict | None = None
        self._build()

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"OpenShiftScreen {{ background-color: {COLORS['bg_light']}; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignCenter)

        outer.addWidget(self._build_card(), 0, Qt.AlignHCenter)

    def _build_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("shiftCard")
        card.setFixedWidth(720)
        card.setStyleSheet(
            f"#shiftCard {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-radius: {RADIUS['lg']}px;"
            f"  border: 1px solid {COLORS['border_light']};"
            f"}}"
        )

        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        v.addWidget(self._build_header())
        v.addWidget(self._build_body(), 1)
        v.addWidget(self._build_footer())
        return card

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: transparent; border: none;"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)

        title = QLabel("Открытие смены")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
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
        close_btn.clicked.connect(self.cancelled.emit)

        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(close_btn)
        return h

    def _build_body(self) -> QWidget:
        b = QWidget()
        v = QVBoxLayout(b)
        v.setContentsMargins(SPACING["xl"], 32, SPACING["xl"], 32)
        v.setSpacing(SPACING["xl"])
        v.setAlignment(Qt.AlignCenter)

        # Зелёный кружок ✓
        check = QLabel("✓")
        check.setFixedSize(64, 64)
        check.setAlignment(Qt.AlignCenter)
        check.setStyleSheet(
            f"background-color: #DCFCE7; color: {COLORS['success_green']};"
            f" border-radius: 32px; font-size: 28pt; font-weight: 700;"
        )
        v.addWidget(check, 0, Qt.AlignHCenter)

        # Касса dropdown — заглушка single value
        v.addLayout(self._build_account_field())

        # Стартовый остаток + quick buttons
        v.addLayout(self._build_balance_field())
        v.addLayout(self._build_quick_buttons())

        # Чекбокс X-отчёт (UI-only)
        chk = QCheckBox("Распечатать X-отчёт открытия")
        chk.setChecked(False)
        chk.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        chk.setEnabled(False)  # X-отчёт — Phase 3 (после backend смен)
        chk.setToolTip("Доступно после Phase 3 (backend смен)")
        self._x_report = chk
        v.addWidget(chk, 0, Qt.AlignHCenter)
        return b

    def _build_account_field(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(SPACING["sm"])
        lbl = QLabel("Касса (счёт)")
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        v.addWidget(lbl)

        # Stub-dropdown как QLineEdit readonly (мульти-кассы — Phase 3).
        field = QLineEdit("Главная касса")
        field.setReadOnly(True)
        field.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 10px 14px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
        )
        v.addWidget(field)
        return v

    def _build_balance_field(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(SPACING["sm"])
        lbl = QLabel("Стартовый остаток")
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        v.addWidget(lbl)

        self._balance = QLineEdit("0.00 TJS")
        self._balance.setAlignment(Qt.AlignCenter)
        self._balance.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 2px solid {COLORS['primary_blue']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 16px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 24pt; font-weight: 700;"
            f"}}"
        )
        # Простой числовой ввод: парсим в _read_balance.
        v.addWidget(self._balance)
        return v

    def _build_quick_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(SPACING["sm"])
        h.setAlignment(Qt.AlignCenter)

        for amount in (100, 500, 1000):
            b = QPushButton(f"+{amount}")
            b.setFixedSize(80, 36)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {COLORS['bg_gray']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:pressed {{ background-color: {COLORS['border_light']}; }}"
            )
            b.clicked.connect(lambda _checked=False, a=amount: self._add_amount(a))
            h.addWidget(b)
        return h

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: transparent; border: none;"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(f)
        layout.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        layout.setSpacing(SPACING["md"])

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(48)
        cancel.setMinimumWidth(140)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 13pt; font-weight: 600;"
            f"  padding: 0 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.cancelled.emit)

        self._open_btn = QPushButton("ОТКРЫТЬ СМЕНУ")
        self._open_btn.setFixedHeight(64)
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._open_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 14pt; font-weight: 700;"
            f"  padding: 0 40px;"
            f"}}"
            f"QPushButton:pressed {{ background-color: #15803D; }}"
        )
        self._open_btn.clicked.connect(self._on_open)

        layout.addWidget(cancel)
        layout.addStretch(1)
        layout.addWidget(self._open_btn)
        return f

    # ------- helpers -------

    def _add_amount(self, amount: int) -> None:
        current = self._read_balance()
        new = current + Decimal(amount)
        self._balance.setText(f"{new:.2f} TJS")

    def _read_balance(self) -> Decimal:
        text = self._balance.text().replace("TJS", "").replace(",", ".").strip()
        try:
            return Decimal(text)
        except Exception:
            return Decimal("0")

    def _on_open(self) -> None:
        if self._thread is not None:
            return
        # Если уже есть открытая смена — просто эмитим её, без POST.
        if self._existing_shift is not None:
            self.shift_opened.emit(self._existing_shift)
            return
        balance = self._read_balance()

        thread = QThread(self)
        worker = _OpenShiftWorker(self._client, balance)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_success)
        worker.error.connect(self._on_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # Сохраняем worker, чтобы Python GC не удалил его до доставки сигнала.
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_success(self, shift: dict) -> None:
        self._thread = None
        self._worker = None
        self.shift_opened.emit(shift)

    def _on_error(self, exc: ApiError) -> None:
        self._thread = None
        self._worker = None
        if exc.code == "SHIFT_ALREADY_OPEN":
            box = QMessageBox(self)
            box.setWindowTitle("Смена уже открыта")
            box.setText(
                "Кассовая смена уже открыта в этом ресторане.\n"
                "Продолжить работу с ней?"
            )
            box.setIcon(QMessageBox.Question)
            yes = box.addButton("Продолжить", QMessageBox.YesRole)
            box.addButton("Отмена", QMessageBox.NoRole)
            box.exec()
            if box.clickedButton() == yes:
                # подтянуть текущую открытую смену через GET /shifts/current/
                try:
                    cur = self._client.get("/shifts/current/")
                    if cur:
                        self.shift_opened.emit(cur)
                        return
                except ApiError as e:
                    QMessageBox.warning(
                        self, "Ошибка", f"Не удалось получить смену: {e.message}"
                    )
            return
        QMessageBox.warning(self, "Ошибка", f"{exc.message}\n[{exc.code}]")

    def reset(self, *, existing: dict | None = None) -> None:
        """Сбросить экран в начальное состояние.

        Если existing передан — переключаемся в режим «продолжить смену»:
        показываем сводку (номер, открыта в HH:MM кассиром X) и одну кнопку
        «Продолжить смену». Иначе — обычная форма открытия."""
        self._balance.setText("0.00 TJS")
        self._existing_shift = existing if isinstance(existing, dict) else None
        if self._existing_shift is not None:
            num = self._existing_shift.get("number", "?")
            opened_at = (self._existing_shift.get("opened_at") or "")[:16].replace("T", " ")
            cashier = (
                self._existing_shift.get("cashier_name")
                or self._existing_shift.get("cashier")
                or "—"
            )
            self._open_btn.setText(
                f"ПРОДОЛЖИТЬ СМЕНУ №{num}"
            )
            # Подсветим info под balance: «Открыта HH:MM, кассир X»
            self._balance.setText(
                f"{self._existing_shift.get('opening_balance', '0.00')} TJS"
            )
            tooltip = f"Открыта {opened_at}, кассир: {cashier}"
            self._open_btn.setToolTip(tooltip)
        else:
            self._open_btn.setText("ОТКРЫТЬ СМЕНУ")
            self._open_btn.setToolTip("")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_open()
            return
        super().keyPressEvent(event)
