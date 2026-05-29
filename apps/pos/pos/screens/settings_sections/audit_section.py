"""Раздел «Журнал действий» — read-only лист audit-записей.

Frame не размечен в дизайне — делаем по аналогии с frame 12 (history):
- Header с фильтром по action (combo)
- Список строк: дата · пользователь · действие · target · краткий payload
- Pagination (50 на странице, кнопка «Загрузить ещё»)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING

ACTION_FILTERS: list[tuple[str, str]] = [
    ("", "Все действия"),
    ("login", "Вход"),
    ("shift_open", "Открытие смены"),
    ("shift_close", "Закрытие смены"),
    ("order_create", "Создание заказа"),
    ("order_close", "Закрытие заказа"),
    ("order_cancel", "Отмена заказа"),
    ("order_transfer", "Перенос"),
    ("item_cancel", "Отмена позиции"),
    ("discount_apply", "Применение скидки"),
    ("discount_remove", "Снятие скидки"),
    ("refund", "Возврат"),
    ("user_create", "Создание пользователя"),
    ("user_update", "Изменение пользователя"),
    ("user_delete", "Удаление пользователя"),
    ("pin_change", "Смена PIN"),
]

# Цвета бейджа по action для быстрого визуального скана.
ACTION_COLOR = {
    "login": COLORS["primary_blue"],
    "shift_open": COLORS["success_green"],
    "shift_close": COLORS["accent_orange"],
    "order_create": COLORS["primary_blue"],
    "order_close": COLORS["success_green"],
    "order_cancel": COLORS["danger_red"],
    "order_transfer": COLORS["primary_blue"],
    "item_cancel": COLORS["danger_red"],
    "discount_apply": "#7C3AED",
    "discount_remove": COLORS["text_secondary"],
    "refund": COLORS["danger_red"],
}


class _ListWorker(QObject):
    success = Signal(list, int)  # entries, total
    error = Signal(object)

    def __init__(self, client: ApiClient, action: str, page: int) -> None:
        super().__init__()
        self.client = client
        self.action = action
        self.page = page

    def run(self) -> None:
        try:
            params: dict[str, str] = {"page": str(self.page)}
            if self.action:
                params["action"] = self.action
            data = self.client.get("/audit/", params=params)
            # Pagination format: {data: [...], meta: {total, page, page_size, pages}}
            if isinstance(data, dict) and "meta" in data:
                items = data.get("data", [])
                total = int(data.get("meta", {}).get("total", 0))
            elif isinstance(data, list):
                items = data
                total = len(items)
            else:
                items = (data or {}).get("data", [])
                total = len(items)
            self.success.emit(list(items), total)
        except ApiError as e:
            self.error.emit(e)


class AuditSection(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._entries: list[dict] = []
        self._total: int = 0
        self._page: int = 1
        self._action_filter: str = ""
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"AuditSection {{ background: {COLORS['bg_light']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Header + filter
        head = QHBoxLayout()
        title = QLabel("Журнал действий")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        head.addWidget(title)
        head.addStretch(1)

        self.action_combo = QComboBox()
        for key, label in ACTION_FILTERS:
            self.action_combo.addItem(label, key)
        self.action_combo.setFixedHeight(36)
        self.action_combo.setMinimumWidth(220)
        self.action_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 12pt;"
            f"}}"
        )
        self.action_combo.currentIndexChanged.connect(self._on_filter_change)
        head.addWidget(self.action_combo)
        v.addLayout(head)

        # Список — таблица как QFrame-строки внутри scroll
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header_row())

        self._rows_holder = QWidget()
        self._rows_holder.setStyleSheet("background: transparent;")
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
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cv.addWidget(scroll, 1)
        v.addWidget(card, 1)

        # Footer — счётчик + «Загрузить ещё»
        foot = QHBoxLayout()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        foot.addWidget(self._count_lbl)
        foot.addStretch(1)
        self._more_btn = QPushButton("Загрузить ещё")
        self._more_btn.setFixedHeight(36)
        self._more_btn.setMinimumWidth(160)
        self._more_btn.setEnabled(False)
        self._more_btn.setCursor(Qt.PointingHandCursor)
        self._more_btn.setStyleSheet(
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
        self._more_btn.clicked.connect(self._on_load_more)
        foot.addWidget(self._more_btn)
        v.addLayout(foot)

    COL_WIDTHS = [140, 160, 200, 280, 0]
    COL_LABELS = ["Время", "Пользователь", "Действие", "Объект", "Детали"]

    def _build_header_row(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(40)
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
                f"color: {COLORS['text_secondary']}; font-size: 10pt; font-weight: 700;"
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

    # -------- public --------

    def reload(self) -> None:
        self._page = 1
        self._entries = []
        self._fetch()

    def _on_filter_change(self) -> None:
        self._action_filter = self.action_combo.currentData() or ""
        self._page = 1
        self._entries = []
        self._fetch()

    def _on_load_more(self) -> None:
        self._page += 1
        self._fetch(append=True)

    def _fetch(self, *, append: bool = False) -> None:
        thread = QThread(self)
        worker = _ListWorker(self._client, self._action_filter, self._page)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if append:
            worker.success.connect(self._on_loaded_append)
        else:
            worker.success.connect(self._on_loaded_replace)
        worker.error.connect(self._on_load_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_loaded_replace(self, items: list, total: int) -> None:
        self._entries = list(items)
        self._total = int(total)
        self._render()

    def _on_loaded_append(self, items: list, total: int) -> None:
        self._entries.extend(items)
        self._total = int(total)
        self._render()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось загрузить журнал: {exc.message}"
        )

    # -------- render --------

    def _render(self) -> None:
        while self._rows_layout.count():
            child = self._rows_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._entries:
            empty = QLabel("Записей в журнале нет")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt; font-style: italic;"
                f" padding: 60px 0; background: transparent;"
            )
            self._rows_layout.addWidget(empty)
        else:
            for i, e in enumerate(self._entries):
                self._rows_layout.addWidget(self._build_row(e, idx=i))

        self._count_lbl.setText(
            f"Показано {len(self._entries)} из {self._total}"
        )
        self._more_btn.setEnabled(len(self._entries) < self._total)

    def _build_row(self, e: dict, *, idx: int) -> QWidget:
        row = QFrame()
        row.setFixedHeight(48)
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

        def cell(text: str, *, width: int, color: str = COLORS["text_primary"], weight: int = 400) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {color}; font-size: 11pt; font-weight: {weight};"
                f" border: none; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if width > 0:
                lbl.setFixedWidth(width)
            return lbl

        # Время — короткий формат
        ts = (e.get("created_at") or "")[:16].replace("T", " ")
        h.addWidget(cell(ts, width=self.COL_WIDTHS[0],
                         color=COLORS["text_secondary"]))

        user = e.get("user_full_name") or e.get("user_username") or "—"
        h.addWidget(cell(user, width=self.COL_WIDTHS[1]))

        # Action с цветным бейджем
        action_color = ACTION_COLOR.get(e.get("action", ""), COLORS["text_secondary"])
        action_label = e.get("action_label") or e.get("action", "")
        action_lbl = QLabel(action_label)
        action_lbl.setFixedWidth(self.COL_WIDTHS[2])
        action_lbl.setStyleSheet(
            f"color: {action_color}; font-size: 11pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        action_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.addWidget(action_lbl)

        target = (
            f"{e.get('target_type', '')} #{e.get('target_id', '')}"
            if e.get("target_id")
            else ""
        )
        h.addWidget(cell(target, width=self.COL_WIDTHS[3],
                         color=COLORS["text_secondary"]))

        # Payload — короткий summary
        payload = e.get("payload") or {}
        payload_parts = []
        for k, val in list(payload.items())[:3]:
            payload_parts.append(f"{k}={val}")
        details = ", ".join(payload_parts) if payload_parts else ""
        details_lbl = cell(details, width=self.COL_WIDTHS[4],
                           color=COLORS["text_secondary"])
        # stretch на последнюю
        h.addWidget(details_lbl, 1)
        return row
