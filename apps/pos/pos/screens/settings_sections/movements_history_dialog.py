"""История движений ингредиента — read-only список."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as tz

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.resources.icons import qicon


DUSHANBE = tz(timedelta(hours=5))

KIND_LABEL = {
    "purchase":          "Приёмка",
    "consume":           "Расход (заказ)",
    "produce_semi":      "Расход (п/ф)",
    "waste":             "Списание",
    "inventory_correct": "Инвент.",
    "return_to_supplier": "Возврат",
    "manual":            "Ручная",
}


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(DUSHANBE).strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return iso[:16]


class _LoadHistoryWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient, ing_id: int) -> None:
        super().__init__()
        self.client = client
        self.ing_id = ing_id

    def run(self) -> None:
        try:
            data = self.client.get(
                f"/inventory/ingredients/{self.ing_id}/movements/",
                params={"limit": 200},
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class MovementsHistoryDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        ingredient: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._ing = ingredient
        self._threads: list[QThread] = []
        self.setWindowTitle(f"История · {ingredient.get('name', '?')}")
        self.setModal(True)
        self.setFixedSize(1000, 820)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 16px;"
            f"}}"
        )
        self._build()
        self._load()

    def _build(self) -> None:
        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header (64px)
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-top-left-radius: 15px;"
            f"  border-top-right-radius: 15px;"
            f"}}"
        )
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(24, 0, 24, 0)
        head_lay.setSpacing(12)

        hist_icon = QLabel()
        hist_icon.setPixmap(qicon("history", COLORS["primary_blue"], 22).pixmap(22, 22))
        hist_icon.setStyleSheet("border: none; background: transparent;")
        head_lay.addWidget(hist_icon)

        meta_stack = QVBoxLayout()
        meta_stack.setSpacing(2)
        doc_title = QLabel("История движений")
        doc_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_title)
        doc_subtitle = QLabel(f"Ингредиент:  {self._ing.get('name', '?')}")
        doc_subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_subtitle)
        head_lay.addLayout(meta_stack)

        head_lay.addStretch(1)

        close_btn = QPushButton()
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 20))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: #F1F5F9; border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.reject)
        head_lay.addWidget(close_btn)
        root.addWidget(header)

        # 2. Filter Bar (fRIDw)
        filter_bar = QWidget()
        filter_bar.setFixedHeight(56)
        filter_bar.setStyleSheet(
            f"QWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        flt_lay = QHBoxLayout(filter_bar)
        flt_lay.setContentsMargins(24, 0, 24, 0)
        flt_lay.setSpacing(10)

        flt_title = QLabel("Фильтр:")
        flt_title.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9.5pt; font-weight: 600; border: none;"
        )
        flt_lay.addWidget(flt_title)

        # Add visual chip buttons matching Frame 40
        all_chip = QPushButton("Все события")
        all_chip.setFixedHeight(30)
        all_chip.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 6px;"
            f"  padding: 0 12px; font-size: 9pt; font-weight: 600;"
            f"}}"
        )
        flt_lay.addWidget(all_chip)

        for name in ["Приёмка", "Расход", "Списание", "Инвентаризация"]:
            chip = QPushButton(name)
            chip.setFixedHeight(30)
            chip.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']}; border-radius: 6px;"
                f"  padding: 0 12px; font-size: 9pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            flt_lay.addWidget(chip)

        flt_lay.addStretch(1)

        period_title = QLabel("За период:")
        period_title.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9.5pt; font-weight: 600; border: none;"
        )
        flt_lay.addWidget(period_title)

        range_btn = QPushButton("За все время")
        range_btn.setFixedHeight(30)
        range_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']}; border-radius: 6px;"
            f"  padding: 0 12px; font-size: 9pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        flt_lay.addWidget(range_btn)
        root.addWidget(filter_bar)

        # 3. Table Area (qcstI)
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Дата и время", "Тип операции", "Δ Количество", "Учетная цена", "Основание / Причина",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  alternate-background-color: #FAFBFC;"
            f"  gridline-color: transparent;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none; padding: 10px 12px; font-weight: 700; font-size: 10pt;"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
            f"QTableWidget::item {{"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  padding: 10px 12px;"
            f"  font-size: 10.5pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Stretch)

        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        table_container = QWidget()
        table_container.setStyleSheet("background: transparent; border: none;")
        table_lay = QVBoxLayout(table_container)
        table_lay.setContentsMargins(24, 16, 24, 16)
        table_lay.addWidget(self._table)
        root.addWidget(table_container, 1)

        # 4. Statistics Footer (B64zHO)
        stat_footer = QFrame()
        stat_footer.setFixedHeight(64)
        stat_footer.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  border-bottom-left-radius: 15px;"
            f"  border-bottom-right-radius: 15px;"
            f"}}"
        )
        stat_lay = QHBoxLayout(stat_footer)
        stat_lay.setContentsMargins(24, 0, 24, 0)
        stat_lay.setSpacing(16)

        self.stat_lbl = QLabel("Показано: 0 из 0 событий")
        self.stat_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10.5pt; font-weight: 600;"
        )
        stat_lay.addWidget(self.stat_lbl)

        stat_lay.addStretch(1)

        close = QPushButton("Закрыть")
        close.setFixedHeight(40)
        close.setMinimumWidth(120)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 0 20px; font-size: 10.5pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        close.clicked.connect(self.accept)
        stat_lay.addWidget(close)
        root.addWidget(stat_footer)

    def _load(self) -> None:
        thread = QThread(self)
        worker = _LoadHistoryWorker(self._client, int(self._ing["id"]))
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

    def _on_loaded(self, items: list) -> None:
        self._table.setRowCount(len(items))
        for i, mv in enumerate(items):
            # Дата и время
            date_item = QTableWidgetItem(_fmt_dt(mv.get("created_at")))
            self._table.setItem(i, 0, date_item)

            # Тип операции
            type_str = KIND_LABEL.get(mv.get("kind", ""), mv.get("kind", ""))
            type_item = QTableWidgetItem(type_str)
            self._table.setItem(i, 1, type_item)

            # Δ количество — цветное
            delta_str = str(mv.get("qty_delta", "0"))
            try:
                d = float(delta_str)
            except (TypeError, ValueError):
                d = 0
            delta_item = QTableWidgetItem(
                f"+{delta_str}" if d > 0 else delta_str
            )
            delta_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            color = COLORS["success_green"] if d > 0 else COLORS["danger_red"]
            delta_item.setForeground(QBrush(QColor(color)))
            f = delta_item.font()
            f.setBold(True)
            delta_item.setFont(f)
            self._table.setItem(i, 2, delta_item)

            # Учетная цена — деньги, 2 dp
            uc = mv.get("unit_cost")
            uc_str = f"{float(uc):,.2f} TJS" if uc else "—"
            uc_item = QTableWidgetItem(uc_str)
            uc_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(i, 3, uc_item)

            # Основание / Причина
            reason_str = mv.get("reason", "")
            reason_item = QTableWidgetItem(reason_str)
            self._table.setItem(i, 4, reason_item)

        self.stat_lbl.setText(f"Показано: {len(items)} из {len(items)} событий")

    def _on_error(self, exc: ApiError) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить историю:\n[{exc.code}] {exc.message}",
        )

