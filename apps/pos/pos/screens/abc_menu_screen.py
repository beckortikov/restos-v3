"""ABC-анализ меню — экран отчёта.

Загружает /api/v1/analytics/abc-menu/?from=&to= и показывает таблицу:
- блюдо / категория
- продано, выручка, себестоимость, маржа, маржа %
- цветной chip класса A/B/C
- доля выручки и накопит. доля

Дефолт периода — последние 30 дней. Кнопка «Применить» с двумя date-pickers.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State


class _LoadWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, dfrom: str, dto: str) -> None:
        super().__init__()
        self.client = client
        self.dfrom = dfrom
        self.dto = dto

    def run(self) -> None:
        try:
            data = self.client.get(
                "/analytics/abc-menu/",
                params={"from": self.dfrom, "to": self.dto},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


CLASS_COLORS = {
    "A": ("#16A34A", "#DCFCE7"),  # зелёный — топ-выручка
    "B": ("#CA8A04", "#FEF9C3"),  # жёлтый
    "C": ("#9CA3AF", "#F3F4F6"),  # серый — хвост
}


class AbcMenuScreen(QWidget):
    """Экран ABC-аналитики (открывается из Settings → Отчёты → ABC-анализ)."""

    back_requested = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"AbcMenuScreen {{ background: {COLORS['bg_light']}; }}"
        )
        self._build()
        # Дефолт — последние 30 дней
        today = date.today()
        self._from_edit.setDate(today - timedelta(days=30))
        self._to_edit.setDate(today)

    # -------- build --------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        # Header
        head = QHBoxLayout()
        back = QPushButton("← Назад")
        back.setFixedHeight(36)
        back.setCursor(Qt.PointingHandCursor)
        back.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        back.clicked.connect(self.back_requested.emit)
        head.addWidget(back)

        title = QLabel("ABC-анализ меню")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 800;"
        )
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)

        # Filters row
        filters = QHBoxLayout()
        filters.setSpacing(SPACING["md"])
        filters.addWidget(self._lbl("Период: с"))
        self._from_edit = QDateEdit()
        self._from_edit.setCalendarPopup(True)
        self._from_edit.setDisplayFormat("yyyy-MM-dd")
        self._from_edit.setFixedHeight(34)
        self._from_edit.setStyleSheet(self._date_qss())
        filters.addWidget(self._from_edit)
        filters.addWidget(self._lbl("по"))
        self._to_edit = QDateEdit()
        self._to_edit.setCalendarPopup(True)
        self._to_edit.setDisplayFormat("yyyy-MM-dd")
        self._to_edit.setFixedHeight(34)
        self._to_edit.setStyleSheet(self._date_qss())
        filters.addWidget(self._to_edit)

        apply_btn = QPushButton("Применить")
        apply_btn.setFixedHeight(34)
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        apply_btn.clicked.connect(self.reload)
        filters.addWidget(apply_btn)
        filters.addStretch(1)
        v.addLayout(filters)

        # Totals strip
        self._totals_lbl = QLabel("Загрузка…")
        self._totals_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700;"
            f" padding: 8px 14px;"
            f" background: {COLORS['bg_white']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        v.addWidget(self._totals_lbl)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "Класс", "Блюдо", "Категория",
            "Прод.", "Выручка", "Себест.",
            "Маржа", "Маржа %", "Доля выручки",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
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
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setColumnWidth(0, 60)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self._table, 1)

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        return l

    def _date_qss(self) -> str:
        return (
            f"QDateEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 4px 8px; font-size: 11pt;"
            f"}}"
        )

    # -------- load --------

    def reload(self) -> None:
        dfrom = self._from_edit.date().toString("yyyy-MM-dd")
        dto = self._to_edit.date().toString("yyyy-MM-dd")
        if dfrom > dto:
            QMessageBox.warning(
                self, "Ошибка", "Дата «от» должна быть не позже даты «до»",
            )
            return
        self._totals_lbl.setText("Загрузка…")
        thread = QThread(self)
        worker = _LoadWorker(self.state.client, dfrom, dto)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_loaded)
        worker.error.connect(self._on_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_loaded(self, data: dict) -> None:
        totals = data.get("totals", {})
        items_count = totals.get("items_count", 0)
        revenue = totals.get("revenue", "0.00")
        margin = totals.get("margin", "0.00")
        margin_pct = totals.get("margin_pct", "0.00")
        self._totals_lbl.setText(
            f"Блюд: {items_count}    "
            f"Выручка: {revenue} TJS    "
            f"Маржа: {margin} TJS ({margin_pct}%)"
        )

        rows = data.get("rows") or []
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cls = r.get("abc_class", "C")
            fg, bg = CLASS_COLORS.get(cls, CLASS_COLORS["C"])
            chip = QTableWidgetItem(cls)
            chip.setTextAlignment(Qt.AlignCenter)
            from PySide6.QtGui import QBrush, QColor
            chip.setForeground(QBrush(QColor(fg)))
            chip.setBackground(QBrush(QColor(bg)))
            self._table.setItem(i, 0, chip)

            self._table.setItem(i, 1, QTableWidgetItem(r.get("name", "")))
            self._table.setItem(i, 2, QTableWidgetItem(r.get("category_name", "")))
            self._table.setItem(i, 3, self._num(r.get("sold_qty", 0)))
            self._table.setItem(i, 4, self._num(r.get("revenue", "0")))
            self._table.setItem(i, 5, self._num(r.get("cogs_total", "0")))
            self._table.setItem(i, 6, self._num(r.get("margin", "0")))
            self._table.setItem(i, 7, self._num(f"{r.get('margin_pct', '0')}%"))
            self._table.setItem(
                i, 8,
                self._num(
                    f"{r.get('revenue_share_pct', '0')}%  "
                    f"(нар. {r.get('cumulative_share_pct', '0')}%)"
                ),
            )

    def _num(self, value) -> QTableWidgetItem:
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return item

    def _on_error(self, exc: ApiError) -> None:
        self._totals_lbl.setText("Ошибка загрузки")
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить ABC-анализ:\n[{exc.code}] {exc.message}",
        )
