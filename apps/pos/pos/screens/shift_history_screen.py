"""Архив смен — список всех закрытых/открытых смен с фильтрами и переходом
в ShiftReportScreen.

Доступен из Настройки → Отчёты → «Архив смен». Позволяет:
- Просматривать смены за период (date range)
- Фильтровать по статусу (open / closed)
- Открыть конкретную смену → ShiftReportScreen
"""
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State
from pos.widgets.sidebar import Sidebar


class ShiftHistoryScreen(QWidget):
    """Сигналы:
        back_requested() — кнопка «Назад»
        open_shift_report(shift_id) — клик по строке смены
        logout_requested()
    """

    back_requested = Signal()
    open_shift_report = Signal(int)
    logout_requested = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._shifts: list[dict] = []
        self._total: int = 0
        self._page: int = 1
        self._page_size: int = 50
        self._build()

    # -------- public --------

    def reload(self, *, page: int = 1, append: bool = False) -> None:
        try:
            params: dict[str, str] = {
                "page": str(page),
                "page_size": str(self._page_size),
            }
            resp = self.state.client.get("/shifts/", params=params)
            if isinstance(resp, dict) and "meta" in resp:
                items = resp.get("data", [])
                self._total = int(resp.get("meta", {}).get("total", 0))
            elif isinstance(resp, list):
                items = resp
                self._total = len(items)
            else:
                items = (resp or {}).get("data", [])
                self._total = len(items)
            if append:
                self._shifts.extend(items)
            else:
                self._shifts = list(items)
            self._page = page
        except ApiError:
            if not append:
                self._shifts = []
                self._total = 0
        self._render()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"ShiftHistoryScreen {{ background-color: {COLORS['bg_light']}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(active="settings")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(
            SPACING["xl"] + 8, SPACING["lg"], SPACING["xl"] + 8, SPACING["lg"],
        )
        cv.setSpacing(SPACING["md"])

        cv.addWidget(self._build_topbar())
        cv.addWidget(self._build_table_card(), 1)
        cv.addLayout(self._build_pagination_row())
        root.addWidget(center, 1)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        back = QPushButton("← Назад")
        back.setFixedHeight(40)
        back.setMinimumWidth(120)
        back.setCursor(Qt.PointingHandCursor)
        back.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        back.clicked.connect(self.back_requested.emit)
        h.addWidget(back)

        title = QLabel("Архив смен")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        h.addWidget(title)
        h.addStretch(1)
        return bar

    # Колонки: №, Дата, Кассир, Статус, Выручка, Расхождение
    COL_WIDTHS = [60, 160, 180, 100, 130, 0]
    COL_LABELS = ["№", "Период", "Кассир", "Статус", "Выручка", "Расхождение"]

    def _build_table_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("histCard")
        card.setStyleSheet(
            f"#histCard {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._build_header_row())

        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet(
            f"background: {COLORS['bg_white']}; border: none;"
        )
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_white']}; border: none; }}"
        )
        scroll.setWidget(self._rows_holder)
        v.addWidget(scroll, 1)
        return card

    def _build_header_row(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(44)
        h.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_gray']};"
            f"  border: none;"
            f"  border-top-left-radius: {RADIUS['sm']}px;"
            f"  border-top-right-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(0)
        for i, label in enumerate(self.COL_LABELS):
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 11pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            w = self.COL_WIDTHS[i]
            if w > 0:
                lbl.setFixedWidth(w)
                layout.addWidget(lbl)
            else:
                layout.addWidget(lbl, 1)
        return h

    def _build_pagination_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        self._page_count_lbl = QLabel("")
        self._page_count_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        h.addWidget(self._page_count_lbl)
        h.addStretch(1)

        self._load_more_btn = QPushButton("Загрузить ещё")
        self._load_more_btn.setFixedHeight(36)
        self._load_more_btn.setMinimumWidth(160)
        self._load_more_btn.setEnabled(False)
        self._load_more_btn.setCursor(Qt.PointingHandCursor)
        self._load_more_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        self._load_more_btn.clicked.connect(
            lambda: self.reload(page=self._page + 1, append=True)
        )
        h.addWidget(self._load_more_btn)
        return h

    # -------- render --------

    def _render(self) -> None:
        # Очистить старые строки
        while self._rows_layout.count():
            child = self._rows_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if self._total > 0:
            self._page_count_lbl.setText(
                f"Показано {len(self._shifts)} из {self._total}"
            )
        else:
            self._page_count_lbl.setText("")
        self._load_more_btn.setEnabled(len(self._shifts) < self._total)

        if not self._shifts:
            empty = QLabel("Закрытых смен пока нет")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt; font-style: italic;"
                f" padding: 60px 0; background: transparent; border: none;"
            )
            self._rows_layout.addWidget(empty)
            return

        for i, s in enumerate(self._shifts):
            self._rows_layout.addWidget(self._build_data_row(s, idx=i))

    def _build_data_row(self, s: dict, *, idx: int) -> QWidget:
        row = QFrame()
        row.setFixedHeight(56)
        bg = COLORS["bg_gray"] if (idx % 2 == 1) else COLORS["bg_white"]
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {bg}; border: none;"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
            f"QFrame:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        row.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(0)

        def cell(text: str, *, width: int, bold: bool = False, color: str | None = None) -> QLabel:
            c = color or COLORS["text_primary"]
            weight = 700 if bold else 400
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {c}; font-size: 12pt; font-weight: {weight};"
                f" border: none; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if width > 0:
                lbl.setFixedWidth(width)
            return lbl

        h.addWidget(cell(f"#{s.get('number', '?')}", width=self.COL_WIDTHS[0]))

        opened = self._fmt(s.get("opened_at"))
        closed = self._fmt(s.get("closed_at")) or "сейчас"
        period = f"{opened} → {closed}" if opened else "—"
        h.addWidget(cell(period, width=self.COL_WIDTHS[1]))

        h.addWidget(cell(s.get("cashier_name") or "—", width=self.COL_WIDTHS[2]))

        status = s.get("status")
        st_label = "Открыта" if status == "open" else "Закрыта"
        st_color = "#16A34A" if status == "open" else COLORS["text_secondary"]
        h.addWidget(cell(st_label, width=self.COL_WIDTHS[3], color=st_color))

        revenue = self._fmt_revenue(s)
        h.addWidget(cell(f"{revenue} TJS", width=self.COL_WIDTHS[4], bold=True))

        disc = s.get("discrepancy")
        if disc is None:
            disc_text, disc_color = "—", COLORS["text_secondary"]
        else:
            disc_color = (
                "#16A34A" if str(disc).startswith("0") else "#DC2626"
            )
            disc_text = f"{disc} TJS"
        h.addWidget(cell(disc_text, width=self.COL_WIDTHS[5], color=disc_color))

        # Кнопка-action в конце
        open_btn = QPushButton("Открыть")
        open_btn.setFixedHeight(32)
        open_btn.setMinimumWidth(100)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"  padding: 6px 12px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_white']}; }}"
        )
        open_btn.clicked.connect(
            lambda _c=False, sid=int(s["id"]): self.open_shift_report.emit(sid)
        )
        h.addWidget(open_btn)
        return row

    @staticmethod
    def _fmt(iso: str | None) -> str:
        if not iso:
            return ""
        try:
            return datetime.fromisoformat(
                iso.replace("Z", "+00:00")
            ).strftime("%d.%m %H:%M")
        except Exception:
            return iso[:16]

    @staticmethod
    def _fmt_revenue(s: dict) -> str:
        """Сумма cash+card+transfer revenue."""
        from decimal import Decimal

        total = Decimal("0")
        for k in ("cash_revenue", "card_revenue", "transfer_revenue"):
            try:
                total += Decimal(str(s.get(k) or 0))
            except Exception:
                pass
        return f"{total}"

    # -------- handlers --------

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        else:
            self.back_requested.emit()
