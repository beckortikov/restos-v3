"""Phase 7 — UI «Аналитика».

4 вкладки:
- Часы пик (heatmap день недели × час)
- Food cost % по категориям
- Аналитика по официантам
- ABC-снимки меню/склада

Базовые таблицы с фильтром период (from/to).
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
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

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


DOW_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class _BasePane(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._build()
        self._load()

    def _build(self) -> None:
        raise NotImplementedError

    def _load(self) -> None:
        raise NotImplementedError

    def _date_filter(self) -> tuple[QDateEdit, QDateEdit, QPushButton]:
        from_edit = QDateEdit(QDate.currentDate().addDays(-30))
        from_edit.setDisplayFormat("yyyy-MM-dd")
        from_edit.setCalendarPopup(True)
        from_edit.setFixedHeight(36)
        to_edit = QDateEdit(QDate.currentDate())
        to_edit.setDisplayFormat("yyyy-MM-dd")
        to_edit.setCalendarPopup(True)
        to_edit.setFixedHeight(36)
        btn = QPushButton("Обновить")
        btn.setFixedHeight(36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
        )
        return from_edit, to_edit, btn

    def _params(self) -> dict:
        return {
            "from": self._from_edit.date().toString("yyyy-MM-dd"),
            "to": self._to_edit.date().toString("yyyy-MM-dd"),
        }


class PeakHoursPane(_BasePane):
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        top = QHBoxLayout()
        self._from_edit, self._to_edit, refresh = self._date_filter()
        top.addWidget(QLabel("С:"))
        top.addWidget(self._from_edit)
        top.addWidget(QLabel("По:"))
        top.addWidget(self._to_edit)
        refresh.clicked.connect(self._load)
        top.addWidget(refresh)
        top.addStretch(1)
        v.addLayout(top)

        # 7 строк (дни недели) × 24 столбца (часы)
        self._table = QTableWidget(7, 24)
        self._table.setHorizontalHeaderLabels([str(h) for h in range(24)])
        self._table.setVerticalHeaderLabels(DOW_LABELS)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  gridline-color: {COLORS['border_light']};"
            f"  font-size: 10pt;"
            f"}}"
        )
        self._table.horizontalHeader().setDefaultSectionSize(38)
        v.addWidget(self._table, 1)

    def _load(self) -> None:
        try:
            data = self._client.get("/analytics/peak-hours/", params=self._params())
            cells = (data or {}).get("data", []) if isinstance(data, dict) else data
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return

        # Очистка таблицы
        for r in range(7):
            for c in range(24):
                self._table.setItem(r, c, QTableWidgetItem(""))

        if not cells:
            return
        max_count = max((int(c.get("count", 0)) for c in cells), default=1)
        for cell in cells:
            r = int(cell.get("dow", 0))
            c = int(cell.get("hour", 0))
            cnt = int(cell.get("count", 0))
            if not (0 <= r < 7 and 0 <= c < 24):
                continue
            item = QTableWidgetItem(str(cnt) if cnt else "")
            item.setTextAlignment(Qt.AlignCenter)
            if cnt > 0:
                # Heatmap: интенсивность оранжевого
                intensity = cnt / max_count
                alpha = int(40 + intensity * 200)
                item.setBackground(QBrush(QColor(244, 122, 32, alpha)))
                if intensity > 0.5:
                    item.setForeground(QBrush(QColor("#FFFFFF")))
            self._table.setItem(r, c, item)


class FoodCostPane(_BasePane):
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        top = QHBoxLayout()
        self._from_edit, self._to_edit, refresh = self._date_filter()
        top.addWidget(QLabel("С:"))
        top.addWidget(self._from_edit)
        top.addWidget(QLabel("По:"))
        top.addWidget(self._to_edit)
        refresh.clicked.connect(self._load)
        top.addWidget(refresh)
        self._totals_lbl = QLabel("")
        self._totals_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; font-weight: 600; padding-left: 16px;"
        )
        top.addWidget(self._totals_lbl)
        top.addStretch(1)
        v.addLayout(top)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            "Категория", "Выручка", "Себестоимость", "Food-cost %", "Кол-во",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._table, 1)

    def _load(self) -> None:
        try:
            data = self._client.get("/analytics/food-cost/", params=self._params())
            body = (data or {}).get("data") if isinstance(data, dict) else None
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        if not body:
            return
        totals = body.get("totals", {})
        self._totals_lbl.setText(
            f"Итого: выручка {totals.get('revenue', '0')} · "
            f"COGS {totals.get('cogs', '0')} · "
            f"FC% {totals.get('food_cost_pct', '0')}"
        )
        cats = body.get("categories", [])
        self._table.setRowCount(len(cats))
        for i, c in enumerate(cats):
            self._table.setItem(i, 0, QTableWidgetItem(c.get("name", "")))
            self._table.setItem(i, 1, QTableWidgetItem(str(c.get("revenue", "0"))))
            self._table.setItem(i, 2, QTableWidgetItem(str(c.get("cogs", "0"))))
            pct = c.get("food_cost_pct", "0")
            pct_item = QTableWidgetItem(f"{pct}%")
            try:
                pct_v = float(pct)
                if pct_v > 40:
                    pct_item.setForeground(QBrush(QColor(COLORS["danger_red"])))
                elif pct_v > 30:
                    pct_item.setForeground(QBrush(QColor(COLORS["accent_orange"])))
                else:
                    pct_item.setForeground(QBrush(QColor(COLORS["success_green"])))
            except (TypeError, ValueError):
                pass
            self._table.setItem(i, 3, pct_item)
            self._table.setItem(i, 4, QTableWidgetItem(str(c.get("items_count", "0"))))


class WaiterAnalyticsPane(_BasePane):
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        top = QHBoxLayout()
        self._from_edit, self._to_edit, refresh = self._date_filter()
        top.addWidget(QLabel("С:"))
        top.addWidget(self._from_edit)
        top.addWidget(QLabel("По:"))
        top.addWidget(self._to_edit)
        refresh.clicked.connect(self._load)
        top.addWidget(refresh)
        top.addStretch(1)
        v.addLayout(top)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            "Официант", "Заказы", "Выручка", "Средний чек", "Гости",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._table, 1)

    def _load(self) -> None:
        try:
            data = self._client.get("/analytics/waiters/", params=self._params())
            rows = (data or {}).get("data", []) if isinstance(data, dict) else data
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        rows = rows or []
        self._table.setRowCount(len(rows))
        for i, w in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(w.get("name", "")))
            self._table.setItem(i, 1, QTableWidgetItem(str(w.get("orders_count", 0))))
            self._table.setItem(i, 2, QTableWidgetItem(str(w.get("revenue", "0"))))
            self._table.setItem(i, 3, QTableWidgetItem(str(w.get("average_check", "0"))))
            self._table.setItem(i, 4, QTableWidgetItem(str(w.get("guests_total", 0))))


class AbcSnapshotsPane(_BasePane):
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        top = QHBoxLayout()
        self._from_edit, self._to_edit, _ = self._date_filter()
        top.addWidget(QLabel("С:"))
        top.addWidget(self._from_edit)
        top.addWidget(QLabel("По:"))
        top.addWidget(self._to_edit)

        self._kind_combo = QComboBox()
        self._kind_combo.addItem("Меню", "menu")
        self._kind_combo.addItem("Склад", "inventory")
        self._kind_combo.setFixedHeight(36)
        top.addWidget(self._kind_combo)

        create_btn = QPushButton("Создать снимок")
        create_btn.setFixedHeight(36)
        create_btn.setCursor(Qt.PointingHandCursor)
        create_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
        )
        create_btn.clicked.connect(self._on_create)
        top.addWidget(create_btn)

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
        refresh.clicked.connect(self._load)
        top.addWidget(refresh)
        top.addStretch(1)
        v.addLayout(top)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Тип", "Период", "Выручка", "COGS", "Маржа", "Позиций",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._table, 1)

    def _on_create(self) -> None:
        body = {
            "kind": self._kind_combo.currentData() or "menu",
            "from": self._from_edit.date().toString("yyyy-MM-dd"),
            "to": self._to_edit.date().toString("yyyy-MM-dd"),
        }
        try:
            self._client.post(
                "/analytics/abc-snapshots/", json=body, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self._load()

    def _load(self) -> None:
        try:
            data = self._client.get("/analytics/abc-snapshots/")
            rows = (data or {}).get("data", []) if isinstance(data, dict) else data
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        rows = rows or []
        self._table.setRowCount(len(rows))
        for i, s in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(s.get("kind", "")))
            self._table.setItem(
                i, 1, QTableWidgetItem(f"{s.get('period_from','')} – {s.get('period_to','')}")
            )
            self._table.setItem(i, 2, QTableWidgetItem(str(s.get("total_revenue", "0"))))
            self._table.setItem(i, 3, QTableWidgetItem(str(s.get("total_cogs", "0"))))
            self._table.setItem(i, 4, QTableWidgetItem(str(s.get("total_margin", "0"))))
            self._table.setItem(i, 5, QTableWidgetItem(str(s.get("lines_count", 0))))


class AnalyticsSection(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Аналитика")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
            f" padding: {SPACING['lg']}px {SPACING['xl']}px 0 {SPACING['xl']}px;"
        )
        v.addWidget(title)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabBar::tab {{ padding: 8px 16px; font-size: 11pt; }}"
            f"QTabBar::tab:selected {{ font-weight: 700; color: {COLORS['accent_orange']}; }}"
        )
        self._peak = PeakHoursPane(self._client)
        self._food = FoodCostPane(self._client)
        self._waiters = WaiterAnalyticsPane(self._client)
        self._abc = AbcSnapshotsPane(self._client)
        tabs.addTab(self._peak, "Часы пик")
        tabs.addTab(self._food, "Food cost")
        tabs.addTab(self._waiters, "Официанты")
        tabs.addTab(self._abc, "ABC снимки")
        v.addWidget(tabs, 1)
