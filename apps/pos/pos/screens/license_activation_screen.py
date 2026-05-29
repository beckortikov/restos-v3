"""SA-7 — экран активации POS на конкретной машине.

Показывается перед PIN-login если ~/.restos-pos/license.json отсутствует
или middleware/permission ответил 403 MACHINE_MISMATCH.

UX:
1. Юзер видит HWID этой машины (BIOS UUID), может скопировать в буфер.
2. Юзер вводит «ключ активации», полученный от вендора.
3. POST /license/activate/ → если ОК, save в license.json, signal success.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.hwid import collect_hardware_uuid, is_valid_hwid
from pos.resources.license_store import save_license
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _ActivateWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, key: str, hwid: str) -> None:
        super().__init__()
        self.client = client
        self.key = key
        self.hwid = hwid

    def run(self) -> None:
        try:
            data = self.client.post(
                "/license/activate/",
                json={"license_key": self.key, "hardware_uuid": self.hwid},
            )
            payload = data.get("data") if isinstance(data, dict) and "data" in data else data
            self.success.emit(payload if isinstance(payload, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class LicenseActivationScreen(QWidget):
    """Экран активации (показывается до PIN-login).

    Сигналы:
        activated(dict) — успешная активация, payload от сервера
        cancelled() — пользователь нажал «Отмена» / Esc
    """

    activated = Signal(dict)
    cancelled = Signal()

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._hwid = collect_hardware_uuid()
        self._threads: list[QThread] = []
        self.setStyleSheet(f"background: {COLORS['bg_light']};")
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFixedWidth(560)
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['lg']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"],
        )
        v.setSpacing(SPACING["lg"])

        title = QLabel("Активация POS на этой машине")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 800; border: none;"
        )
        v.addWidget(title)

        intro = QLabel(
            "Программа запускается на конкретном компьютере и требует "
            "одноразовой активации. Скопируйте ID машины ниже и отправьте "
            "поставщику — он выдаст вам ключ.",
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; border: none;"
        )
        v.addWidget(intro)

        # HWID display
        hwid_label = QLabel("ID этой машины (HWID):")
        hwid_label.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; font-weight: 700; border: none;"
        )
        v.addWidget(hwid_label)

        hwid_row = QHBoxLayout()
        self._hwid_field = QLineEdit(self._hwid)
        self._hwid_field.setReadOnly(True)
        self._hwid_field.setFixedHeight(40)
        self._hwid_field.setStyleSheet(self._field_qss(mono=True))
        hwid_row.addWidget(self._hwid_field, 1)

        copy_btn = QPushButton("Копировать")
        copy_btn.setFixedHeight(40)
        copy_btn.setMinimumWidth(120)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(self._btn_secondary_qss())
        copy_btn.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(copy_btn)
        v.addLayout(hwid_row)

        if not is_valid_hwid(self._hwid):
            warn = QLabel(
                "⚠ Не удалось получить стабильный ID этой машины (часто на VM "
                "или из-за прав). Запустите POS как администратор и попробуйте "
                "снова, или обратитесь к поставщику.",
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"color: {COLORS['danger_red']};"
                f" font-size: 9.5pt; border: none; padding: 6px 0;"
            )
            v.addWidget(warn)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        v.addWidget(sep)

        # License key input
        key_label = QLabel("Ключ активации (от поставщика):")
        key_label.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; font-weight: 700; border: none;"
        )
        v.addWidget(key_label)

        self._key_field = QLineEdit()
        self._key_field.setPlaceholderText("ABCD-EFGH-IJKL-MNOP")
        self._key_field.setFixedHeight(44)
        self._key_field.setStyleSheet(self._field_qss())
        self._key_field.returnPressed.connect(self._submit)
        v.addWidget(self._key_field)

        # Footer buttons
        foot = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._btn_secondary_qss())
        cancel.clicked.connect(self.cancelled.emit)
        foot.addWidget(cancel)
        foot.addStretch(1)

        self._activate_btn = QPushButton("Активировать")
        self._activate_btn.setFixedHeight(44)
        self._activate_btn.setMinimumWidth(160)
        self._activate_btn.setCursor(Qt.PointingHandCursor)
        self._activate_btn.setStyleSheet(self._btn_primary_qss())
        self._activate_btn.clicked.connect(self._submit)
        foot.addWidget(self._activate_btn)
        v.addLayout(foot)

        root.addWidget(card)

    # ---- styles ----

    def _field_qss(self, *, mono: bool = False) -> str:
        font = "'Courier New', monospace" if mono else "Inter"
        return (
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; color: {COLORS['text_primary']};"
            f"  font-family: {font}; font-size: 11pt;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {COLORS['accent_orange']}; }}"
        )

    def _btn_primary_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 22px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #B85812; }}"
        )

    def _btn_secondary_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    # ---- handlers ----

    def _copy_hwid(self) -> None:
        QGuiApplication.clipboard().setText(self._hwid)
        QMessageBox.information(
            self, "Скопировано",
            "ID машины скопирован в буфер обмена. Отправьте его поставщику.",
        )

    def _submit(self) -> None:
        key = self._key_field.text().strip()
        if not key:
            QMessageBox.warning(self, "Ошибка", "Введите ключ активации")
            return
        if not is_valid_hwid(self._hwid):
            QMessageBox.warning(
                self, "Ошибка",
                "Не удалось получить стабильный ID этой машины. "
                "Запустите POS как администратор.",
            )
            return
        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Активируем…")

        thread = QThread(self)
        worker = _ActivateWorker(self._client, key, self._hwid)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_success)
        worker.error.connect(self._on_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_success(self, payload: dict) -> None:
        # Сохраняем локально
        key = self._key_field.text().strip()
        save_license(key, self._hwid)
        first = bool(payload.get("first_activation"))
        plan = payload.get("plan", "")
        rest_name = payload.get("restaurant_name", "")
        msg = (
            f"Готово! Лицензия привязана к этой машине.\n\n"
            f"Ресторан: {rest_name}\nТариф: {plan}\n"
            + ("Это первая активация." if first else "Повторная активация (тот же ПК).")
        )
        QMessageBox.information(self, "Активация успешна", msg)
        self.activated.emit(payload)

    def _on_error(self, exc: ApiError) -> None:
        self._activate_btn.setEnabled(True)
        self._activate_btn.setText("Активировать")
        code = getattr(exc, "code", "ERROR")
        msg = getattr(exc, "message", str(exc))
        # Human-readable messages для типовых кодов
        if code == "LICENSE_NOT_FOUND":
            msg = "Ключ не найден. Проверьте корректность или обратитесь к поставщику."
        elif code == "LICENSE_BLOCKED":
            msg = f"Лицензия заблокирована. {msg}"
        elif code == "MACHINE_MISMATCH":
            msg = (
                "Этот ключ уже привязан к другой машине. "
                "Свяжитесь с поставщиком — он сбросит привязку, и активацию "
                "можно будет повторить."
            )
        QMessageBox.warning(self, "Не удалось активировать", msg)
