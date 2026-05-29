"""Экран 1. PIN Login — frame "1. PIN Login" в design/pos_cashier.pen."""
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.auth.session import SessionStore
from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.widgets.numpad import Numpad

PIN_MIN_LEN = 4
PIN_MAX_LEN = 6


_DOT_FILLED_QSS = (
    f"background-color: {COLORS['accent_orange']};"
    f"border-radius: 14px;"
)
_DOT_EMPTY_QSS = (
    f"background-color: transparent;"
    f"border: 2px solid {COLORS['border_light']};"
    f"border-radius: 14px;"
)


class _LoginWorker(QObject):
    """Выполняет POST /auth/pin/ в отдельном QThread, чтобы не морозить UI."""

    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, pin: str) -> None:
        super().__init__()
        self.client = client
        self.pin = pin

    def run(self) -> None:
        try:
            data = self.client.post("/auth/pin/", json={"pin": self.pin})
            self.success.emit(data)
        except ApiError as e:
            self.error.emit(e)
        except Exception as e:
            self.error.emit(ApiError("UNKNOWN", str(e), 0))


class PinLoginScreen(QWidget):
    """Frame: 1. PIN Login. Принимает 4–6 цифр PIN, вызывает POST /auth/pin/.

    Сигналы:
        logged_in(user_dict) — успешный логин, токен уже в keyring
    """

    logged_in = Signal(dict)

    def __init__(
        self,
        client: ApiClient | None = None,
        session_store: SessionStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client or ApiClient()
        self.session_store = session_store or SessionStore()
        self._pin: str = ""
        self._thread: QThread | None = None
        self._worker: _LoginWorker | None = None

        self._build()

    # ------- UI -------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"PinLoginScreen {{ background-color: {COLORS['bg_dark']}; }}")
        self.setFocusPolicy(Qt.StrongFocus)

        # Корневой вертикальный layout: статус-бар сверху справа,
        # затем центрированный контент (логотип + карточка).
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        root.setSpacing(SPACING["lg"])

        # Top status bar: слева — text-button «Подключить планшет» (хелпер для
        # онбординга waiter PWA, post-MVP), справа — Pill «Онлайн» + текст.
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        pair_btn = QPushButton("📱 Подключить планшет")
        pair_btn.setCursor(Qt.PointingHandCursor)
        pair_btn.setFlat(True)
        pair_btn.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 12pt;"
            f" background: transparent; border: none;"
        )
        pair_btn.clicked.connect(self._open_pairing_dialog)
        top.addWidget(pair_btn)
        top.addStretch(1)
        top.addWidget(self._build_status_pill())
        sync_lbl = QLabel("Синхронизировано")
        sync_lbl.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 12pt;"
            f" background: transparent; border: none;"
        )
        top.addWidget(sync_lbl)
        root.addLayout(top)

        # Центрированный контент
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(SPACING["lg"])
        center.setAlignment(Qt.AlignCenter)
        center.addStretch(1)
        center.addWidget(self._build_logo(), 0, Qt.AlignHCenter)
        center.addWidget(self._build_card(), 0, Qt.AlignHCenter)
        center.addStretch(1)
        root.addLayout(center, 1)

    def _build_status_pill(self) -> QWidget:
        """Pill-Badge «Онлайн» — дизайн: bg=success_green, radius=14,
        padding=[0,12], height=28; внутри белая точка 8×8 + текст."""
        pill = QFrame()
        pill.setObjectName("statusPill")
        pill.setFixedHeight(28)
        pill.setStyleSheet(
            f"#statusPill {{"
            f"  background-color: {COLORS['success_green']};"
            f"  border-radius: 14px;"
            f"}}"
        )
        h = QHBoxLayout(pill)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(6)
        dot = QLabel("")
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background-color: {COLORS['text_white']}; border-radius: 4px;"
        )
        h.addWidget(dot)
        text = QLabel("Онлайн")
        text.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 12pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        h.addWidget(text)
        return pill

    def _build_logo(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACING["sm"])
        v.setAlignment(Qt.AlignCenter)

        logo = QLabel("R")
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background-color: {COLORS['bg_white']};"
            f"color: {COLORS['primary_blue']};"
            f"border-radius: 28px;"
            f"font-size: 28pt; font-weight: 800;"
        )

        title = QLabel("RestOS")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 24pt; font-weight: 700;"
        )

        v.addWidget(logo, 0, Qt.AlignHCenter)
        v.addWidget(title, 0, Qt.AlignHCenter)
        return wrap

    def _build_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("loginCard")
        card.setFixedWidth(480)
        # Border вместо drop-shadow effect — на macOS shadow effect трогает GPU
        # и тормозит UI. Один тонкий бордер визуально приемлем.
        card.setStyleSheet(
            f"#loginCard {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-radius: {RADIUS['lg']}px;"
            f"  border: 1px solid {COLORS['border_light']};"
            f"}}"
        )

        v = QVBoxLayout(card)
        v.setContentsMargins(40, 24, 40, 24)
        v.setSpacing(SPACING["lg"])
        v.setAlignment(Qt.AlignCenter)

        heading = QLabel("Вход кассира")
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 24pt; font-weight: 700;"
            f" border: none;"
        )

        avatar = self._build_avatar()
        prompt = QLabel("Введите PIN-код")
        prompt.setAlignment(Qt.AlignCenter)
        prompt.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 14pt; border: none;"
        )

        self._dots = self._build_dots()
        self._numpad = Numpad()
        self._numpad.digit_pressed.connect(self._on_digit)
        self._numpad.backspace_pressed.connect(self._on_backspace)
        self._numpad.submit_pressed.connect(self._on_submit)

        self._error = QLabel("")
        self._error.setAlignment(Qt.AlignCenter)
        self._error.setStyleSheet(
            f"color: {COLORS['danger_red']}; font-size: 14pt; font-weight: 500;"
            f"min-height: 18px; border: none;"
        )

        switch = QPushButton("Сменить пользователя →")
        switch.setCursor(Qt.PointingHandCursor)
        switch.setFlat(True)
        switch.setStyleSheet(
            f"color: {COLORS['primary_blue']}; font-size: 14pt; font-weight: 500;"
            f"border: none; background: transparent;"
        )
        switch.setEnabled(False)
        switch.setToolTip("Доступно после Phase 2 (несколько кассиров)")

        v.addWidget(heading)
        v.addWidget(avatar)
        v.addWidget(prompt)
        v.addWidget(self._dots, 0, Qt.AlignHCenter)
        v.addWidget(self._numpad, 0, Qt.AlignHCenter)
        v.addWidget(self._error)
        v.addWidget(switch, 0, Qt.AlignHCenter)
        return card

    def _build_avatar(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACING["sm"])
        v.setAlignment(Qt.AlignCenter)

        circ = QLabel("К")
        circ.setFixedSize(44, 44)
        circ.setAlignment(Qt.AlignCenter)
        circ.setStyleSheet(
            f"background-color: {COLORS['primary_blue']};"
            f"color: {COLORS['text_white']};"
            f"border-radius: 22px;"
            f"font-size: 20pt; font-weight: 700;"
        )

        name = QLabel("Кассир")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 600;"
            f" border: none;"
        )
        v.addWidget(circ, 0, Qt.AlignHCenter)
        v.addWidget(name, 0, Qt.AlignHCenter)
        return wrap

    def _build_dots(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        h.setAlignment(Qt.AlignCenter)
        self._dot_widgets: list[QLabel] = []
        # По дизайну — 4 dots (даже если PIN до 6 цифр, индикатор показывает
        # «первые 4 цифры → подсветка; 5-6-я цифра → последний dot остаётся
        # filled, остальные тоже filled»).
        for _ in range(PIN_MIN_LEN):
            dot = QLabel("")
            dot.setFixedSize(28, 28)
            dot.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            dot.setStyleSheet(_DOT_EMPTY_QSS)
            self._dot_widgets.append(dot)
            h.addWidget(dot)
        return wrap

    def _render_dots(self) -> None:
        # Меняем стиль только у тех виджетов, чьё состояние реально изменилось.
        # Для длины PIN > PIN_MIN_LEN — все dots остаются filled.
        filled_count = min(len(self._pin), len(self._dot_widgets))
        for i, dot in enumerate(self._dot_widgets):
            should_fill = i < filled_count
            current_filled = dot.property("filled") is True
            if should_fill == current_filled:
                continue
            dot.setStyleSheet(_DOT_FILLED_QSS if should_fill else _DOT_EMPTY_QSS)
            dot.setProperty("filled", should_fill)

    # ------- input handlers -------

    def _on_digit(self, d: str) -> None:
        if len(self._pin) >= PIN_MAX_LEN or self._thread is not None:
            return
        self._pin += d
        self._render_dots()
        if self._error.text():
            self._error.setText("")
        if len(self._pin) == PIN_MAX_LEN:
            self._on_submit()

    def _on_backspace(self) -> None:
        if self._thread is not None or not self._pin:
            return
        self._pin = self._pin[:-1]
        self._render_dots()
        if self._error.text():
            self._error.setText("")

    def _on_submit(self) -> None:
        if self._thread is not None:
            return
        if not (PIN_MIN_LEN <= len(self._pin) <= PIN_MAX_LEN):
            self._show_error("PIN должен содержать 4–6 цифр")
            return

        self._numpad.set_submit_enabled(False)

        thread = QThread(self)
        worker = _LoginWorker(self.client, self._pin)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_login_success)
        worker.error.connect(self._on_login_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._numpad.set_submit_enabled(True)

    def _on_login_success(self, data: dict) -> None:
        token = data.get("session_token", "")
        if not token:
            self._show_error("Некорректный ответ сервера")
            return
        self.session_store.token = token
        self._pin = ""
        self._render_dots()
        self._error.setText("")
        self.logged_in.emit(data.get("user", {}))

    def _on_login_error(self, exc: ApiError) -> None:
        self._pin = ""
        self._render_dots()
        if exc.code == "AUTH_INVALID_PIN":
            locked = (exc.detail or {}).get("locked_until")
            if locked:
                try:
                    when = datetime.fromisoformat(locked).strftime("%H:%M")
                    self._show_error(f"Учётка заблокирована до {when}")
                    return
                except ValueError:
                    pass
            self._show_error("Неверный PIN")
        elif exc.code == "NETWORK":
            self._show_error("Нет связи с сервером")
        else:
            self._show_error(exc.message or exc.code)

    def _show_error(self, text: str) -> None:
        self._error.setText(text)

    def _open_pairing_dialog(self) -> None:
        from pos.config import get_pair_url
        from pos.screens.tablet_pairing_screen import TabletPairingDialog

        TabletPairingDialog(get_pair_url(), parent=self).exec()

    # ------- keyboard -------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        text = event.text()
        if text and text.isdigit():
            self._on_digit(text)
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            self._on_backspace()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._on_submit()
            return
        super().keyPressEvent(event)
