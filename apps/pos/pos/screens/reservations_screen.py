"""Экран резерваций — список с фильтрами и переходом к управлению.

Доступен из Настройки → Отчёты → «Резервации». Показывает:
- Tabs: «Активные» / «Сегодня» / «Архив»
- Кнопка «+ Новая резервация» → ReservationFormDialog
- Таблица: время, стол, гость, гостей, статус, действия (Подтвердить/Отменить/Усадить/Не пришёл)
"""
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
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
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State
from pos.widgets.sidebar import Sidebar


STATUS_LABEL = {
    "pending": "Ожидает",
    "confirmed": "Подтв.",
    "seated": "Гости пришли",
    "cancelled": "Отменена",
    "no_show": "Не пришли",
}

STATUS_COLOR = {
    "pending": COLORS["accent_orange"],
    "confirmed": "#16A34A",
    "seated": COLORS["primary_blue"],
    "cancelled": COLORS["text_secondary"],
    "no_show": COLORS["danger_red"],
}


class ReservationsScreen(QWidget):
    """Сигналы:
        back_requested()
        logout_requested()
    """

    back_requested = Signal()
    logout_requested = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._items: list[dict] = []
        self._mode: str = "active"  # active | today | all
        self._build()

    # -------- public --------

    def reload(self) -> None:
        params: dict[str, str] = {}
        if self._mode == "active":
            params["active"] = "true"
        elif self._mode == "today":
            today = date.today().isoformat()
            params["from"] = today
            params["to"] = today
        try:
            resp = self.state.client.get("/reservations/", params=params)
            if isinstance(resp, dict) and "data" in resp:
                self._items = resp["data"]
            elif isinstance(resp, list):
                self._items = resp
            else:
                self._items = []
        except ApiError:
            self._items = []
        self._render()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"ReservationsScreen {{ background-color: {COLORS['bg_light']}; }}"
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
        cv.addWidget(self._build_tabs())
        cv.addWidget(self._build_table_card(), 1)
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

        title = QLabel("Резервации")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        h.addWidget(title)
        h.addStretch(1)

        self._add_btn = QPushButton("+ Новая резервация")
        self._add_btn.setFixedHeight(40)
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #DC6803; }}"
        )
        self._add_btn.clicked.connect(self._on_new)
        h.addWidget(self._add_btn)
        return bar

    def _build_tabs(self) -> QWidget:
        bar = QFrame()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        self._tab_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("active", "Активные"),
            ("today", "На сегодня"),
            ("all", "Все"),
        ):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setMinimumHeight(36)
            btn.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            btn.setStyleSheet(self._tab_qss(active=(key == self._mode)))
            self._tab_buttons[key] = btn
            h.addWidget(btn)

        h.addStretch(1)
        return bar

    def _tab_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 8px;"
                f"  padding: 6px 18px; font-size: 11pt; font-weight: 700;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 6px 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def set_mode(self, mode: str) -> None:
        if mode not in {"active", "today", "all"}:
            return
        self._mode = mode
        for k, btn in self._tab_buttons.items():
            btn.setStyleSheet(self._tab_qss(active=(k == mode)))
        self.reload()

    COL_LABELS = ["Время", "Стол", "Гость", "Тел.", "Гостей", "Статус", "Действия"]
    COL_WIDTHS = [110, 110, 180, 130, 80, 130, 0]

    def _build_table_card(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
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

    # -------- render --------

    def _render(self) -> None:
        while self._rows_layout.count():
            child = self._rows_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._items:
            empty = QLabel("Резерваций нет")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt;"
                f" font-style: italic; padding: 60px 0;"
                f" background: transparent; border: none;"
            )
            self._rows_layout.addWidget(empty)
            return

        for i, r in enumerate(self._items):
            self._rows_layout.addWidget(self._build_row(r, idx=i))

    def _build_row(self, r: dict, *, idx: int) -> QWidget:
        row = QFrame()
        row.setFixedHeight(56)
        bg = COLORS["bg_gray"] if (idx % 2 == 1) else COLORS["bg_white"]
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {bg}; border: none;"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(0)

        def cell(text: str, *, width: int, color: str | None = None, bold: bool = False) -> QLabel:
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

        h.addWidget(cell(self._fmt_dt(r.get("scheduled_at")), width=self.COL_WIDTHS[0], bold=True))
        h.addWidget(cell(r.get("table_name") or "—", width=self.COL_WIDTHS[1]))
        h.addWidget(cell(r.get("customer_name") or "—", width=self.COL_WIDTHS[2]))
        h.addWidget(cell(r.get("customer_phone") or "—", width=self.COL_WIDTHS[3]))
        h.addWidget(cell(str(r.get("party_size") or 0), width=self.COL_WIDTHS[4]))

        st = r.get("status") or "pending"
        h.addWidget(cell(
            STATUS_LABEL.get(st, st),
            width=self.COL_WIDTHS[5],
            color=STATUS_COLOR.get(st),
            bold=True,
        ))

        # Actions wrapper
        actions = QWidget()
        actions.setStyleSheet("background: transparent; border: none;")
        aw = QHBoxLayout(actions)
        aw.setContentsMargins(0, 0, 0, 0)
        aw.setSpacing(SPACING["sm"])

        rid = int(r["id"])
        if st == "pending":
            aw.addWidget(self._mk_action("Подтвердить", "primary",
                lambda: self._do_action(rid, "confirm")))
        if st in ("pending", "confirmed"):
            aw.addWidget(self._mk_action("Усадить", "primary",
                lambda: self._do_action(rid, "seat")))
            aw.addWidget(self._mk_action("Не пришли", "danger",
                lambda: self._do_action(rid, "no_show")))
            aw.addWidget(self._mk_action("Отмена", "outline",
                lambda: self._do_action(rid, "cancel")))
        aw.addStretch(1)
        h.addWidget(actions, 1)
        return row

    def _mk_action(self, label: str, kind: str, handler) -> QPushButton:
        b = QPushButton(label)
        b.setFixedHeight(30)
        b.setMinimumWidth(96)
        b.setCursor(Qt.PointingHandCursor)
        if kind == "primary":
            qss = (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 6px;"
                f"  padding: 4px 10px; font-size: 10pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #DC6803; }}"
            )
        elif kind == "danger":
            qss = (
                f"QPushButton {{"
                f"  background: {COLORS['danger_red']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 6px;"
                f"  padding: 4px 10px; font-size: 10pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #B91C1C; }}"
            )
        else:
            qss = (
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 6px;"
                f"  padding: 4px 10px; font-size: 10pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
        b.setStyleSheet(qss)
        b.clicked.connect(handler)
        return b

    def _do_action(self, reservation_id: int, action: str) -> None:
        try:
            self.state.client.post(
                f"/reservations/{reservation_id}/{action}/", json={},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"{e.message}\n[{e.code}]",
            )
            return
        self.reload()
        # Стол мог изменить статус (или появилась/закрылась резервация)
        if hasattr(self.state, "refresh"):
            self.state.refresh()

    def _on_new(self) -> None:
        from pos.screens.reservation_form_dialog import ReservationFormDialog

        dlg = ReservationFormDialog(
            client=self.state.client,
            tables=list(self.state.tables),
            parent=self,
        )
        dlg.reservation_created.connect(lambda _r: self.reload())
        dlg.exec()
        if hasattr(self.state, "refresh"):
            self.state.refresh()

    @staticmethod
    def _fmt_dt(iso: str | None) -> str:
        if not iso:
            return "—"
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%d.%m %H:%M")
        except Exception:
            return iso[:16]

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        else:
            self.back_requested.emit()
