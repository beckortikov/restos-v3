"""Phase 6 — UI «Зарплата».

Две вкладки:
- Табель: список TimeEntry за период + кнопка clock_in/clock_out.
- Периоды: расчёт зарплаты за период по сотруднику.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDate

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    return iso.replace("T", " ")[:16]


def _hours_between(iso_in: str | None, iso_out: str | None) -> str:
    if not iso_in or not iso_out:
        return "—"
    from datetime import datetime
    try:
        a = datetime.fromisoformat(iso_in.replace("Z", "+00:00"))
        b = datetime.fromisoformat(iso_out.replace("Z", "+00:00"))
        hours = (b - a).total_seconds() / 3600
        return f"{hours:.2f}"
    except (ValueError, TypeError):
        return "—"


class TimeEntriesPane(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._employees: list[dict] = []
        self._build()
        self._load_employees()
        self._load()
        self._refresh_clock_button()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"]
        )
        v.setSpacing(SPACING["md"])

        # Top bar: clock-in/out для меня + фильтр сотрудника
        top = QHBoxLayout()
        self._clock_btn = QPushButton("Открыть смену")
        self._clock_btn.setFixedHeight(40)
        self._clock_btn.setMinimumWidth(180)
        self._clock_btn.setCursor(Qt.PointingHandCursor)
        self._clock_btn.clicked.connect(self._on_clock)
        top.addWidget(self._clock_btn)

        top.addStretch(1)

        top.addWidget(QLabel("Сотрудник:"))
        self._emp_combo = QComboBox()
        self._emp_combo.setFixedHeight(36)
        self._emp_combo.setMinimumWidth(220)
        self._emp_combo.currentIndexChanged.connect(self._load)
        top.addWidget(self._emp_combo)

        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(36)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setStyleSheet(self._btn_qss())
        refresh.clicked.connect(self._load)
        top.addWidget(refresh)

        v.addLayout(top)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Сотрудник", "Начало", "Конец", "Часы", "Ставка", "Статус",
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
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._table, 1)

    def _btn_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _load_employees(self) -> None:
        try:
            data = self._client.get("/users/")
            users = data if isinstance(data, list) else (data or {}).get("data", [])
        except ApiError:
            users = []
        self._employees = users
        self._emp_combo.clear()
        self._emp_combo.addItem("Все", None)
        for u in users:
            self._emp_combo.addItem(u.get("full_name", "?"), int(u["id"]))

    def _load(self) -> None:
        params = {}
        uid = self._emp_combo.currentData()
        if uid is not None:
            params["user_id"] = uid
        try:
            data = self._client.get("/payroll/time/", params=params)
            items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError:
            items = []
        self._fill_table(items)

    def _fill_table(self, items: list) -> None:
        self._table.setRowCount(len(items))
        STATUS_LABEL = {
            "open": "Открыта", "closed": "Закрыта", "auto_closed": "Авто",
        }
        for i, e in enumerate(items):
            self._table.setItem(i, 0, QTableWidgetItem(e.get("user_name", "")))
            self._table.setItem(i, 1, QTableWidgetItem(_fmt_dt(e.get("clock_in"))))
            self._table.setItem(i, 2, QTableWidgetItem(_fmt_dt(e.get("clock_out"))))
            self._table.setItem(
                i, 3,
                QTableWidgetItem(str(e.get("hours_worked") or _hours_between(
                    e.get("clock_in"), e.get("clock_out"),
                )))
            )
            self._table.setItem(
                i, 4,
                QTableWidgetItem(str(e.get("hourly_rate_snapshot") or "—"))
            )
            self._table.setItem(
                i, 5,
                QTableWidgetItem(STATUS_LABEL.get(e.get("status"), e.get("status", "")))
            )

    def _refresh_clock_button(self) -> None:
        try:
            data = self._client.get("/payroll/time/current/")
            current = (data or {}).get("data") if isinstance(data, dict) else None
        except ApiError:
            current = None
        if current is not None:
            self._clock_btn.setText("Закрыть смену")
            self._clock_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['danger_red']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
                f"}}"
            )
            self._is_open = True
        else:
            self._clock_btn.setText("Открыть смену")
            self._clock_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['success_green']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
                f"}}"
            )
            self._is_open = False

    def _on_clock(self) -> None:
        endpoint = "clock_out" if getattr(self, "_is_open", False) else "clock_in"
        try:
            self._client.post(f"/payroll/time/{endpoint}/", json={}, idempotent=True)
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self._refresh_clock_button()
        self._load()


class PayrollPeriodsPane(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._employees: list[dict] = []
        self._build()
        self._load_employees()
        self._load()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # Top: создать период
        top = QHBoxLayout()
        top.addWidget(QLabel("Сотрудник:"))
        self._emp_combo = QComboBox()
        self._emp_combo.setFixedHeight(36)
        self._emp_combo.setMinimumWidth(200)
        top.addWidget(self._emp_combo)

        top.addWidget(QLabel("С:"))
        self._from_edit = QDateEdit(QDate.currentDate().addDays(-14))
        self._from_edit.setDisplayFormat("yyyy-MM-dd")
        self._from_edit.setCalendarPopup(True)
        self._from_edit.setFixedHeight(36)
        top.addWidget(self._from_edit)

        top.addWidget(QLabel("По:"))
        self._to_edit = QDateEdit(QDate.currentDate())
        self._to_edit.setDisplayFormat("yyyy-MM-dd")
        self._to_edit.setCalendarPopup(True)
        self._to_edit.setFixedHeight(36)
        top.addWidget(self._to_edit)

        top.addWidget(QLabel("Премия:"))
        self._bonus_spin = QDoubleSpinBox()
        self._bonus_spin.setRange(0, 1_000_000)
        self._bonus_spin.setDecimals(2)
        self._bonus_spin.setFixedHeight(36)
        self._bonus_spin.setFixedWidth(100)
        top.addWidget(self._bonus_spin)

        top.addWidget(QLabel("Штраф:"))
        self._deduction_spin = QDoubleSpinBox()
        self._deduction_spin.setRange(0, 1_000_000)
        self._deduction_spin.setDecimals(2)
        self._deduction_spin.setFixedHeight(36)
        self._deduction_spin.setFixedWidth(100)
        top.addWidget(self._deduction_spin)

        calc_btn = QPushButton("Рассчитать")
        calc_btn.setFixedHeight(36)
        calc_btn.setMinimumWidth(140)
        calc_btn.setCursor(Qt.PointingHandCursor)
        calc_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
        )
        calc_btn.clicked.connect(self._on_calculate)
        top.addWidget(calc_btn)

        v.addLayout(top)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            "Сотрудник", "Период", "Часы", "Ставка",
            "База", "Премия", "Штраф", "Итог",
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
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        self._table.cellDoubleClicked.connect(self._on_row_double_click)
        v.addWidget(self._table, 1)

        # Footer hint
        hint = QLabel(
            "<span style='color:#64748B; font-size:10pt'>"
            "Двойной клик по строке → финализировать / выплатить."
            "</span>"
        )
        v.addWidget(hint)

    def _load_employees(self) -> None:
        try:
            data = self._client.get("/users/")
            users = data if isinstance(data, list) else (data or {}).get("data", [])
        except ApiError:
            users = []
        self._employees = users
        self._emp_combo.clear()
        for u in users:
            self._emp_combo.addItem(u.get("full_name", "?"), int(u["id"]))

    def _load(self) -> None:
        try:
            data = self._client.get("/payroll/periods/")
            items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError:
            items = []
        self._periods = items
        self._table.setRowCount(len(items))
        for i, p in enumerate(items):
            self._table.setItem(i, 0, QTableWidgetItem(p.get("user_name", "")))
            self._table.setItem(
                i, 1,
                QTableWidgetItem(f"{p.get('period_start','')} – {p.get('period_end','')}")
            )
            self._table.setItem(i, 2, QTableWidgetItem(str(p.get("hours_worked", "0"))))
            self._table.setItem(i, 3, QTableWidgetItem(str(p.get("hourly_rate", "0"))))
            self._table.setItem(i, 4, QTableWidgetItem(str(p.get("base_salary", "0"))))
            self._table.setItem(i, 5, QTableWidgetItem(str(p.get("bonuses", "0"))))
            self._table.setItem(i, 6, QTableWidgetItem(str(p.get("deductions", "0"))))
            total = QTableWidgetItem(f"{p.get('total','0')} ({p.get('status_display','')})")
            total.setData(Qt.UserRole, p)
            self._table.setItem(i, 7, total)

    def _on_calculate(self) -> None:
        uid = self._emp_combo.currentData()
        if uid is None:
            QMessageBox.warning(self, "Ошибка", "Выберите сотрудника")
            return
        body = {
            "user_id": int(uid),
            "from": self._from_edit.date().toString("yyyy-MM-dd"),
            "to": self._to_edit.date().toString("yyyy-MM-dd"),
            "bonuses": f"{self._bonus_spin.value():.2f}",
            "deductions": f"{self._deduction_spin.value():.2f}",
        }
        try:
            self._client.post(
                "/payroll/periods/calculate/", json=body, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self._load()

    def _on_row_double_click(self, row: int, _col: int) -> None:
        try:
            p = self._table.item(row, 7).data(Qt.UserRole)
        except Exception:
            return
        if not p:
            return
        pid = p.get("id")
        status = p.get("status")
        if status == "draft":
            ans = QMessageBox.question(
                self, "Финализировать?",
                f"Финализировать период {p.get('period_start')}—{p.get('period_end')}?\n"
                "После этого править нельзя.",
            )
            if ans != QMessageBox.Yes:
                return
            try:
                self._client.post(
                    f"/payroll/periods/{pid}/finalize/", json={}, idempotent=True,
                )
            except ApiError as e:
                QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
                return
        elif status == "finalized":
            ans = QMessageBox.question(
                self, "Выплатить?",
                f"Отметить как выплаченное ({p.get('total')} TJS)?",
            )
            if ans != QMessageBox.Yes:
                return
            try:
                self._client.post(
                    f"/payroll/periods/{pid}/pay/", json={}, idempotent=True,
                )
            except ApiError as e:
                QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
                return
        else:
            QMessageBox.information(self, "Готово", "Период уже выплачен")
            return
        self._load()


class PayrollSection(QWidget):
    """Корневой виджет с табами «Табель» / «Периоды»."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        title_bar = QHBoxLayout()
        title = QLabel("Зарплата и табель")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
            f" padding: {SPACING['lg']}px {SPACING['xl']}px 0 {SPACING['xl']}px;"
        )
        title_bar.addWidget(title)
        title_bar.addStretch(1)
        v.addLayout(title_bar)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabBar::tab {{ padding: 8px 16px; font-size: 11pt; }}"
            f"QTabBar::tab:selected {{ font-weight: 700; color: {COLORS['accent_orange']}; }}"
        )

        self._time_pane = TimeEntriesPane(self._client)
        self._periods_pane = PayrollPeriodsPane(self._client)

        tabs.addTab(self._time_pane, "Табель")
        tabs.addTab(self._periods_pane, "Периоды")
        v.addWidget(tabs, 1)
