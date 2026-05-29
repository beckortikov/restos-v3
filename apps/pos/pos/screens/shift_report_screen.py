"""Отчёт по смене — frames "15. Сводка" + "16. Официанты" в design/pos_cashier.pen.

Полноэкранный screen с двумя табами:
- Сводка (frame 15): KPI cards + 3 колонки (оплаты / категории / тип заказа) + касса
- Официанты (frame 16): таблица — заказы / продажи / ср.чек

MVP-cut от дизайна:
- Обслуживание (Phase 4)
- Чаевые (Phase 4)
- Возвраты (Phase 4)
- «vs вчера +5%» (Phase 7 аналитика)
- «Печать Z-отчёта» (Phase 3 backend)
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State
from pos.widgets.sidebar import Sidebar


class ShiftReportScreen(QWidget):
    """Сигналы:
        back_requested() — кнопка «Назад» / sidebar
        close_shift_requested() — кнопка «Закрыть смену и печать Z-отчёта»
        logout_requested()
    """

    back_requested = Signal()
    close_shift_requested = Signal()
    print_z_requested = Signal(int)
    print_x_requested = Signal(int)
    cash_op_created = Signal(dict)
    logout_requested = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._report: dict | None = None
        self._shift_id: int | None = None
        self._build()

    # -------- public --------

    def set_shift_id(self, shift_id: int) -> None:
        """Тянет /shifts/{id}/report/ и перерисовывает."""
        self._shift_id = shift_id
        try:
            data = self.state.client.get(f"/shifts/{shift_id}/report/")
        except ApiError:
            data = None
        # ApiClient возвращает {"data": ...} напрямую развёрнутым; иначе берём data
        if isinstance(data, dict) and "data" in data and "kpi" not in data:
            data = data["data"]
        self._report = data
        self._render()

    # -------- build --------

    def _build(self) -> None:
        # WA_StyledBackground обязателен для покраски фона QWidget'а через
        # class-name селектор. Без него QSS не красит, и сквозь пустоты
        # пробивается чёрный системный фон macOS dark mode.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"ShiftReportScreen {{ background-color: {COLORS['bg_light']}; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(active="tables")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(SPACING["xl"] + 8, SPACING["lg"], SPACING["xl"] + 8, SPACING["lg"])
        cv.setSpacing(SPACING["lg"])

        cv.addWidget(self._build_topbar())
        # 4 KPI cards
        self._kpi_row = QFrame()
        self._kpi_layout = QHBoxLayout(self._kpi_row)
        self._kpi_layout.setContentsMargins(0, 0, 0, 0)
        self._kpi_layout.setSpacing(SPACING["lg"])
        cv.addWidget(self._kpi_row)

        # Stacked tabs body (Сводка / Официанты)
        self._stack = QStackedWidget()
        self._summary_view = self._build_summary_view()
        self._waiters_view = self._build_waiters_view()
        self._stack.addWidget(self._summary_view)
        self._stack.addWidget(self._waiters_view)
        cv.addWidget(self._stack, 1)

        cv.addLayout(self._build_bottom_buttons())
        root.addWidget(center, 1)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        self._title = QLabel("Отчёт по смене")
        self._title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        h.addWidget(self._title)

        self._date_lbl = QLabel("")
        self._date_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        h.addWidget(self._date_lbl)
        h.addStretch(1)

        # Tabs
        self._tab_summary = self._make_tab("Сводка", active=True)
        self._tab_waiters = self._make_tab("Официанты", active=False)
        self._tab_summary.clicked.connect(lambda: self._switch_tab(0))
        self._tab_waiters.clicked.connect(lambda: self._switch_tab(1))
        h.addWidget(self._tab_summary)
        h.addWidget(self._tab_waiters)
        return bar

    def _make_tab(self, label: str, *, active: bool) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setMinimumHeight(36)
        btn.setStyleSheet(self._tab_qss(active))
        return btn

    def _tab_qss(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 8px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"  padding: 6px 18px;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"  padding: 6px 18px;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _switch_tab(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        self._tab_summary.setStyleSheet(self._tab_qss(idx == 0))
        self._tab_waiters.setStyleSheet(self._tab_qss(idx == 1))

    def _build_summary_view(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_light']}; border: none; }}"
            f" QWidget {{ background: {COLORS['bg_light']}; }}"
        )

        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACING["lg"])

        # 3 колонки: оплаты / категории / типы заказов + касса справа
        self._details_grid = QGridLayout()
        self._details_grid.setHorizontalSpacing(SPACING["lg"])
        self._details_grid.setVerticalSpacing(SPACING["lg"])

        v.addLayout(self._details_grid)
        v.addStretch(1)
        scroll.setWidget(holder)
        return scroll

    def _build_waiters_view(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("waitersCard")
        card.setStyleSheet(
            f"#waitersCard {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['lg']}px;"
            f"}}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)

        self._waiters_table = QTableWidget()
        self._waiters_table.setColumnCount(4)
        self._waiters_table.setHorizontalHeaderLabels(
            ["Официант", "Заказы", "Продажи", "Ср. чек"]
        )
        self._waiters_table.verticalHeader().setVisible(False)
        self._waiters_table.setShowGrid(False)
        self._waiters_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: none;"
            f"  font-size: 12pt;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none;"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  padding: 12px;"
            f"  font-weight: 600;"
            f"}}"
            f"QTableWidget::item {{ padding: 8px; }}"
        )
        self._waiters_table.horizontalHeader().setStretchLastSection(False)
        cv.addWidget(self._waiters_table)
        v.addWidget(card)
        return wrap

    def _build_bottom_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        back_btn = QPushButton("Назад")
        back_btn.setFixedHeight(48)
        back_btn.setMinimumWidth(120)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 600; padding: 0 24px;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        back_btn.clicked.connect(self.back_requested.emit)

        h.addWidget(back_btn)
        h.addStretch(1)

        # «Касса» — внесение/изъятие наличных. Активна только для open смены.
        self._cash_op_btn = QPushButton("  Касса")
        self._cash_op_btn.setFixedHeight(48)
        self._cash_op_btn.setMinimumWidth(140)
        self._cash_op_btn.setCursor(Qt.PointingHandCursor)
        self._cash_op_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700; padding: 0 20px;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        self._cash_op_btn.clicked.connect(self._on_cash_op)
        h.addWidget(self._cash_op_btn)

        # «Печать X-отчёта» — промежуточный отчёт (только для открытых смен).
        self._print_x_btn = QPushButton("  Печать X-отчёта")
        self._print_x_btn.setFixedHeight(48)
        self._print_x_btn.setMinimumWidth(180)
        self._print_x_btn.setCursor(Qt.PointingHandCursor)
        self._print_x_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700; padding: 0 24px;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        self._print_x_btn.clicked.connect(self._on_print_x)
        h.addWidget(self._print_x_btn)

        # «Печать Z-отчёта» — outline-кнопка слева от красной «Закрыть смену».
        # Активна всегда (если shift_id известен): можно перепечатать.
        self._print_z_btn = QPushButton("  Печать Z-отчёта")
        self._print_z_btn.setFixedHeight(48)
        self._print_z_btn.setMinimumWidth(180)
        self._print_z_btn.setCursor(Qt.PointingHandCursor)
        self._print_z_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700; padding: 0 24px;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}"
        )
        self._print_z_btn.clicked.connect(self._on_print_z)
        h.addWidget(self._print_z_btn)

        self._close_btn = QPushButton("Закрыть смену")
        self._close_btn.setFixedHeight(48)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"  padding: 0 28px;"
            f"}}"
            f"QPushButton:pressed {{ background-color: #B91C1C; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._close_btn.clicked.connect(self.close_shift_requested.emit)
        h.addWidget(self._close_btn)
        return h

    def _on_cash_op(self) -> None:
        """Открыть CashOpDialog. После успеха — пере-загрузить отчёт."""
        if self._shift_id is None:
            return
        from pos.screens.cash_op_dialog import CashOpDialog

        dlg = CashOpDialog(self.state.client, self._shift_id, parent=self)
        dlg.op_created.connect(self._on_cash_op_created)
        dlg.exec()

    def _on_cash_op_created(self, op: dict) -> None:
        """Обновляем отчёт (expected_balance, cash_in_total/out_total изменились)."""
        self.cash_op_created.emit(op or {})
        if self._shift_id is not None:
            self.set_shift_id(self._shift_id)

    def _on_print_x(self) -> None:
        """POST /shifts/{id}/print_x/ — промежуточный X-отчёт.

        Доступно только для открытой смены (backend вернёт 422
        INVALID_TRANSITION для закрытой)."""
        if self._shift_id is None:
            return
        try:
            self.state.client.post(
                f"/shifts/{self._shift_id}/print_x/", json={}, idempotent=True,
            )
        except ApiError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Ошибка печати",
                f"Не удалось поставить X-отчёт в очередь:\n{e.message}\n[{e.code}]",
            )
            return
        self.print_x_requested.emit(int(self._shift_id))

    def _on_print_z(self) -> None:
        """POST /shifts/{id}/print_z/ → emit print_z_requested(shift_id)."""
        if self._shift_id is None:
            return
        try:
            self.state.client.post(f"/shifts/{self._shift_id}/print_z/", json={})
        except ApiError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Ошибка печати",
                f"Не удалось поставить Z-отчёт в очередь:\n{e.message}\n[{e.code}]",
            )
            return
        self.print_z_requested.emit(int(self._shift_id))

    # -------- render --------

    def _render(self) -> None:
        if self._report is None:
            self._title.setText("Отчёт недоступен")
            self._close_btn.setEnabled(False)
            self._close_btn.setText("Смена закрыта")
            return

        shift = self._report.get("shift") or {}
        kpi = self._report.get("kpi") or {}
        self._title.setText(f"Отчёт по смене №{shift.get('number', '?')}")
        opened = shift.get("opened_at", "")[:16].replace("T", " ") if shift.get("opened_at") else ""
        closed = shift.get("closed_at") or "сейчас"
        self._date_lbl.setText(f"{opened} — {closed[:16].replace('T', ' ')}")

        # Кнопка «Закрыть смену» активна только если смена ещё открыта.
        is_open = (shift.get("status") == "open")
        self._close_btn.setEnabled(is_open)
        self._close_btn.setText(
            "Закрыть смену" if is_open else "Смена закрыта"
        )
        # X-отчёт — только для открытой смены.
        if hasattr(self, "_print_x_btn"):
            self._print_x_btn.setEnabled(is_open)
            self._print_x_btn.setToolTip(
                "Промежуточный отчёт по текущей смене"
                if is_open else
                "X-отчёт доступен только для открытой смены"
            )
        # Касса-операции — только для открытой смены
        if hasattr(self, "_cash_op_btn"):
            self._cash_op_btn.setEnabled(is_open)
            self._cash_op_btn.setToolTip(
                "" if is_open else "Операции возможны только в открытой смене"
            )

        self._render_kpi(kpi)
        self._render_summary_details()
        self._render_waiters_table()

    def _render_kpi(self, kpi: dict) -> None:
        # очистить
        while self._kpi_layout.count():
            child = self._kpi_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        deltas = (self._report or {}).get("deltas") or {}
        cards = [
            (
                "Выручка",
                f"{kpi.get('revenue', '0.00')} TJS",
                f"{kpi.get('orders_count', 0)} заказов",
                deltas.get("revenue_pct"),
            ),
            (
                "Средний чек",
                f"{kpi.get('average_check', '0.00')} TJS",
                "",
                deltas.get("average_check_pct"),
            ),
            (
                "Гостей",
                str(kpi.get("guests_count", 0)),
                f"ср. визит {kpi.get('average_per_guest', '0.00')} TJS",
                deltas.get("guests_pct"),
            ),
            (
                "Заказов",
                str(kpi.get("orders_count", 0)),
                "",
                deltas.get("orders_pct"),
            ),
        ]
        for label, value, sub, delta_pct in cards:
            self._kpi_layout.addWidget(
                self._kpi_card(label, value, sub, delta_pct=delta_pct), 1
            )

    def _kpi_card(
        self,
        label: str,
        value: str,
        sub: str,
        *,
        delta_pct: str | None = None,
    ) -> QFrame:
        c = QFrame()
        c.setObjectName("kpiCard")
        c.setStyleSheet(
            f"#kpiCard {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(4)

        # Top row: label + (опц.) дельта-чип
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        top.addWidget(l)
        top.addStretch(1)
        delta_chip = self._delta_chip(delta_pct)
        if delta_chip is not None:
            top.addWidget(delta_chip)
        v.addLayout(top)

        val = QLabel(value)
        val.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        s = QLabel(sub)
        s.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt;"
            f" border: none; background: transparent;"
        )

        v.addWidget(val)
        v.addWidget(s)
        return c

    def _delta_chip(self, pct_str: str | None) -> QLabel | None:
        """Чип «↑ 5.0% к прошлой смене» / «↓ 3.2%» / «–».

        pct_str: строковое значение в процентах (с одной десятой, может быть
        отрицательным или None если предыдущей смены не было).
        """
        if pct_str is None:
            return None
        try:
            val = float(pct_str)
        except (TypeError, ValueError):
            return None
        if abs(val) < 0.05:
            arrow, color, bg = "→", COLORS["text_secondary"], COLORS["bg_gray"]
        elif val > 0:
            arrow, color = "↑", "#16A34A"  # green-600
            bg = "#DCFCE7"  # green-100
        else:
            arrow, color = "↓", "#DC2626"  # red-600
            bg = "#FEE2E2"  # red-100
        sign = "+" if val > 0 else ""
        chip = QLabel(f"{arrow} {sign}{val:.1f}%")
        chip.setStyleSheet(
            f"QLabel {{"
            f"  background: {bg}; color: {color};"
            f"  border: none; border-radius: 8px;"
            f"  padding: 2px 8px;"
            f"  font-size: 10pt; font-weight: 700;"
            f"}}"
        )
        chip.setToolTip("В сравнении с предыдущей сменой")
        return chip

    def _render_summary_details(self) -> None:
        # Очистить grid
        while self._details_grid.count():
            child = self._details_grid.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if self._report is None:
            return

        # Колонка 1: Оплата по способам
        col1 = self._details_card("Оплата по способам")
        col1_v = col1._body
        sales_pay = self._report.get("sales_by_payment") or {}
        labels = {"cash": "Наличные", "card": "Банк. карта", "transfer": "Перевод"}
        total_pay = 0.0
        for code, label in labels.items():
            value = sales_pay.get(code) or "0.00"
            col1_v.addWidget(self._kv_row(label, f"{value} TJS"))
            try:
                total_pay += float(value)
            except (TypeError, ValueError):
                pass
        col1_v.addWidget(self._divider())
        col1_v.addWidget(self._kv_row("Итого", f"{total_pay:.2f} TJS", bold=True))

        # Колонка 2: Продажи по категориям
        col2 = self._details_card("Продажи по категориям")
        col2_v = col2._body
        for cat in (self._report.get("sales_by_category") or [])[:8]:
            qty = cat.get("qty", 0)
            label = f"{cat.get('name', '?')} ({qty} шт)"
            col2_v.addWidget(self._kv_row(label, f"{cat.get('total', '0.00')} TJS"))

        # Колонка 3: По типу заказа + касса
        col3 = self._details_card("По типу заказа")
        col3_v = col3._body
        type_labels = {"hall": "В зале", "takeaway": "С собой", "delivery": "Доставка"}
        for row in self._report.get("sales_by_order_type") or []:
            t = type_labels.get(row.get("type", ""), row.get("type"))
            n = row.get("orders_count", 0)
            col3_v.addWidget(self._kv_row(f"{t} ({n})", f"{row.get('total', '0.00')} TJS"))

        col4 = self._details_card("Касса")
        col4_v = col4._body
        shift = self._report.get("shift") or {}
        col4_v.addWidget(self._kv_row("Остаток на начало", f"{shift.get('opening_balance', '0')} TJS"))
        col4_v.addWidget(
            self._kv_row("+ Наличная выручка", f"{sales_pay.get('cash', '0.00')} TJS")
        )
        # Cash-in / cash-out (если были)
        cash_in_total = shift.get("cash_in_total") or "0.00"
        cash_out_total = shift.get("cash_out_total") or "0.00"
        if cash_in_total not in (None, "", "0", "0.00"):
            col4_v.addWidget(
                self._kv_row("+ Внесения", f"{cash_in_total} TJS")
            )
        if cash_out_total not in (None, "", "0", "0.00"):
            col4_v.addWidget(
                self._kv_row("− Изъятия", f"{cash_out_total} TJS")
            )
        col4_v.addWidget(self._divider())
        col4_v.addWidget(
            self._kv_row("Ожидаемо", f"{shift.get('expected_balance', '0.00')} TJS")
        )
        if shift.get("actual_balance"):
            col4_v.addWidget(
                self._kv_row("Фактический", f"{shift['actual_balance']} TJS", bold=True)
            )
            disc = shift.get("discrepancy")
            if disc is not None:
                col4_v.addWidget(self._kv_row("Расхождение", f"{disc} TJS"))

        # 2 колонки точно по дизайну frame 15:
        # left: Оплата по способам + Продажи по категориям (vertical stack)
        # right: По типу заказа + Касса (vertical stack)
        self._details_grid.addWidget(col1, 0, 0)  # Оплата
        self._details_grid.addWidget(col3, 0, 1)  # По типу
        self._details_grid.addWidget(col2, 1, 0)  # Категории
        self._details_grid.addWidget(col4, 1, 1)  # Касса
        self._details_grid.setColumnStretch(0, 1)
        self._details_grid.setColumnStretch(1, 1)

    def _details_card(self, title: str) -> QFrame:
        f = QFrame()
        f.setObjectName("detailsCard")
        f.setStyleSheet(
            f"#detailsCard {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        t = QLabel(title)
        t.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 13pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(t)

        body = QVBoxLayout()
        body.setSpacing(6)
        body_holder = QWidget()
        body_holder.setLayout(body)
        body.setObjectName("cardBody")  # для findChild
        v.addWidget(body_holder)
        # findChild ищет QObject — layout не QObject. Вместо этого вернём
        # QVBoxLayout через атрибут на frame.
        f._body = body
        # Перепривязка — нам нужен поиск через имя
        f.setProperty("body_holder", body_holder)
        return f

    def _kv_row(self, label: str, value: str, *, bold: bool = False) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; border: none; background: transparent;"
        )
        v = QLabel(value)
        weight = "700" if bold else "600"
        v.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: {weight};"
            f" border: none; background: transparent;"
        )
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(l)
        h.addStretch(1)
        h.addWidget(v)
        return row

    def _divider(self) -> QFrame:
        s = QFrame()
        s.setFixedHeight(1)
        s.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        return s

    def _render_waiters_table(self) -> None:
        rows = self._report.get("sales_by_waiter") or []
        self._waiters_table.setRowCount(len(rows) + 1)  # +1 для итоговой строки
        total_orders = 0
        total_sum = 0.0
        for i, r in enumerate(rows):
            self._waiters_table.setItem(i, 0, QTableWidgetItem(r.get("name", "")))
            self._waiters_table.setItem(i, 1, QTableWidgetItem(str(r.get("orders_count", 0))))
            self._waiters_table.setItem(i, 2, QTableWidgetItem(f"{r.get('total', '0.00')} TJS"))
            self._waiters_table.setItem(i, 3, QTableWidgetItem(f"{r.get('avg_check', '0.00')} TJS"))
            total_orders += int(r.get("orders_count", 0))
            try:
                total_sum += float(r.get("total", 0))
            except (TypeError, ValueError):
                pass

        # Итого
        i = len(rows)
        bold_item = QTableWidgetItem("Итого")
        f = bold_item.font()
        f.setBold(True)
        bold_item.setFont(f)
        self._waiters_table.setItem(i, 0, bold_item)
        for col, val in enumerate(
            [str(total_orders), f"{total_sum:.2f} TJS", ""], start=1
        ):
            it = QTableWidgetItem(val)
            it.setFont(f)
            self._waiters_table.setItem(i, col, it)

        self._waiters_table.resizeColumnsToContents()
        self._waiters_table.horizontalHeader().setStretchLastSection(True)

    # -------- handlers --------

    def _on_nav(self, name: str) -> None:
        if name == "logout":
            self.logout_requested.emit()
        else:
            self.back_requested.emit()
