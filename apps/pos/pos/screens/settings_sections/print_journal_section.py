"""Журнал печати — список последних PrintJob'ов с preview.

Главный use-case: тестирование флоу заказ/дозаказ/оплата в virtual-режиме —
кассир/dev видит что распечаталось бы на физ. принтер.

Структура:
- Topbar: toggle «Виртуальный режим» + кнопка «Обновить»
- Таблица: дата · тип · принтер · статус (с badge)
- Двойной клик → модалка с text preview
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


KIND_LBL = {
    "guest_receipt": "Чек гостю",
    "kitchen_order": "Кухня",
    "ready_runner": "Готово (бегунок)",
    "cancel_runner": "Отмена",
    "pre_bill": "Пре-чек",
    "z_report": "Z-отчёт",
    "x_report": "X-отчёт",
    "refund_receipt": "Возврат",
    "split_receipt": "Сплит-чек",
    "bar_order": "Бар",
}

STATUS_LBL = {
    "pending": "Ожидает",
    "printing": "Печатает",
    "done": "Готово",
    "failed": "Ошибка",
    "dead": "Сдох",
}

STATUS_COLOR = {
    "pending": "#FBBF24",
    "printing": "#2563EB",
    "done": "#16A34A",
    "failed": "#DC2626",
    "dead": "#7C2D12",
}


class _PreviewDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        job: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._job = job
        self.setWindowTitle(f"Job #{job['id']} — {KIND_LBL.get(job.get('kind'), job.get('kind'))}")
        self.setModal(True)
        self.setMinimumSize(520, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        meta = QLabel(
            f"<b>Принтер:</b> {job.get('printer_name', '—')} · "
            f"<b>Статус:</b> {STATUS_LBL.get(job.get('status'), job.get('status'))} · "
            f"<b>Создан:</b> {(job.get('created_at') or '')[:16].replace('T', ' ')}"
        )
        meta.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" background: transparent; border: none;"
        )
        v.addWidget(meta)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        mono = QFont("Menlo, Consolas, monospace", 10)
        mono.setStyleHint(QFont.Monospace)
        self._text.setFont(mono)
        self._text.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: #0F172A;"
            f"  color: #F1F5F9;"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 12px;"
            f"}}"
        )
        v.addWidget(self._text, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if job.get("status") in ("failed", "dead"):
            retry_btn = QPushButton("Повторить")
            retry_btn.setFixedHeight(36)
            retry_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
                f"}}"
            )
            retry_btn.clicked.connect(self._on_retry)
            btns.addWidget(retry_btn)

        close_btn = QPushButton("Закрыть")
        close_btn.setFixedHeight(36)
        close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
        )
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        v.addLayout(btns)

        self._load_preview()

    def _load_preview(self) -> None:
        try:
            data = self._client.get(
                f"/printing/jobs/{self._job['id']}/preview/"
            )
            text = (data or {}).get("text") if isinstance(data, dict) else None
        except ApiError as e:
            text = f"[Ошибка загрузки превью]\n[{e.code}] {e.message}"
        self._text.setPlainText(text or "(пусто)")

    def _on_retry(self) -> None:
        try:
            self._client.post(
                f"/printing/jobs/{self._job['id']}/retry/",
                json={}, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        QMessageBox.information(self, "Готово", "Задача поставлена в очередь повторно")
        self.accept()


class PrintJournalSection(QWidget):
    """Журнал печати — таблица + preview + toggle virtual mode."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._jobs: list[dict] = []
        self._build()
        self._load_restaurant_state()
        self._load_jobs()

        # Auto-refresh каждые 5 сек (полезно при тестировании флоу)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load_jobs)
        self._timer.start(5000)

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        head = QHBoxLayout()
        head.setContentsMargins(
            SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["md"]
        )
        title = QLabel("Журнал печати")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)

        # Toolbar: virtual toggle + refresh
        tb = QHBoxLayout()
        tb.setContentsMargins(
            SPACING["xl"], 0, SPACING["xl"], SPACING["md"]
        )
        self._virt_chk = QCheckBox("Виртуальный режим (печать в файл, не на железо)")
        self._virt_chk.setStyleSheet(
            f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
        )
        self._virt_chk.stateChanged.connect(self._on_virt_toggle)
        tb.addWidget(self._virt_chk)
        tb.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(36)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 11pt; font-weight: 600;"
            f"}}"
        )
        refresh.clicked.connect(self._load_jobs)
        tb.addWidget(refresh)
        v.addLayout(tb)

        # Hint
        hint = QLabel(
            "Двойной клик по строке — превью того, что было распечатано. "
            "Автообновление каждые 5 секунд."
        )
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" padding: 0 {SPACING['xl']}px {SPACING['sm']}px {SPACING['xl']}px;"
        )
        v.addWidget(hint)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            "#", "Дата", "Тип", "Принтер", "Статус",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  gridline-color: {COLORS['border_light']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {COLORS['bg_gray']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: none; padding: 8px 6px;"
            f"  font-weight: 700; font-size: 10pt;"
            f"}}"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_row_click)

        # Wrap table in margins
        wrap = QFrame()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], SPACING["xl"])
        wv.addWidget(self._table)
        v.addWidget(wrap, 1)

    def _load_restaurant_state(self) -> None:
        try:
            data = self._client.get("/restaurant/")
            resto = data if isinstance(data, dict) else {}
        except ApiError:
            return
        # /restaurant/ может вернуть {'data': {...}} или объект
        if "data" in resto:
            resto = resto["data"]
        self._virt_chk.blockSignals(True)
        self._virt_chk.setChecked(bool(resto.get("printer_virtual_mode", False)))
        self._virt_chk.blockSignals(False)

    def _on_virt_toggle(self, state: int) -> None:
        enabled = self._virt_chk.isChecked()
        try:
            self._client.request(
                "PATCH", "/restaurant/",
                json={"printer_virtual_mode": enabled},
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            # rollback
            self._virt_chk.blockSignals(True)
            self._virt_chk.setChecked(not enabled)
            self._virt_chk.blockSignals(False)
            return

    def _load_jobs(self) -> None:
        try:
            data = self._client.get("/printing/jobs/")
            self._jobs = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError:
            self._jobs = []
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(len(self._jobs))
        for i, j in enumerate(self._jobs):
            self._table.setItem(i, 0, QTableWidgetItem(str(j.get("id", ""))))
            created = (j.get("created_at") or "")[:16].replace("T", " ")
            self._table.setItem(i, 1, QTableWidgetItem(created))
            self._table.setItem(
                i, 2,
                QTableWidgetItem(KIND_LBL.get(j.get("kind"), j.get("kind", ""))),
            )
            printer = j.get("printer_name") or "—"
            self._table.setItem(i, 3, QTableWidgetItem(printer))
            status = j.get("status", "")
            status_item = QTableWidgetItem(STATUS_LBL.get(status, status))
            color = STATUS_COLOR.get(status, COLORS["text_secondary"])
            status_item.setForeground(QBrush(QColor(color)))
            f = status_item.font()
            f.setBold(True)
            status_item.setFont(f)
            self._table.setItem(i, 4, status_item)

    def _on_row_click(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._jobs):
            return
        job = self._jobs[row]
        _PreviewDialog(self._client, job, parent=self).exec()

    def closeEvent(self, event):  # noqa: N802 — Qt naming
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)
