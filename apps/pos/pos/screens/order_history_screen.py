"""История заказов — frame "12. История заказов" (id=l9IJB) в design/pos_cashier.pen.

Read-only таблица закрытых/отменённых заказов с фильтрами:
- shift_id (когда выбрана текущая смена) — «Закрытые сегодня»
- без фильтра — весь архив

MVP-cut от дизайна:
- Поиск по номеру/столу/времени (Phase 5+: backend filter уже есть)
- Кнопка «Фильтры» (Phase 5+)
- Кнопка «Возврат» — disabled, ведёт на Phase 4
- Pagination — backend StandardPagination, в MVP грузим первую страницу

MVP-keep:
- Tabs «Активные / Закрытые / Архив»
- Cashier label справа
- Таблица: №, Время, Стол, Сумма, Оплата, Кассир, Действия
"""
from datetime import date, datetime
from datetime import timezone as tz

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiError
from pos.resources.icons import qicon, qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State
from pos.widgets.sidebar import Sidebar


class OrderHistoryScreen(QWidget):
    """Сигналы:
        nav_to_active() — клик по табу «Активные заказы»
        logout_requested()
        refund_requested(order_id) — Phase 4
    """

    nav_to_active = Signal()
    logout_requested = Signal()
    refund_requested = Signal(int)
    reprint_requested = Signal(int)

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._cashier_name: str = ""
        self._shift_no: int = 0
        self._mode: str = "today"  # "today" | "archive"
        self._orders: list[dict] = []
        self._search_query: str = ""
        self._total: int = 0
        self._page: int = 1
        self._page_size: int = 50
        self._build()
        # Debounce-таймер для поиска: 350мс после последнего ввода → reload.
        from PySide6.QtCore import QTimer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._do_search_reload)

    # -------- public --------

    def set_cashier(self, name: str, shift_no: int = 0) -> None:
        self._cashier_name = name
        self._shift_no = shift_no
        self._render_cashier_label()

    def reload(self, *, page: int = 1, append: bool = False) -> None:
        """Тянет /orders/ с фильтрами + пагинацией.

        page=1 + append=False → replace список (новый поиск/фильтр).
        page>1 + append=True → дозагрузка следующей страницы.
        """
        try:
            params: dict[str, str] = {
                "status": "done,cancelled",
                "page": str(page),
                "page_size": str(self._page_size),
            }
            if self._mode == "today":
                # Жёстко ограничиваем сегодняшним днём: не зависим от смены
                # (смены может не быть или быть длинной), пользователь хочет
                # «только сегодняшние» закрытые заказы.
                today_str = date.today().isoformat()
                params["from"] = today_str
                params["to"] = today_str
                shift = self.state.current_shift
                if shift and shift.get("id"):
                    params["shift"] = str(shift["id"])
            if self._search_query:
                params["q"] = self._search_query

            resp = self.state.client.get("/orders/", params=params)
            # Paginated response: {data: [...], meta: {total, page, page_size, pages}}
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
                self._orders.extend(items)
            else:
                self._orders = list(items)
            self._page = page
        except ApiError:
            if not append:
                self._orders = []
                self._total = 0
        self._render_table()

    def _do_search_reload(self) -> None:
        self._page = 1
        self.reload(page=1, append=False)


    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"OrderHistoryScreen {{ background-color: {COLORS['bg_light']}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(active="orders")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_topbar())
        cv.addWidget(self._build_content_area(), 1)
        root.addWidget(center, 1)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)
        bar.setStyleSheet(
            f"#topBar {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 0, 24, 0)
        h.setSpacing(SPACING["md"])

        # Tab «Активные заказы» — кликабелен, переключает на ActiveOrdersScreen
        active_btn = QPushButton("Активные заказы")
        active_btn.setFlat(True)
        active_btn.setCursor(Qt.PointingHandCursor)
        active_btn.setStyleSheet(self._tab_qss(active=False))
        active_btn.clicked.connect(self.nav_to_active.emit)
        h.addWidget(active_btn)

        # Tab «Закрытые сегодня» — текущий, оранжевый
        self._tab_today = QPushButton("Закрытые сегодня")
        self._tab_today.setFlat(True)
        self._tab_today.setCursor(Qt.PointingHandCursor)
        self._tab_today.setStyleSheet(self._tab_qss(active=True))
        self._tab_today.clicked.connect(lambda: self.set_mode("today"))
        h.addWidget(self._tab_today)

        self._tab_archive = QPushButton("Архив")
        self._tab_archive.setFlat(True)
        self._tab_archive.setCursor(Qt.PointingHandCursor)
        self._tab_archive.setStyleSheet(self._tab_qss(active=False))
        self._tab_archive.clicked.connect(lambda: self.set_mode("archive"))
        h.addWidget(self._tab_archive)

        h.addStretch(1)

        self._cashier_lbl = QLabel("")
        self._cashier_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        h.addWidget(self._cashier_lbl)
        return bar

    def _tab_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 6px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"  padding: 8px 16px;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none;"
            f"  font-size: 11pt; font-weight: 500;"
            f"  padding: 8px 16px;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
        )

    def _build_content_area(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # Search row + filters btn (placeholder для Phase 5+)
        v.addLayout(self._build_search_row())
        v.addWidget(self._build_table_card(), 1)
        v.addLayout(self._build_pagination_row())
        return w

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
        self._load_more_btn.clicked.connect(self._on_load_more)
        h.addWidget(self._load_more_btn)
        return h

    def _on_load_more(self) -> None:
        self.reload(page=self._page + 1, append=True)

    def _build_search_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        # Search: ширина 360 фиксирована (по дизайну), высота 48.
        # Debounce 350мс через _search_timer.
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(
            "Поиск по номеру чека, столу, имени, блюду…"
        )
        self._search_input.setFixedHeight(48)
        self._search_input.setMinimumWidth(360)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        self._search_input.textChanged.connect(self._on_search_text)

        # Фильтры: outline-кнопка (модалка фильтров — Phase 5+, сейчас inert).
        filters_btn = QPushButton("  Фильтры")
        filters_btn.setEnabled(False)
        filters_btn.setToolTip("Дополнительные фильтры — Phase 5+")
        filters_btn.setIcon(qicon("filter", COLORS["text_secondary"], 18))
        filters_btn.setIconSize(QSize(18, 18))
        filters_btn.setFixedHeight(48)
        filters_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px;"
            f"  font-size: 12pt;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
        )

        h.addWidget(self._search_input, 1)
        h.addWidget(filters_btn)
        return h

    def _on_search_text(self, text: str) -> None:
        self._search_query = (text or "").strip()
        self._search_timer.start()

    # Ширины колонок (по дизайну frame 12). Последняя — stretch (1).
    COL_WIDTHS = [60, 80, 100, 110, 120, 140, 0]
    COL_LABELS = ["№", "Время", "Стол", "Сумма", "Оплата", "Кассир", "Действия"]

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

        # Header row — fixed 44px, bg-gray, серый bold текст
        v.addWidget(self._build_header_row())

        # Список строк — в QScrollArea
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
                f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            w = self.COL_WIDTHS[i]
            if w > 0:
                lbl.setFixedWidth(w)
                layout.addWidget(lbl)
            else:
                layout.addWidget(lbl, 1)  # stretch последнюю
        return h

    # -------- render --------

    def _render_cashier_label(self) -> None:
        if self._cashier_name and self._shift_no:
            self._cashier_lbl.setText(
                f"{self._cashier_name}  |  Смена №{self._shift_no}"
            )
        elif self._cashier_name:
            self._cashier_lbl.setText(self._cashier_name)
        else:
            self._cashier_lbl.setText("")

    def _render_table(self) -> None:
        from PySide6.QtGui import QBrush, QColor, QFont

        # Очистить старые строки
        while self._rows_layout.count():
            child = self._rows_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        # Backend уже отдаёт по -created_at desc, но на всякий случай sort'нем.
        rows = sorted(
            self._orders,
            key=lambda o: o.get("closed_at") or o.get("created_at") or "",
            reverse=True,
        )

        # Pagination footer
        if hasattr(self, "_page_count_lbl"):
            if self._total > 0:
                self._page_count_lbl.setText(
                    f"Показано {len(self._orders)} из {self._total}"
                )
            else:
                self._page_count_lbl.setText("")
        if hasattr(self, "_load_more_btn"):
            self._load_more_btn.setEnabled(len(self._orders) < self._total)

        # Empty state — одно сообщение в центре
        if not rows:
            empty = QLabel("Закрытых заказов пока нет")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt; font-style: italic;"
                f" padding: 60px 0; background: transparent; border: none;"
            )
            self._rows_layout.addWidget(empty)
            return

        for i, o in enumerate(rows):
            self._rows_layout.addWidget(self._build_data_row(o, idx=i))

    def _build_data_row(self, o: dict, *, idx: int) -> QWidget:
        """Одна строка таблицы — QFrame с QHBoxLayout. Зебра: чётные idx — bg-gray."""
        pm_labels = {"cash": "Наличные", "card": "Карта", "transfer": "Перевод"}

        row = QFrame()
        row.setFixedHeight(52)
        bg = COLORS["bg_gray"] if (idx % 2 == 1) else COLORS["bg_white"]
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {bg};"
            f"  border: none;"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(0)

        def cell(text: str, *, width: int, bold: bool = False, secondary: bool = False, stretch: bool = False) -> QLabel:
            color = COLORS["text_secondary"] if secondary else COLORS["text_primary"]
            weight = 700 if bold else 400
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {color}; font-size: 12pt; font-weight: {weight};"
                f" border: none; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if width > 0:
                lbl.setFixedWidth(width)
            return lbl

        # Колонки: №, Время, Стол, Сумма (bold), Оплата (secondary), Кассир (secondary), Действия (stretch)
        h.addWidget(cell(f"#{o['id']}", width=self.COL_WIDTHS[0]))

        time_str = self._fmt_time(o.get("closed_at") or o.get("created_at"))
        h.addWidget(cell(time_str, width=self.COL_WIDTHS[1]))

        type_label = "С собой" if o.get("order_type") == "takeaway" else (
            "Доставка" if o.get("order_type") == "delivery"
            else (o.get("table_name") or "—")
        )
        h.addWidget(cell(type_label, width=self.COL_WIDTHS[2]))

        h.addWidget(
            cell(f"{o.get('total', '0.00')} TJS", width=self.COL_WIDTHS[3], bold=True)
        )

        pm = o.get("payment_method")
        pm_text = pm_labels.get(pm, "—") if pm else "—"
        if o.get("status") == "cancelled":
            pm_text = "Отменён"
        h.addWidget(cell(pm_text, width=self.COL_WIDTHS[4], secondary=True))

        h.addWidget(
            cell(o.get("cashier_name") or "—", width=self.COL_WIDTHS[5], secondary=True)
        )

        # Кнопка «Возврат» в последней колонке (stretch wrapper)
        action_wrap = QWidget()
        action_wrap.setStyleSheet("background: transparent; border: none;")
        aw = QHBoxLayout(action_wrap)
        aw.setContentsMargins(0, 0, 0, 0)
        aw.setSpacing(0)

        refund_btn = QPushButton("Возврат")
        is_done = o.get("status") == "done"
        refund_btn.setEnabled(is_done)
        refund_btn.setToolTip(
            "Возврат по закрытому заказу" if is_done
            else "Возврат возможен только по закрытым заказам"
        )
        refund_btn.setCursor(Qt.PointingHandCursor)
        refund_btn.setFixedHeight(32)
        refund_btn.setMinimumWidth(96)
        refund_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 6px;"
            f"  padding: 6px 12px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #B91C1C; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        refund_btn.clicked.connect(
            lambda _c=False, oid=int(o["id"]): self.refund_requested.emit(oid)
        )

        reprint_btn = QPushButton("Печать")
        reprint_btn.setEnabled(is_done)
        reprint_btn.setToolTip(
            "Повторно напечатать чек (помечается как ДУБЛИКАТ)"
            if is_done else
            "Повторная печать доступна только для закрытых заказов"
        )
        reprint_btn.setCursor(Qt.PointingHandCursor)
        reprint_btn.setFixedHeight(32)
        reprint_btn.setMinimumWidth(96)
        reprint_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"  padding: 6px 12px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        reprint_btn.clicked.connect(
            lambda _c=False, oid=int(o["id"]): self.reprint_requested.emit(oid)
        )

        aw.addWidget(reprint_btn)
        aw.addSpacing(8)
        aw.addWidget(refund_btn)
        aw.addStretch(1)
        h.addWidget(action_wrap, 1)
        return row

    @staticmethod
    def _fmt_time(iso: str | None) -> str:
        if not iso:
            return "—"
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M")
        except Exception:
            return "—"

    # -------- handlers --------

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        elif name == "tables":
            self.nav_to_active.emit()  # main решит куда идти

    def set_mode(self, mode: str) -> None:
        """mode ∈ {today, archive} — переключение «Закрытые сегодня» ↔ «Архив»."""
        if mode not in {"today", "archive"}:
            return
        self._mode = mode
        self._tab_today.setStyleSheet(self._tab_qss(active=(mode == "today")))
        self._tab_archive.setStyleSheet(self._tab_qss(active=(mode == "archive")))
        self.reload()
