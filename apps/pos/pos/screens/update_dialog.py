"""SA-7 — диалог проверки/скачивания обновления.

Состояния:
1. Idle/Checking — крутится спиннер «Проверяем GitHub…»
2. UpToDate — «Установлена последняя версия» + кнопка Закрыть
3. UpdateAvailable — показывает версию + release notes + кнопка «Скачать и установить»
4. Downloading — прогресс-бар с %, можно отменить
5. Ready — «Готов запустить установщик» + кнопка «Установить и перезапустить»
6. Error — текст ошибки + Закрыть
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.services.updater import (
    apply_update,
    check_for_update,
    download_installer,
)


class _CheckWorker(QObject):
    success = Signal(object)   # dict | None
    error = Signal(str)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        try:
            info = check_for_update(self.current_version)
            self.success.emit(info)
        except Exception as exc:
            self.error.emit(str(exc))


class _DownloadWorker(QObject):
    progress = Signal(int, int)   # bytes_done, total
    success = Signal(str)         # local path to installer
    error = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            path = download_installer(
                self.url,
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            self.success.emit(path)
        except Exception as exc:
            self.error.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, current_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_version = current_version
        self._threads: list[QThread] = []
        self._installer_path: str | None = None
        self._update_info: dict | None = None

        self.setWindowTitle("Обновление RestOS POS")
        self.setModal(True)
        self.setFixedWidth(540)
        self.setMinimumHeight(420)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()
        self._set_state_checking()
        self._start_check()

    # ---- UI ----

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        root.setSpacing(SPACING["md"])

        self.title_lbl = QLabel("Проверка обновлений…")
        self.title_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        root.addWidget(self.title_lbl)

        self.subtitle_lbl = QLabel(f"Текущая версия: v{self.current_version}")
        self.subtitle_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        root.addWidget(self.subtitle_lbl)

        # Notes / status area
        self.notes = QTextBrowser()
        self.notes.setStyleSheet(
            f"QTextBrowser {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 12px; font-size: 10pt;"
            f"}}"
        )
        self.notes.setOpenExternalLinks(True)
        self.notes.setVisible(False)
        root.addWidget(self.notes, 1)

        # Status text
        self.status_lbl = QLabel("Запрос к GitHub…")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; font-style: italic;"
        )
        root.addWidget(self.status_lbl)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  text-align: center; font-size: 9pt; font-weight: 600;"
            f"}}"
            f"QProgressBar::chunk {{ background: {COLORS['accent_orange']}; border-radius: {RADIUS['sm']}px; }}"
        )
        root.addWidget(self.progress)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(SPACING["sm"])
        btns.addStretch(1)
        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setFixedHeight(40)
        self.close_btn.setMinimumWidth(120)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(self._btn_secondary_qss())
        self.close_btn.clicked.connect(self.reject)
        btns.addWidget(self.close_btn)

        self.action_btn = QPushButton("Скачать и установить")
        self.action_btn.setFixedHeight(40)
        self.action_btn.setMinimumWidth(200)
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setStyleSheet(self._btn_primary_qss())
        self.action_btn.setVisible(False)
        self.action_btn.clicked.connect(self._on_action)
        btns.addWidget(self.action_btn)
        root.addLayout(btns)

    def _btn_primary_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #B85812; }}"
            f"QPushButton:disabled {{ background: #D4A98A; }}"
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

    # ---- States ----

    def _set_state_checking(self) -> None:
        self.title_lbl.setText("Проверка обновлений…")
        self.status_lbl.setText("Запрос к GitHub releases…")
        self.notes.setVisible(False)
        self.progress.setVisible(False)
        self.action_btn.setVisible(False)

    def _set_state_up_to_date(self) -> None:
        self.title_lbl.setText("Обновлений нет")
        self.status_lbl.setText(
            f"У вас установлена последняя версия (v{self.current_version})."
        )
        self.notes.setVisible(False)
        self.progress.setVisible(False)
        self.action_btn.setVisible(False)

    def _set_state_available(self, info: dict) -> None:
        self.title_lbl.setText(f"Доступна версия {info['version']}")
        self.status_lbl.setText("Что нового — см. ниже:")
        notes_html = (
            f"<b>{info['version']}</b><br>"
            f"<a href='{info.get('html_url', '')}'>Открыть в GitHub</a><br><br>"
            f"<pre style='white-space:pre-wrap;font-family:Inter,sans-serif'>"
            f"{(info.get('notes') or 'Описание не предоставлено.')}"
            f"</pre>"
        )
        self.notes.setHtml(notes_html)
        self.notes.setVisible(True)
        self.progress.setVisible(False)
        self.action_btn.setText("Скачать и установить")
        self.action_btn.setVisible(True)
        self.action_btn.setEnabled(True)

    def _set_state_downloading(self) -> None:
        self.title_lbl.setText("Скачиваем обновление…")
        self.status_lbl.setText("Не закрывайте окно.")
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.action_btn.setEnabled(False)
        self.action_btn.setText("Скачиваем…")

    def _set_state_ready(self) -> None:
        self.title_lbl.setText("Готово к установке")
        self.status_lbl.setText(
            "POS закроется и запустится установщик в тихом режиме. "
            "После установки приложение запустится автоматически.",
        )
        self.progress.setVisible(False)
        self.action_btn.setText("Установить и перезапустить")
        self.action_btn.setEnabled(True)

    def _set_state_error(self, msg: str) -> None:
        self.title_lbl.setText("Ошибка")
        self.status_lbl.setText(msg)
        self.notes.setVisible(False)
        self.progress.setVisible(False)
        self.action_btn.setVisible(False)

    # ---- Actions ----

    def _start_check(self) -> None:
        thread = QThread(self)
        worker = _CheckWorker(self.current_version)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_check_result)
        worker.error.connect(self._on_check_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._w = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_check_result(self, info) -> None:
        if info is None:
            self._set_state_up_to_date()
            return
        self._update_info = info
        self._set_state_available(info)

    def _on_check_error(self, msg: str) -> None:
        self._set_state_error(f"Не удалось проверить обновления: {msg}")

    def _on_action(self) -> None:
        # Если уже скачано — запускаем
        if self._installer_path:
            self._apply()
            return
        # Иначе — качаем
        if self._update_info is None:
            return
        url = self._update_info.get("installer_url") or self._update_info.get("zip_url")
        if not url:
            self._set_state_error("В релизе нет installer .exe — обновитесь вручную.")
            return
        if not url.endswith(".exe"):
            self._set_state_error(
                "Авто-обновление поддерживается только через .exe-installer. "
                "Скачайте новый ZIP из релиза вручную.",
            )
            return
        self._set_state_downloading()
        self._start_download(url)

    def _start_download(self, url: str) -> None:
        thread = QThread(self)
        worker = _DownloadWorker(url)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.success.connect(self._on_download_done)
        worker.error.connect(self._on_download_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._w = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int(done * 100 / total)
            self.progress.setValue(pct)
            mb_done = done / 1024 / 1024
            mb_total = total / 1024 / 1024
            self.status_lbl.setText(f"Скачано {mb_done:.1f} из {mb_total:.1f} МБ")
        else:
            self.progress.setRange(0, 0)  # indeterminate

    def _on_download_done(self, path: str) -> None:
        self._installer_path = path
        self._set_state_ready()

    def _on_download_error(self, msg: str) -> None:
        self._set_state_error(f"Ошибка скачивания: {msg}")

    def _apply(self) -> None:
        ans = QMessageBox.question(
            self,
            "Подтверждение",
            "Кассир закроется, начнётся установка. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if ans != QMessageBox.Yes:
            return
        try:
            apply_update(self._installer_path)
        except Exception as exc:
            self._set_state_error(f"Не удалось запустить установщик: {exc}")
