"""Drawer «Очередь принтера» — overlay поверх правой части TablesScreen.

Открывается по клику кнопки `Принтер` в топбаре. Кассир видит свежий
state print-очереди и может:
- **Отменить** pending/failed job — POST `/printing/jobs/{id}/cancel/`.
- **Повторить** failed job — POST `/printing/jobs/{id}/retry/`.

Источник данных: GET `/printing/jobs/?limit=50`. Polling каждые 5 сек пока
drawer виден (SSE-подписка отложена на отдельный backend-tracker — простой
polling достаточен для MVP).

Сигналы:
    closed() — клик по крестику; main скрывает drawer.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State

# Локализация (та же, что в PrintJournalSection — синхронизировать вручную
# если расходится; здесь дублируем чтобы не тащить зависимость на screen).
KIND_LBL = {
    "guest_receipt": "Чек гостю",
    "kitchen_order": "Кухня",
    "bar_order": "Бар",
    "ready_runner": "Готово",
    "cancel_runner": "Отмена",
    "pre_bill": "Пре-чек",
    "z_report": "Z-отчёт",
    "x_report": "X-отчёт",
    "refund_receipt": "Возврат",
    "split_receipt": "Сплит-чек",
}

STATUS_LBL = {
    "pending": "Ожидает",
    "printing": "Печатает",
    "done": "Готово",
    "failed": "Ошибка",
    "dead": "Отменён",
}

STATUS_COLOR = {
    "pending": COLORS["warning_yellow"],
    "printing": COLORS["primary_blue"],
    "done": COLORS["success_green"],
    "failed": COLORS["danger_red"],
    "dead": COLORS["text_secondary"],
}

FILTERS = [
    ("active", "Активные"),  # pending + printing + failed
    ("pending", "Ожидают"),
    ("failed", "Ошибки"),
    ("done", "Готовы"),
    ("all", "Все"),
]


class PrinterDrawer(QFrame):
    """Overlay-панель 360px (= OrderDetailPanel ширина) на всю высоту окна,
    с оранжевым accent-border slева как payment/pre-bill."""

    closed = Signal()

    # Единый размер для всех overlay-drawer'ов справа (как OrdersDrawer).
    PANEL_WIDTH = 360
    POLL_INTERVAL_MS = 5000

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._jobs: list[dict] = []
        self._filter: str = "active"

        self.setObjectName("printerDrawer")
        self.setFixedWidth(PrinterDrawer.PANEL_WIDTH)
        self.setStyleSheet(
            f"#printerDrawer {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 4px solid {COLORS['accent_orange']};"
            f"}}"
        )
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Drawer всегда overlay (y=0, full-height) — host TablesScreen
        # читает этот флаг в _position_drawer и перекрывает правую панель.
        self.overlay_mode: bool = True

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(PrinterDrawer.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._fetch_jobs)

        self._build()

    # -------- public API --------

    def refresh(self) -> None:
        """Принудительная перезагрузка списка."""
        self._fetch_jobs()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._fetch_jobs()
        self._poll_timer.start()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._poll_timer.stop()

    # -------- build --------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("printerDrawerHeader")
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"#printerDrawerHeader {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 0, 12, 0)
        h.setSpacing(8)

        title_icon = QLabel()
        title_icon.setPixmap(qicon("printer", COLORS["text_primary"], 18).pixmap(18, 18))
        title_icon.setStyleSheet("background: transparent; border: none;")
        h.addWidget(title_icon)

        title = QLabel("Очередь принтера")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 15pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        h.addWidget(title)
        h.addStretch(1)

        close_btn = QPushButton()
        close_btn.setFixedSize(36, 36)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close_btn.setIconSize(QSize(18, 18))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']};"
            f" border-radius: 6px; }}"
        )
        close_btn.clicked.connect(self.closed.emit)
        h.addWidget(close_btn)
        root.addWidget(header)

        # Filter chips
        chips_bar = QFrame()
        chips_bar.setFixedHeight(48)
        chips_bar.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        cb = QHBoxLayout(chips_bar)
        cb.setContentsMargins(12, 8, 12, 8)
        cb.setSpacing(6)

        self._chip_buttons: dict[str, QPushButton] = {}
        for key, label in FILTERS:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda _c=False, k=key: self._on_chip(k))
            self._chip_buttons[key] = btn
            cb.addWidget(btn)
        cb.addStretch(1)
        root.addWidget(chips_bar)

        # List (scroll)
        self._list_holder = QWidget()
        self._list_holder.setStyleSheet(f"background: {COLORS['bg_white']};")
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_white']}; border: none; }}"
        )
        scroll.setWidget(self._list_holder)
        root.addWidget(scroll, 1)

        self._render_chips()
        self._render_list()

    def _render_chips(self) -> None:
        for key, btn in self._chip_buttons.items():
            active = (key == self._filter)
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {COLORS['accent_orange']};"
                    f"  color: {COLORS['text_white']};"
                    f"  border: none; border-radius: 14px;"
                    f"  padding: 4px 12px; font-size: 10pt; font-weight: 700;"
                    f"}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {COLORS['bg_white']};"
                    f"  color: {COLORS['text_secondary']};"
                    f"  border: 1px solid {COLORS['border_light']};"
                    f"  border-radius: 14px;"
                    f"  padding: 4px 12px; font-size: 10pt; font-weight: 600;"
                    f"}}"
                    f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
                )

    def _on_chip(self, key: str) -> None:
        if self._filter == key:
            return
        self._filter = key
        self._render_chips()
        self._render_list()

    # -------- fetching --------

    def _fetch_jobs(self) -> None:
        try:
            resp = self.state.client.get("/printing/jobs/")
        except ApiError:
            return
        if isinstance(resp, dict) and "results" in resp:
            self._jobs = list(resp.get("results") or [])
        elif isinstance(resp, list):
            self._jobs = resp
        else:
            self._jobs = []
        self._render_list()

    def _filtered_jobs(self) -> list[dict]:
        if self._filter == "all":
            return self._jobs
        if self._filter == "active":
            return [
                j for j in self._jobs
                if j.get("status") in ("pending", "printing", "failed")
            ]
        return [j for j in self._jobs if j.get("status") == self._filter]

    # -------- rendering --------

    def _clear_list(self) -> None:
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _render_list(self) -> None:
        self._clear_list()
        jobs = self._filtered_jobs()
        if not jobs:
            empty = QLabel("Очередь пуста")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
                f" font-style: italic; padding: 32px 0;"
                f" background: transparent; border: none;"
            )
            self._list_layout.addWidget(empty)
            return
        for j in jobs[:50]:
            self._list_layout.addWidget(self._build_row(j))

    def _build_row(self, job: dict) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        v = QVBoxLayout(row)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        # Верхняя строка: kind + status badge
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        kind = job.get("kind") or ""
        kind_lbl = QLabel(KIND_LBL.get(kind, kind))
        kind_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        top.addWidget(kind_lbl)
        top.addStretch(1)

        status = job.get("status") or "pending"
        badge = QLabel(STATUS_LBL.get(status, status))
        badge.setStyleSheet(
            f"QLabel {{"
            f"  background: {STATUS_COLOR.get(status, COLORS['text_secondary'])};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 10px;"
            f"  padding: 2px 10px;"
            f"  font-size: 9pt; font-weight: 700;"
            f"}}"
        )
        top.addWidget(badge)
        v.addLayout(top)

        # Subline: принтер + время + retries
        printer_name = job.get("printer_name") or "—"
        created = self._fmt_time(job.get("created_at"))
        retries = int(job.get("retries") or 0)
        sub_parts = [printer_name, created]
        if retries:
            sub_parts.append(f"повтор {retries}")
        sub = QLabel(" • ".join(s for s in sub_parts if s))
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        v.addWidget(sub)

        # Error preview (если failed/dead и есть error)
        err = (job.get("error") or "").strip()
        if err and status in ("failed", "dead"):
            err_short = err.replace("\n", " ")[:120]
            err_lbl = QLabel(err_short)
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet(
                f"color: {COLORS['danger_red']}; font-size: 9pt;"
                f" background: transparent; border: none;"
            )
            v.addWidget(err_lbl)

        # Action buttons (visibility / enabled зависит от status)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(6)
        actions.addStretch(1)

        job_id = int(job.get("id") or 0)
        if status in ("pending", "failed"):
            cancel_btn = QPushButton("  Отменить")
            cancel_btn.setIcon(qicon("x", COLORS["danger_red"], 14))
            cancel_btn.setIconSize(QSize(14, 14))
            cancel_btn.setFixedHeight(30)
            cancel_btn.setCursor(Qt.PointingHandCursor)
            cancel_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['danger_red']};"
                f"  border: 1px solid {COLORS['danger_red']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 10px; font-size: 10pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: #FEF2F2; }}"
            )
            cancel_btn.clicked.connect(
                lambda _c=False, jid=job_id: self._on_cancel(jid),
            )
            actions.addWidget(cancel_btn)

        if status == "failed":
            retry_btn = QPushButton("  Повторить")
            retry_btn.setIcon(qicon("refresh-cw", COLORS["primary_blue"], 14))
            retry_btn.setIconSize(QSize(14, 14))
            retry_btn.setFixedHeight(30)
            retry_btn.setCursor(Qt.PointingHandCursor)
            retry_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['primary_blue']};"
                f"  border: 1px solid {COLORS['primary_blue']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 10px; font-size: 10pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: #EFF6FF; }}"
            )
            retry_btn.clicked.connect(
                lambda _c=False, jid=job_id: self._on_retry(jid),
            )
            actions.addWidget(retry_btn)

        v.addLayout(actions)
        return row

    # -------- actions --------

    def _on_cancel(self, job_id: int) -> None:
        try:
            self.state.client.post(
                f"/printing/jobs/{job_id}/cancel/",
                json={},
                extra_headers={"Idempotency-Key": str(uuid4())},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка отмены", f"Не удалось отменить: {e.message}",
            )
            return
        self._fetch_jobs()

    def _on_retry(self, job_id: int) -> None:
        try:
            self.state.client.post(
                f"/printing/jobs/{job_id}/retry/",
                json={},
                extra_headers={"Idempotency-Key": str(uuid4())},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка повтора", f"Не удалось повторить: {e.message}",
            )
            return
        self._fetch_jobs()

    @staticmethod
    def _fmt_time(iso: str | None) -> str:
        if not iso:
            return ""
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            local = dt.astimezone()
            return local.strftime("%H:%M:%S")
        except Exception:
            return str(iso)[:16].replace("T", " ")
