"""Экран 5b. Статус печати чека — комбинация статуса PrintJob и баннера
из frame "23. Принтер недоступен" (id=M6MEl) для failed-состояния.

Открывается после успешной оплаты в PaymentDialog. Подписан на
state.print_job_updated; обновляет UI по реальному статусу job.
"""
import uuid

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon, qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _RetryWorker(QObject):
    success = Signal()
    error = Signal(object)

    def __init__(self, client: ApiClient, job_id: int) -> None:
        super().__init__()
        self.client = client
        self.job_id = job_id

    def run(self) -> None:
        try:
            self.client.post(
                f"/printing/jobs/{self.job_id}/retry/",
                json={},
                extra_headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            self.success.emit()
        except ApiError as e:
            self.error.emit(e)


class ReceiptStatusDialog(QDialog):
    """Модалка статуса печати чека.

    Принимает initial print_job, подписывается на state.print_job_updated,
    обновляет UI: pending/printing → спиннер; done → ✓ + auto-close;
    failed/dead → красный banner «Принтер недоступен» с retry."""

    def __init__(
        self,
        print_job: dict,
        client: ApiClient,
        printer_name: str = "Принтер",
        printer_address: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._job = dict(print_job)
        self._client = client
        self._printer_name = printer_name
        self._printer_address = printer_address
        self._retry_thread: QThread | None = None
        self._retry_worker: _RetryWorker | None = None

        self.setWindowTitle("Чек")
        self.setModal(True)
        self.setFixedWidth(560)

        self._build()
        self._render_state()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Banner ошибки (frame 23) — изначально скрыт
        self._banner = self._build_banner()
        self._banner.setVisible(False)
        outer.addWidget(self._banner)

        # Body
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(40, 40, 40, 40)
        bv.setSpacing(SPACING["lg"])
        bv.setAlignment(Qt.AlignCenter)

        self._icon = QLabel("…")
        self._icon.setFixedSize(80, 80)
        self._icon.setAlignment(Qt.AlignCenter)
        bv.addWidget(self._icon, 0, Qt.AlignHCenter)

        self._title = QLabel("")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        bv.addWidget(self._title)

        self._subtitle = QLabel("")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        self._subtitle.setWordWrap(True)
        bv.addWidget(self._subtitle)

        outer.addWidget(body, 1)

        # Footer: «Закрыть» (на done auto-close, на failed — есть retry в banner)
        footer = QFrame()
        footer.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])
        self._close_btn = QPushButton("Закрыть")
        self._close_btn.setFixedHeight(40)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 24px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        self._close_btn.clicked.connect(self.accept)
        fh.addStretch(1)
        fh.addWidget(self._close_btn)
        outer.addWidget(footer)

    def _build_banner(self) -> QFrame:
        b = QFrame()
        b.setObjectName("printerBanner")
        b.setFixedHeight(54)
        b.setStyleSheet(
            f"#printerBanner {{ background-color: {COLORS['danger_red']}; }}"
        )
        h = QHBoxLayout(b)
        h.setContentsMargins(24, 0, 24, 0)
        h.setSpacing(12)

        icon = QLabel()
        icon.setPixmap(qpixmap("alert-triangle", COLORS["text_white"], 18))
        icon.setStyleSheet("border: none;")
        self._banner_text = QLabel("")
        self._banner_text.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 11pt; font-weight: 700;"
            f" border: none;"
        )
        h.addWidget(icon)
        h.addWidget(self._banner_text)
        h.addStretch(1)

        retry = QPushButton("Повторить")
        retry.setFixedHeight(28)
        retry.setCursor(Qt.PointingHandCursor)
        retry.setStyleSheet(
            f"QPushButton {{"
            f"  background: rgba(255,255,255,0.2);"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 6px;"
            f"  padding: 0 12px;"
            f"  font-size: 10pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.3); }}"
        )
        retry.clicked.connect(self._on_retry)

        hide = QPushButton("Скрыть")
        hide.setFixedHeight(28)
        hide.setCursor(Qt.PointingHandCursor)
        hide.setStyleSheet(retry.styleSheet())
        hide.clicked.connect(lambda: self._banner.setVisible(False))

        h.addWidget(retry)
        h.addWidget(hide)
        return b

    # ------- public -------

    def update_from_event(self, payload: dict) -> None:
        """Слот для state.print_job_updated. Обновляет UI если событие про этот job."""
        if int(payload.get("id", -1)) != int(self._job["id"]):
            return
        self._job.update(payload)
        self._render_state()

    # ------- render -------

    def _render_state(self) -> None:
        status = (self._job.get("status") or "pending").lower()
        if status == "done":
            self._icon.setText("✓")
            self._icon.setStyleSheet(
                f"background-color: #DCFCE7; color: {COLORS['success_green']};"
                f" border-radius: 40px; font-size: 32pt; font-weight: 700;"
            )
            self._title.setText("Чек напечатан")
            self._subtitle.setText("Заказ закрыт. Стол освобождён.")
            self._banner.setVisible(False)
            QTimer.singleShot(2000, self.accept)
            return
        if status in {"failed", "dead"}:
            self._icon.setText("⚠")
            self._icon.setStyleSheet(
                f"background-color: #FEE2E2; color: {COLORS['danger_red']};"
                f" border-radius: 40px; font-size: 28pt; font-weight: 700;"
            )
            retries = int(self._job.get("retries") or 0)
            if status == "dead":
                self._title.setText("Чек не напечатан")
                self._subtitle.setText(
                    f"После {retries} попыток печать не удалась. "
                    f"Заказ закрыт, чек хранится в очереди — "
                    f"можно повторить вручную из admin."
                )
            else:
                self._title.setText("Печать в ожидании")
                self._subtitle.setText(
                    f"Попытка {retries}. Принтер ответит — повторим автоматически."
                )
            address = f" ({self._printer_address})" if self._printer_address else ""
            self._banner_text.setText(
                f"Принтер «{self._printer_name}» недоступен{address}"
            )
            self._banner.setVisible(True)
            return
        if status == "printing":
            self._icon.setText("🖨")
            self._icon.setStyleSheet(
                f"background-color: {COLORS['bg_gray']};"
                f" color: {COLORS['primary_blue']};"
                f" border-radius: 40px; font-size: 28pt;"
            )
            self._title.setText("Печатается…")
            self._subtitle.setText("Подождите, принтер выводит чек.")
            self._banner.setVisible(False)
            return
        # pending (default)
        self._icon.setText("…")
        self._icon.setStyleSheet(
            f"background-color: {COLORS['bg_gray']};"
            f" color: {COLORS['text_secondary']};"
            f" border-radius: 40px; font-size: 28pt; font-weight: 700;"
        )
        self._title.setText("Чек в очереди")
        self._subtitle.setText("Принтер начнёт печать через секунду.")
        self._banner.setVisible(False)

    # ------- handlers -------

    def _on_retry(self) -> None:
        if self._retry_thread is not None:
            return
        thread = QThread(self)
        worker = _RetryWorker(self._client, int(self._job["id"]))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_retry_done)
        worker.error.connect(self._on_retry_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._retry_thread = thread
        self._retry_worker = worker
        thread.start()

    def _on_retry_done(self) -> None:
        self._retry_thread = None
        self._job["status"] = "pending"
        self._render_state()

    def _on_retry_failed(self, exc: ApiError) -> None:
        self._retry_thread = None
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self, "Ошибка повтора",
            f"Не удалось перезапустить печать: {exc.message}",
        )
