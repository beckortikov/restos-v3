"""Экран 2. Карта зала + Заказ — frame "3. POS — Столы + Заказ" в design/pos_cashier.pen.

В дизайне три колонки: sidebar (72) | center (gridArea) | rightPanel (360).
В MVP cashier:
- sidebar реализован в pos.widgets.sidebar
- center grid — карточки столов (TableCard)
- rightPanel — детали заказа выбранного стола (OrderDetailPanel)
"""
import math
import uuid

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon, qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State
from pos.widgets.menu_panel import MenuPanel
from pos.widgets.order_detail_panel import OrderDetailPanel
from pos.widgets.orders_drawer import OrdersDrawer
from pos.widgets.printer_drawer import PrinterDrawer
from pos.widgets.sidebar import Sidebar
from pos.widgets.table_card import TableCard

GRID_MIN_COLUMNS = 2
GRID_MAX_COLUMNS = 8
GRID_PADDING_H = 20
GRID_PADDING_V = 16


class _CancelWorker(QObject):
    success = Signal(int)
    error = Signal(int, object)

    def __init__(
        self, client: ApiClient, order_id: int, manager_pin: str = "",
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.manager_pin = manager_pin

    def run(self) -> None:
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        if self.manager_pin:
            headers["X-Manager-Pin"] = self.manager_pin
        try:
            self.client.post(
                f"/orders/{self.order_id}/cancel/",
                json={"reason": "Отменён кассиром"},
                extra_headers=headers,
            )
            self.success.emit(self.order_id)
        except ApiError as e:
            self.error.emit(self.order_id, e)


class TablesScreen(QWidget):
    """Frame: 3. POS — Столы + Заказ.

    Сигналы:
        pay_requested(order_id) — Payment screen (экран 5)
        logout_requested
        nav_requested(name) — переключение между Tables/Orders из sidebar
    """

    pay_requested = Signal(int)
    logout_requested = Signal()
    nav_requested = Signal(str)
    new_order_requested = Signal(str, object)  # (order_type, table_id_or_None)
    add_items_requested = Signal(int)          # для дозаказа из rightPanel
    pre_bill_requested = Signal(int)           # «Пре-чек» из rightPanel
    cancel_item_requested = Signal(int, dict)  # × на позиции в rightPanel

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._cards: list[TableCard] = []
        self._columns = GRID_MIN_COLUMNS
        self._selected_table_id: int | None = None
        self._selected_order_id: int | None = None
        self._cashier_name: str = ""
        self._shift_no: int = 0
        self._cancel_threads: list[QThread] = []
        # Активная зона для фильтра grid'а. "all" = все зоны, иначе int(zone_id).
        self._active_zone_id: object = "all"
        self._zone_tab_buttons: dict[object, QPushButton] = {}
        # Активная не-залная кнопка ("takeaway" | "delivery" | None) — для
        # подсветки таба «С собой» / «Доставка» когда открыто меню
        # takeaway/delivery inline.
        self._active_non_hall: str | None = None
        self._non_hall_buttons: dict[str, QPushButton] = {}
        # Initial-render fix: первый _render_tables гарантированно делаем
        # после первого layout-pass через QTimer.singleShot(0, ...) в showEvent.
        self._first_show_done: bool = False
        # Overlay-drawer'ы (создаются лениво при первом открытии).
        # Floating-panel паттерн: parent=self, move() + raise_() + show()/hide().
        self._orders_drawer: OrdersDrawer | None = None
        self._printer_drawer: PrinterDrawer | None = None

        self._build()
        self.state.tables_changed.connect(self._on_state_changed)
        self.state.orders_changed.connect(self._on_state_changed)
        self.state.online_changed.connect(self._render_status)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_clock)
        self._clock.start(1000)
        self._update_clock()

    # ------- public -------

    def set_cashier(self, name: str, shift_no: int = 0) -> None:
        self._cashier_name = name
        self._shift_no = shift_no
        self._update_status_cashier()

    # ------- build -------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"TablesScreen {{ background-color: {COLORS['bg_light']}; }}"
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(active="tables")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        # CENTER: VBox (topbar / _center_stack[grid|menu-work] / statusbar).
        # ВАЖНО: topbar и statusbar — ВНУТРИ center, поэтому НЕ перекрывают
        # правую панель. Правая панель уходит на root-уровень → на всю высоту
        # окна (включая зону над/под топбаром).
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_topbar())
        self._center_stack = QStackedWidget()
        cv.addWidget(self._center_stack, 1)
        cv.addWidget(self._build_statusbar())
        root.addWidget(center, 1)

        # Page 0 центра: только grid (без detail_panel — он теперь снаружи).
        self._center_stack.addWidget(self._build_grid_scroll())

        # Page 1 центра: embedded MenuPanel (work-area, без CartPanel —
        # карточка тоже снаружи на root-уровне).
        self._menu_panel = MenuPanel(self.state)
        self._menu_panel.cancelled.connect(self._on_menu_panel_cancelled)
        self._menu_panel.order_submitted.connect(
            self._on_menu_panel_order_submitted,
        )
        self._menu_panel.reservation_requested.connect(
            self._on_menu_panel_reservation_requested,
        )
        self._menu_panel.search_query_cleared.connect(
            self._on_menu_search_cleared,
        )
        self._center_stack.addWidget(self._menu_panel)
        self._center_stack.setCurrentIndex(0)

        # RIGHT: QStackedWidget на root-уровне — 360px full-height.
        # Page 0 = OrderDetailPanel (детали выбранного стола / форма резерва).
        # Page 1 = CartPanel из MenuPanel (корзина текущего заказа).
        self.detail_panel = OrderDetailPanel()
        # ОПЛАТА из OrderDetailPanel → открыть OrdersDrawer + show_payment
        # (inline-sidebar 360px, как просил пользователь — без popup).
        self.detail_panel.pay_requested.connect(self._open_payment_in_drawer)
        self.detail_panel.cancel_requested.connect(self._on_cancel)
        self.detail_panel.add_items_requested.connect(self.add_items_requested.emit)
        self.detail_panel.reservation_action_requested.connect(
            self._on_reservation_action
        )
        # ПРЕ-ЧЕК из OrderDetailPanel → открыть OrdersDrawer + show_pre_bill
        # (inline-sidebar 360px, без popup модалки).
        self.detail_panel.pre_bill_requested.connect(self._open_pre_bill_in_drawer)
        self.detail_panel.group_switched.connect(self._on_group_switched)
        # «Добавить группу» — открываем меню INLINE (тот же flow, что и
        # клик по свободному столу). Раньше эмитили new_order_requested →
        # outer MenuScreen, у которого нет topbar'а Зал/С собой/Доставка.
        self.detail_panel.add_group_requested.connect(self._on_add_group_inline)
        self.detail_panel.reserve_submit_requested.connect(
            self._on_reserve_submit
        )
        self.detail_panel.cancel_item_requested.connect(
            self.cancel_item_requested.emit
        )

        self._right_stack = QStackedWidget()
        self._right_stack.setFixedWidth(360)
        self._right_stack.addWidget(self.detail_panel)
        self._right_stack.addWidget(self._menu_panel.cart)
        self._right_stack.setCurrentIndex(0)
        root.addWidget(self._right_stack)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(52)
        bar.setStyleSheet(
            f"#topBar {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(SPACING["md"])

        # Динамические табы зон (Зал, Веранда, Терраса ...) + «Все».
        # Список зон derive из state.tables (zone_id + zone_name) — отдельного
        # запроса не делаем, данные уже пришли с /tables/.
        self._zone_tabs_holder = QFrame()
        self._zone_tabs_holder.setStyleSheet("background: transparent;")
        zh = QHBoxLayout(self._zone_tabs_holder)
        zh.setContentsMargins(0, 0, 0, 0)
        zh.setSpacing(4)
        h.addWidget(self._zone_tabs_holder)
        self._render_zone_tabs()

        # «С собой» / «Доставка» — кликабельные табы как зоны, поддерживают
        # active-state (когда inline-меню открыто для takeaway/delivery).
        for label, kind in (("С собой", "takeaway"), ("Доставка", "delivery")):
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(self._non_hall_qss(active=False))
            btn.clicked.connect(
                lambda _checked=False, k=kind: self._on_start_non_hall(k)
            )
            self._non_hall_buttons[kind] = btn
            h.addWidget(btn)

        h.addStretch(1)

        # Поиск + Заказы — единый поисково-action кластер слева от центра.
        from PySide6.QtWidgets import QLineEdit
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Поиск стола…")
        self._search_input.setFixedHeight(36)
        self._search_input.setMinimumWidth(260)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 0 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        self._search_input.textChanged.connect(self._on_search_text)
        self._search_query: str = ""
        h.addWidget(self._search_input)

        # «Заказы» — рядом с поиском (по просьбе: «Заказы передвин ближе к поиску»).
        orders_btn = self._make_outline_btn("  Заказы", icon_name="receipt")
        orders_btn.clicked.connect(self._toggle_orders_drawer)
        h.addWidget(orders_btn)

        # «Ещё ▾» — выпадающее меню с «Принтер» и «Объединить», стоит сразу
        # после «Заказы» (без stretch'а между ними).
        from PySide6.QtWidgets import QMenu
        more_btn = self._make_outline_btn("Ещё  ▾")
        more_menu = QMenu(more_btn)
        more_menu.setStyleSheet(
            f"QMenu {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px; padding: 4px 0;"
            f"}}"
            f"QMenu::item {{"
            f"  padding: 8px 16px; color: {COLORS['text_primary']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QMenu::item:selected {{ background: {COLORS['bg_gray']}; }}"
        )
        act_printer = more_menu.addAction("Принтер")
        act_printer.triggered.connect(self._toggle_printer_drawer)
        act_merge = more_menu.addAction("Объединить столы")
        act_merge.triggered.connect(self._on_open_merge_dialog)
        more_btn.setMenu(more_menu)
        h.addWidget(more_btn)

        h.addStretch(1)

        # Кассир/смена не дублируем в топбаре — по дизайну они уже есть слева
        # в нижнем statusBar («Смена №N | Имя К.»). Раньше тут был
        # `self._top_cashier` — снят, чтобы не повторять одну и ту же информацию.
        return bar

    def _build_grid_scroll(self) -> QWidget:
        self._grid_holder = QWidget()
        self._grid = QGridLayout(self._grid_holder)
        self._grid.setContentsMargins(
            GRID_PADDING_H, GRID_PADDING_V, GRID_PADDING_H, GRID_PADDING_V
        )
        self._grid.setHorizontalSpacing(SPACING["md"])
        self._grid.setVerticalSpacing(SPACING["md"])
        # Карточки растягиваются по ширине колонки (см. setColumnStretch
        # в _render_tables), высота фиксированная — прижимаем grid к верху.
        self._grid.setAlignment(Qt.AlignTop)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidget(self._grid_holder)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {COLORS['bg_light']}; border: none; }}"
            f" QWidget {{ background-color: {COLORS['bg_light']}; }}"
        )
        return self._scroll

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(32)
        bar.setStyleSheet(
            f"#statusBar {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(SPACING["md"])

        # По дизайну: слева — «Смена №N | Имя К.» (text_secondary),
        # центр — время (text_primary, semibold), справа — «● Онлайн» (зелёный).
        self._status_left = QLabel("")
        self._status_left.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        self._status_clock = QLabel("--:--")
        self._status_clock.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 10pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )

        # Pill «● Онлайн» — точка 8×8 + текст 12pt 600 зелёный.
        online_wrap = QWidget()
        online_wrap.setStyleSheet("background: transparent;")
        oh = QHBoxLayout(online_wrap)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(6)
        self._status_dot = QLabel("")
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet(
            f"background-color: {COLORS['success_green']};"
            f" border-radius: 4px;"
        )
        self._status_label = QLabel("Онлайн")
        self._status_label.setStyleSheet(
            f"color: {COLORS['success_green']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        oh.addWidget(self._status_dot)
        oh.addWidget(self._status_label)
        self._status_online_wrap = online_wrap

        h.addWidget(self._status_left)
        h.addStretch(1)
        h.addWidget(self._status_clock)
        h.addStretch(1)
        h.addWidget(online_wrap)
        return bar

    # ------- handlers -------

    def _on_state_changed(self, *_args) -> None:
        self._render_tables()
        self._refresh_detail_panel()

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        else:
            self.nav_requested.emit(name)

    def _on_card_clicked(self, table_id: int, action: str) -> None:
        """Тап по столу:
        - Свободный стол → embedded MenuPanel **в том же окне** (внутренний
          QStackedWidget переключается на page 1). Sidebar/topbar остаются —
          нет «прыжка» окна. «Бронирование» — в правой панели MenuPanel.
        - Занятый / bill_requested → правая панель с деталями заказа.
        """
        self._selected_table_id = table_id
        for c in self._cards:
            c.set_selected(c._table_id == table_id)

        table = next(
            (t for t in self.state.tables if int(t["id"]) == int(table_id)),
            None,
        )
        if table is not None and table.get("status") == "free":
            # Inline-swap: центр → menu, правая панель → cart (full-height).
            self._menu_panel.configure_create("hall", int(table_id))
            self._menu_panel.reload()
            self._center_stack.setCurrentIndex(1)
            self._right_stack.setCurrentIndex(1)
            self._set_topbar_mode("menu")
            return

        # Занятый / bill_requested — стандартная панель с заказом.
        self._refresh_detail_panel()

    # -------- handlers embedded MenuPanel --------

    def _on_add_group_inline(self, table_id: int) -> None:
        """«Добавить группу» из OrderDetailPanel — открываем embedded MenuPanel
        в TablesScreen (тот же flow, что и клик по свободному столу), чтобы
        кассир остался в едином UI с topbar'ом Зал/С собой/Доставка."""
        self._selected_table_id = int(table_id)
        for c in self._cards:
            c.set_selected(c._table_id == int(table_id))
        self._menu_panel.configure_create("hall", int(table_id))
        self._menu_panel.reload()
        self._center_stack.setCurrentIndex(1)
        self._right_stack.setCurrentIndex(1)
        self._set_topbar_mode("menu")

    def _on_menu_panel_cancelled(self) -> None:
        """Кассир закрыл embedded меню (кнопка «Отмена» или «Назад»)."""
        self._set_topbar_mode("tables")
        self._set_non_hall_active(None)
        self._center_stack.setCurrentIndex(0)
        self._right_stack.setCurrentIndex(0)
        self._refresh_detail_panel()

    def _on_menu_panel_order_submitted(self, order_id: int) -> None:
        """Заказ создан через embedded меню — возвращаемся на карту зала."""
        self._set_topbar_mode("tables")
        self._set_non_hall_active(None)
        self._center_stack.setCurrentIndex(0)
        self._right_stack.setCurrentIndex(0)
        # state.refresh уже вызван внутри MenuPanel; перерисуем grid/panel.
        self._refresh_detail_panel()

    def _on_menu_panel_reservation_requested(self, table_id: int) -> None:
        """Клик «Бронирование» в embedded меню — возвращаемся и открываем
        форму резерва для этого стола."""
        self._set_topbar_mode("tables")
        self._set_non_hall_active(None)
        self._center_stack.setCurrentIndex(0)
        self._right_stack.setCurrentIndex(0)
        self.open_reservation_form(int(table_id))

    def _on_menu_search_cleared(self) -> None:
        """MenuPanel сбросил search через back-чип — чистим topbar input,
        но только если мы сейчас в menu-mode (текст принадлежит блюдам)."""
        if self._center_stack.currentIndex() != 1:
            return
        self._search_input.blockSignals(True)
        self._search_input.clear()
        self._search_input.blockSignals(False)

    def _set_topbar_mode(self, mode: str) -> None:
        """Контекстный переключатель основного поиска в топбаре.

        - tables-mode: placeholder «Поиск стола…», textChanged → фильтр grid'а столов.
        - menu-mode:  placeholder «Поиск блюда…», textChanged → MenuPanel.set_search_query.

        Никакие другие виджеты топбара не трогаем — Зал/С собой/Доставка/Заказы/
        Принтер/Объединить остаются видимыми всегда (пользователь явно: «топбар
        Зал/С собой — основной, не удваивать»).
        """
        try:
            self._search_input.textChanged.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._search_input.blockSignals(True)
        self._search_input.clear()
        self._search_input.blockSignals(False)
        if mode == "menu":
            self._search_input.setPlaceholderText("Поиск блюда…")
            self._search_input.textChanged.connect(
                self._menu_panel.set_search_query,
            )
        else:
            self._search_input.setPlaceholderText("Поиск стола…")
            self._search_input.textChanged.connect(self._on_search_text)

    def open_reservation_form(self, table_id: int) -> None:
        """Открыть форму бронирования для стола (вызывается из main.py при
        возврате с MenuScreen после клика «🕐 Бронирование»).
        """
        table = next(
            (t for t in self.state.tables if int(t["id"]) == int(table_id)),
            None,
        )
        if table is None:
            return
        self._selected_table_id = int(table_id)
        for c in self._cards:
            c.set_selected(c._table_id == int(table_id))
        self.detail_panel.show_reservation_form(table)

    def _on_card_context_menu(self, table_id: int, global_pos) -> None:
        """Правый клик по столу: меню действий в зависимости от статуса."""
        from PySide6.QtWidgets import QMenu

        table = next(
            (t for t in self.state.tables if int(t["id"]) == int(table_id)),
            None,
        )
        if table is None:
            return
        status = table.get("status")

        menu = QMenu(self)
        # Резервация теперь в правой панели через кнопку «🕐 Бронирование» —
        # здесь не дублируем. «Добавить группу» — тоже в правой панели.
        # В правом клике остаётся только force-free для застрявших столов.
        if (
            status in ("occupied", "bill_requested")
            and not table.get("current_order")
        ):
            free_action = menu.addAction("⚠  Освободить стол (нет заказа)")
            free_action.triggered.connect(
                lambda: self._force_free_table(table_id)
            )
        if menu.isEmpty():
            return
        menu.exec(global_pos)

    def _on_group_clicked(self, table_id: int, order_id: int) -> None:
        """Клик по конкретной группе на TableCard — выбираем стол и
        открываем именно эту группу в OrderDetailPanel."""
        self._selected_table_id = table_id
        self._selected_order_id = order_id  # запоминаем какую группу смотрим
        for c in self._cards:
            c.set_selected(c._table_id == table_id)
        self._refresh_detail_panel()

    def _on_group_switched(self, table_id: int, order_id: int) -> None:
        """Клик по табу группы внутри правой панели."""
        self._selected_order_id = order_id
        self._refresh_detail_panel()

    def _force_free_table(self, table_id: int) -> None:
        from PySide6.QtWidgets import QMessageBox

        confirm = QMessageBox(self)
        confirm.setWindowTitle("Освободить стол")
        confirm.setText(
            "Принудительно освободить стол? Это допустимо только если "
            "на столе нет активного заказа (рассинхрон состояния)."
        )
        confirm.setIcon(QMessageBox.Warning)
        yes = confirm.addButton("Освободить", QMessageBox.YesRole)
        confirm.addButton("Отмена", QMessageBox.RejectRole)
        confirm.exec()
        if confirm.clickedButton() != yes:
            return
        try:
            self.state.client.post(
                f"/tables/{table_id}/force_free/", json={},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"{e.message}\n[{e.code}]",
            )
            return
        self.state.refresh()

    def _on_reserve_submit(self, table_id: int, body: dict) -> None:
        """POST /reservations/ от inline-формы. На успех — refresh + обратно
        в free-table view. На ошибку — QMessageBox.warning, форма остаётся."""
        from PySide6.QtWidgets import QMessageBox

        try:
            self.state.client.post("/reservations/", json=body)
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось создать бронь:\n{e.message}\n[{e.code}]",
            )
            # Восстановим кнопку
            if hasattr(self.detail_panel, "_res_save_btn"):
                self.detail_panel._res_save_btn.setEnabled(True)
                self.detail_panel._res_save_btn.setText("Сохранить")
            return
        # Refresh state, чтобы next_reservation бейдж появился
        self.state.refresh()
        # Возврат в обычный free-table view (с кнопками «Открыть»/«Бронирование»)
        table = next(
            (t for t in self.state.tables if int(t["id"]) == int(table_id)),
            None,
        )
        if table is not None:
            self.detail_panel.show_free_table(table)

    def _on_search_text(self, text: str) -> None:
        self._search_query = (text or "").strip()
        self._render_tables()

    def _on_open_merge_dialog(self) -> None:
        """Открыть TableMergeDialog: загрузка списка столов и активных групп."""
        from pos.screens.table_merge_dialog import TableMergeDialog

        try:
            groups_resp = self.state.client.get(
                "/tables/groups/", params={"active": "true"},
            )
            groups = groups_resp.get("data", []) if isinstance(groups_resp, dict) else groups_resp or []
        except ApiError:
            groups = []

        dlg = TableMergeDialog(
            client=self.state.client,
            tables=list(self.state.tables),
            groups=groups,
            parent=self,
        )
        dlg.groups_changed.connect(self.state.refresh)
        dlg.exec()

    def _on_start_non_hall(self, kind: str) -> None:
        """Клик «С собой» / «Доставка» в топбаре — inline-меню в TablesScreen.

        Тот же top bar (Зал/С собой/Доставка/Поиск/Заказы/Принтер/Объединить)
        остаётся неизменным — только подсвечивается активный таб + центр
        свапается на MenuPanel (как при клике на свободный стол).

        Для takeaway/delivery сначала собираем контакт через CustomerDialog —
        отказ возвращает в tables-mode без изменения интерфейса.
        """
        from pos.screens.customer_dialog import CustomerDialog

        dlg = CustomerDialog(order_type=kind, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._menu_panel.configure_create(
            kind,
            table_id=None,
            customer_name=dlg.name,
            customer_phone=dlg.phone,
            customer_address=dlg.address,
        )
        self._menu_panel.reload()
        self._center_stack.setCurrentIndex(1)
        self._right_stack.setCurrentIndex(1)
        self._set_topbar_mode("menu")
        self._set_non_hall_active(kind)
        # Сбрасываем выделение стола и зон — пользователь сейчас в takeaway.
        self._selected_table_id = None
        for c in self._cards:
            c.set_selected(False)

    # -------- topbar buttons helper --------

    def _make_outline_btn(
        self, label: str, *, icon_name: str | None = None,
    ) -> QPushButton:
        """Outline-кнопка для топбара (Объединить / Заказы / Принтер).
        Стиль единый: bg-white + border + 36px height + 11pt 600.
        Иконка (lucide) опциональна — слева от текста, 16px."""
        btn = QPushButton(label)
        btn.setFixedHeight(36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        if icon_name:
            btn.setIcon(qicon(icon_name, COLORS["text_primary"], 16))
            btn.setIconSize(QSize(16, 16))
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 6px 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        return btn

    # -------- overlay drawers --------

    def _ensure_orders_drawer(self) -> "OrdersDrawer":
        """Lazy create + wire OrdersDrawer. Возвращает экземпляр (видимость
        не меняет — callers сами решают show/hide)."""
        if self._orders_drawer is None:
            self._orders_drawer = OrdersDrawer(self.state, parent=self)
            self._orders_drawer.closed.connect(self._close_drawers)
            self._orders_drawer.reprint_requested.connect(
                self._on_reprint_from_drawer,
            )
            self._orders_drawer.pre_bill_requested.connect(
                self.pre_bill_requested.emit,
            )
            self._orders_drawer.width_change_requested.connect(
                lambda _w=None: self._position_drawer(self._orders_drawer),
            )
            self._orders_drawer.hide()
        return self._orders_drawer

    def _show_orders_drawer(self) -> None:
        """Открыть drawer (не toggle) — позиционирует, поднимает, показывает."""
        drawer = self._ensure_orders_drawer()
        if self._printer_drawer is not None and self._printer_drawer.isVisible():
            self._printer_drawer.hide()
        if not drawer.isVisible():
            drawer.refresh()
        self._position_drawer(drawer)
        drawer.raise_()
        drawer.show()

    def _toggle_orders_drawer(self) -> None:
        """Открыть/закрыть OrdersDrawer. Закрывает printer drawer если открыт."""
        drawer = self._ensure_orders_drawer()
        if drawer.isVisible():
            drawer.hide()
            return
        self._show_orders_drawer()

    def _open_pre_bill_in_drawer(self, order_id: int) -> None:
        """ПРЕ-ЧЕК из OrderDetailPanel → drawer.show_pre_bill (inline sidebar)."""
        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)),
            None,
        )
        if order is None:
            return
        table = None
        tid = order.get("table")
        if tid is not None:
            table = next(
                (t for t in self.state.tables if int(t["id"]) == int(tid)),
                None,
            )
        self._show_orders_drawer()
        self._orders_drawer.show_pre_bill(order, table)
        self._position_drawer(self._orders_drawer)

    def _open_payment_in_drawer(self, order_id: int) -> None:
        """ОПЛАТА из OrderDetailPanel → drawer.show_payment (inline sidebar)."""
        order = next(
            (o for o in self.state.orders if int(o["id"]) == int(order_id)),
            None,
        )
        if order is None:
            return
        table = None
        tid = order.get("table")
        if tid is not None:
            table = next(
                (t for t in self.state.tables if int(t["id"]) == int(tid)),
                None,
            )
        self._show_orders_drawer()
        self._orders_drawer.show_payment(order, table)
        self._position_drawer(self._orders_drawer)

    def _toggle_printer_drawer(self) -> None:
        """Открыть/закрыть PrinterDrawer. Закрывает orders drawer если открыт."""
        if self._printer_drawer is None:
            self._printer_drawer = PrinterDrawer(self.state, parent=self)
            self._printer_drawer.closed.connect(self._close_drawers)
            self._printer_drawer.hide()
        if self._printer_drawer.isVisible():
            self._printer_drawer.hide()
            return
        if self._orders_drawer is not None and self._orders_drawer.isVisible():
            self._orders_drawer.hide()
        self._position_drawer(self._printer_drawer)
        self._printer_drawer.raise_()
        self._printer_drawer.show()

    def _close_drawers(self) -> None:
        if self._orders_drawer is not None and self._orders_drawer.isVisible():
            self._orders_drawer.hide()
        if self._printer_drawer is not None and self._printer_drawer.isVisible():
            self._printer_drawer.hide()

    def _position_drawer(self, drawer: QWidget) -> None:
        """Позиционируем drawer как floating panel поверх правой части экрана.

        Default: drawer от y=topbar_h до bottom-statusbar_h (не перекрывает
        topbar/statusbar). Если у drawer'а `overlay_mode=True` (pre-bill mode) —
        растягиваем на полную высоту окна, чтобы перекрыть весь правый sidebar
        (OrderDetailPanel) целиком как в дизайне restos.
        """
        topbar_h = 52
        statusbar_h = 32
        x = self.width() - drawer.width()
        if getattr(drawer, "overlay_mode", False):
            drawer.setGeometry(x, 0, drawer.width(), self.height())
        else:
            drawer.setGeometry(
                x, topbar_h, drawer.width(),
                self.height() - topbar_h - statusbar_h,
            )

    def _on_reprint_from_drawer(self, order_id: int) -> None:
        """Reprint из OrdersDrawer — переиспользуем тот же endpoint, что и
        OrderHistoryScreen (POST /orders/{id}/reprint_receipt/).
        Handler в main.py для outer `reprint_requested` пока не доступен из
        TablesScreen — делаем POST прямо здесь."""
        from uuid import uuid4
        try:
            self.state.client.post(
                f"/orders/{order_id}/reprint_receipt/",
                json={},
                extra_headers={"Idempotency-Key": str(uuid4())},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка печати", f"Не удалось отправить чек: {e.message}",
            )
            return
        # Можно показать toast «Чек отправлен», но MessageBox слишком обилен.
        # Пока molchaom — пользователь увидит job в Printer drawer.

    def _on_reservation_action(self, reservation_id: int, action: str) -> None:
        """Действие над бронью из правой панели (свободный стол с next_reservation).

        action ∈ {"confirm", "seat", "no_show", "cancel"} → POST на эндпоинт.
        Для "cancel" просим подтверждение.
        """
        labels = {
            "confirm": "подтвердить",
            "seat": "усадить",
            "no_show": "отметить «не пришли»",
            "cancel": "отменить",
        }
        if action == "cancel":
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Отменить бронь")
            confirm.setText(f"Отменить бронь #{reservation_id}?")
            confirm.setIcon(QMessageBox.Question)
            yes = confirm.addButton("Отменить бронь", QMessageBox.YesRole)
            confirm.addButton("Не отменять", QMessageBox.NoRole)
            confirm.exec()
            if confirm.clickedButton() != yes:
                return
        try:
            self.state.client.post(
                f"/reservations/{reservation_id}/{action}/",
                json={}, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось {labels.get(action, action)}:\n"
                f"{e.message}\n[{e.code}]",
            )
            return
        self.state.refresh()

    def _on_cancel(self, order_id: int, manager_pin: str = "") -> None:
        # Если manager_pin уже передан (retry-flow) — пропускаем подтверждение.
        if not manager_pin:
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Отменить заказ")
            confirm.setText(f"Отменить заказ #{order_id}?")
            confirm.setIcon(QMessageBox.Question)
            yes = confirm.addButton("Отменить", QMessageBox.YesRole)
            confirm.addButton("Не отменять", QMessageBox.NoRole)
            confirm.exec()
            if confirm.clickedButton() != yes:
                return

        thread = QThread(self)
        worker = _CancelWorker(self.state.client, order_id, manager_pin)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_cancel_done)
        worker.error.connect(self._on_cancel_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # Удержать worker, иначе Python GC удалит его до старта потока.
        thread._worker = worker  # noqa: SLF001
        self._cancel_threads.append(thread)
        thread.start()

    def _on_cancel_done(self, _order_id: int) -> None:
        self.state.refresh()

    def _on_cancel_failed(self, order_id: int, exc: ApiError) -> None:
        # Manager-override flow: backend сказал «нужен PIN менеджера» → диалог.
        if exc.code in ("MANAGER_OVERRIDE_REQUIRED", "MANAGER_OVERRIDE_INVALID_PIN"):
            from pos.screens.manager_pin_dialog import ManagerPinDialog

            msg = (
                "Неверный PIN. Попробуйте ещё раз."
                if exc.code == "MANAGER_OVERRIDE_INVALID_PIN"
                else "Эта операция требует подтверждения менеджера"
            )
            dlg = ManagerPinDialog(message=msg, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted and dlg.pin:
                # Retry с введённым PIN'ом
                self._on_cancel(order_id, manager_pin=dlg.pin)
            return
        QMessageBox.warning(
            self, "Ошибка отмены", f"Не удалось отменить #{order_id}: {exc.message}"
        )

    def showEvent(self, event):  # noqa: N802
        """Первый показ: к этому моменту layout ещё не выполнен, поэтому
        отложим _render_tables через QTimer.singleShot(0, ...) — Qt отработает
        layout-pass, и _compute_columns() увидит финальный viewport.width()
        (а не initial ~0). Без этого initial render даёт 2-3 колонки вместо
        корректных 5+, и карточки выглядят растянутыми."""
        super().showEvent(event)
        if not self._first_show_done:
            self._first_show_done = True
            QTimer.singleShot(0, self._render_tables)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._cards and self._compute_columns() != self._columns:
            self._render_tables()
        # Перепозиционировать открытые drawer'ы при ресайзе окна.
        if self._orders_drawer is not None and self._orders_drawer.isVisible():
            self._position_drawer(self._orders_drawer)
        if self._printer_drawer is not None and self._printer_drawer.isVisible():
            self._position_drawer(self._printer_drawer)

    # ------- rendering -------

    def _compute_columns(self) -> int:
        """Кол-во колонок = сколько фиксированных карточек помещается
        в viewport по ширине. Карточки не растягиваются (fixed size), при
        переполнении — vertical scroll внутри QScrollArea."""
        viewport = self._scroll.viewport().width() if hasattr(self, "_scroll") else self.width()
        usable = max(0, viewport - 2 * GRID_PADDING_H)
        cell = TableCard.CARD_WIDTH + SPACING["md"]
        max_by_width = (usable + SPACING["md"]) // cell or 1
        return max(GRID_MIN_COLUMNS, min(GRID_MAX_COLUMNS, int(max_by_width)))

    def _clear_grid_stretches(self) -> None:
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)

    def _build_order_total_index(self) -> dict[int, str]:
        idx: dict[int, str] = {}
        for o in self.state.orders:
            tid = o.get("table")
            if tid is None or o.get("status") not in ("new", "bill_requested"):
                continue
            total = o.get("total")
            if total:
                idx[int(tid)] = f"{total} TJS"
        return idx

    def _non_hall_qss(self, *, active: bool) -> str:
        """Стиль для табов «С собой» / «Доставка» — совпадает с zone tab,
        чтобы visually-consistent active-state в одном топбаре."""
        return self._zone_tab_qss(active=active)

    def _set_non_hall_active(self, kind: str | None) -> None:
        """Подсветить кнопку «С собой»/«Доставка» как active (или сбросить)."""
        self._active_non_hall = kind
        for k, btn in self._non_hall_buttons.items():
            btn.setStyleSheet(self._non_hall_qss(active=(k == kind)))

    def _zone_tab_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background-color: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 6px;"
                f"  padding: 6px 14px;"
                f"  font-size: 11pt; font-weight: 600;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none; padding: 6px 14px;"
            f"  font-size: 11pt; font-weight: 500;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
        )

    # Сколько зон показываем кнопками; остальные — в dropdown «Ещё ▾».
    VISIBLE_ZONES = 3

    def _render_zone_tabs(self) -> None:
        """Перерисовать табы зон по уникальным zone_id из state.tables.

        Логика: «Все» + первые VISIBLE_ZONES зон как кнопки; остальные —
        в dropdown «Ещё ▾». Если активна зона из dropdown — её имя показывается
        в самом «Ещё» (например «Веранда ▾») для feedback.
        """
        if not hasattr(self, "_zone_tabs_holder"):
            return
        layout = self._zone_tabs_holder.layout()
        # Очистить
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._zone_tab_buttons.clear()

        # Собрать уникальные зоны из state.tables.
        zones: dict[int, str] = {}
        for t in self.state.tables:
            zid = t.get("zone")
            zname = t.get("zone_name") or ""
            if zid is not None and zid not in zones:
                zones[int(zid)] = zname
        sorted_zones = sorted(zones.items())  # стабильный порядок по id

        def _mk_tab(key: object, label: str) -> QPushButton:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            is_active = (key == self._active_zone_id)
            btn.setStyleSheet(self._zone_tab_qss(active=is_active))
            btn.clicked.connect(lambda _c=False, k=key: self._on_zone_tab(k))
            self._zone_tab_buttons[key] = btn
            return btn

        # «Все» таб — показывается только если зон ≥2.
        if len(sorted_zones) >= 2:
            layout.addWidget(_mk_tab("all", "Все"))

        # Если зон <= VISIBLE_ZONES — показываем все кнопками без dropdown.
        if len(sorted_zones) <= self.VISIBLE_ZONES:
            for zid, zname in sorted_zones:
                layout.addWidget(_mk_tab(zid, zname))
        else:
            # Иначе: первые VISIBLE_ZONES кнопками, остальные в «Ещё ▾».
            visible = sorted_zones[: self.VISIBLE_ZONES]
            hidden = sorted_zones[self.VISIBLE_ZONES:]
            for zid, zname in visible:
                layout.addWidget(_mk_tab(zid, zname))
            # Если активная зона — в hidden, отражаем её имя в «Ещё».
            hidden_active = next(
                ((zid, zname) for zid, zname in hidden if zid == self._active_zone_id),
                None,
            )
            if hidden_active:
                more_label = f"{hidden_active[1]}  ▾"
                more_is_active = True
            else:
                more_label = f"Ещё ({len(hidden)})  ▾"
                more_is_active = False
            more_btn = QPushButton(more_label)
            more_btn.setFlat(True)
            more_btn.setCursor(Qt.PointingHandCursor)
            more_btn.setFocusPolicy(Qt.NoFocus)
            more_btn.setStyleSheet(self._zone_tab_qss(active=more_is_active))
            from PySide6.QtWidgets import QMenu
            menu = QMenu(more_btn)
            for zid, zname in hidden:
                a = menu.addAction(zname)
                a.setCheckable(True)
                a.setChecked(zid == self._active_zone_id)
                a.triggered.connect(lambda _c=False, k=zid: self._on_zone_tab(k))
            more_btn.setMenu(menu)
            layout.addWidget(more_btn)
            self._zone_tab_buttons["__more__"] = more_btn

        # Если активной нет в списке (например, удалили зону) — переключаем на all.
        if self._active_zone_id != "all" and self._active_zone_id not in zones:
            self._active_zone_id = "all"

    def _on_zone_tab(self, key: object) -> None:
        # Клик по любой зоне в топбаре — пользователь хочет вернуться к карте
        # столов. Если открыто inline-меню (takeaway/delivery/hall) — корзина
        # пустая → закрываем без подтверждения; есть позиции → confirm.
        if self._center_stack.currentIndex() == 1:
            if self._menu_panel.is_dirty():
                if not self._menu_panel.confirm_discard():
                    return
            self._on_menu_panel_cancelled()
        if self._active_zone_id == key:
            return
        self._active_zone_id = key
        # Перерисуем табы целиком — чтобы «Ещё ▾» подхватило имя выбранной
        # зоны из dropdown и подсветку.
        self._render_zone_tabs()
        self._render_tables()

    def _render_tables(self) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._clear_grid_stretches()

        # Перерисовать табы зон при изменении state.tables (на случай новых зон).
        self._render_zone_tabs()

        order_total_by_table = self._build_order_total_index()
        cols = self._compute_columns()
        self._columns = cols

        tables = sorted(self.state.tables, key=lambda t: int(t.get("number") or 0))
        # Фильтр по активной зоне (если выбрана конкретная).
        if self._active_zone_id != "all":
            tables = [
                t for t in tables
                if int(t.get("zone") or 0) == self._active_zone_id
            ]
        # Поисковый фильтр: совпадение по name / number / zone_name / waiter_name.
        q = (getattr(self, "_search_query", "") or "").strip().lower()
        if q:
            def _match(t: dict) -> bool:
                fields = [
                    str(t.get("name") or ""),
                    str(t.get("number") or ""),
                    str(t.get("zone_name") or ""),
                    str(t.get("waiter_name") or ""),
                ]
                return any(q in f.lower() for f in fields)
            tables = [t for t in tables if _match(t)]

        for i, table in enumerate(tables):
            row, col = divmod(i, cols)
            total_text = order_total_by_table.get(int(table["id"]), "")
            card = TableCard(table, total_text=total_text)
            card.clicked.connect(self._on_card_clicked)
            card.context_menu_requested.connect(self._on_card_context_menu)
            card.group_clicked.connect(self._on_group_clicked)
            if int(table["id"]) == self._selected_table_id:
                card.set_selected(True)
            self._grid.addWidget(card, row, col)
            self._cards.append(card)

        # Растягиваем колонки равномерно — карточки заполняют всю ширину
        # viewport'а (по горизонтали). Высота фиксированная: rowStretch не нужен.
        if tables:
            for c in range(cols):
                self._grid.setColumnStretch(c, 1)

    def _refresh_detail_panel(self) -> None:
        if self._selected_table_id is None:
            self.detail_panel.show_empty()
            return
        table = next(
            (t for t in self.state.tables if int(t["id"]) == self._selected_table_id),
            None,
        )
        if table is None:
            self.detail_panel.show_empty()
            return
        if table.get("status") == "free":
            self.detail_panel.show_free_table(table)
            self._selected_order_id = None
            return
        # Активные заказы на столе (multi-group)
        active = [
            o for o in self.state.orders
            if o.get("table") == self._selected_table_id
            and o.get("status") in {"new", "bill_requested"}
        ]
        if not active:
            self.detail_panel.show_free_table(table)
            self._selected_order_id = None
            return
        # Если выбрана конкретная группа — её и показываем; иначе primary
        # (current_order стола или первый активный)
        target = None
        if self._selected_order_id is not None:
            target = next(
                (o for o in active if int(o["id"]) == int(self._selected_order_id)),
                None,
            )
        if target is None:
            primary_id = table.get("current_order")
            target = next(
                (o for o in active if int(o["id"]) == int(primary_id or 0)),
                None,
            ) or active[0]
            self._selected_order_id = int(target["id"])
        self.detail_panel.show_order(table, target)

    def _render_status(self, online: bool) -> None:
        color = COLORS["success_green"] if online else COLORS["danger_red"]
        self._status_label.setText("Онлайн" if online else "Офлайн")
        self._status_label.setStyleSheet(
            f"color: {color}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        self._status_dot.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;"
        )

    def _update_clock(self) -> None:
        from datetime import datetime
        self._status_clock.setText(datetime.now().strftime("%H:%M"))

    def _update_status_cashier(self) -> None:
        parts: list[str] = []
        if self._shift_no:
            parts.append(f"Смена №{self._shift_no}")
        if self._cashier_name:
            parts.append(self._cashier_name)
        self._status_left.setText("  |  ".join(parts))
