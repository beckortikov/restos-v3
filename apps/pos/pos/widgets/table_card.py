from PySide6.QtCore import QPoint, Qt, Signal  # noqa: F401  (QPoint used in Signal type)
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS

def _qss(border: str, *, left_accent: bool = False) -> str:
    """border — hex цвета бордера. Если left_accent — слева 3px, остальное 1px."""
    if left_accent:
        return (
            f"#tableCard {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 1px solid {border};"
            f"  border-left: 3px solid {border};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
    return (
        f"#tableCard {{"
        f"  background-color: {COLORS['bg_white']};"
        f"  border: 1px solid {border};"
        f"  border-radius: {RADIUS['sm']}px;"
        f"}}"
    )


# Цвета по статусам (по требованию пользователя):
# free → зелёный, booking → синий, occupied → красный, bill_requested → оранжевый.
CARD_QSS = {
    "free": _qss(COLORS["success_green"]),
    "occupied": _qss(COLORS["danger_red"], left_accent=True),
    "booking": _qss(COLORS["primary_blue"], left_accent=True),
    "bill_requested": _qss(COLORS["accent_orange"], left_accent=True),
    # «merged» — стол объединён в группу с другим, основной заказ на главном
    # столе. Визуально серый и disabled, чтобы не путать кассира.
    "merged": (
        f"#tableCard {{"
        f"  background-color: {COLORS['bg_gray']};"
        f"  border: 1px dashed {COLORS['border_light']};"
        f"  border-radius: {RADIUS['sm']}px;"
        f"}}"
    ),
}

STATUS_COLOR = {
    "free": COLORS["success_green"],
    "occupied": COLORS["danger_red"],
    "booking": COLORS["primary_blue"],
    "bill_requested": COLORS["accent_orange"],
    "merged": COLORS["text_secondary"],
}

STATUS_LABEL = {
    "free": "Свободен",
    "occupied": "Занят",
    "booking": "Бронь",
    "bill_requested": "Счёт",
    "merged": "Объединён",
}


class TableCard(QFrame):
    """Карточка стола для grid'а карты зала. Frame: ms8M8/j5jrP/Lt7v6 в .pen.

    Сигнал clicked(table_id, action) — action ∈ {"pay", "detail", "noop"}."""

    clicked = Signal(int, str)
    # Контекстное меню (правый клик): кассир может зарезервировать свободный
    # стол или принудительно освободить «застрявший» (occupied без заказа).
    context_menu_requested = Signal(int, "QPoint")
    # Клик по конкретной группе (multi-group): открыть OrderDetailPanel этой группы.
    group_clicked = Signal(int, int)  # (table_id, order_id)

    # Высота фиксирована — кол-во столов НЕ меняет визуальную высоту карточек,
    # переполнение → vertical scroll. Ширина = Expanding в пределах grid-колонки
    # → карточки заполняют всё доступное место по горизонтали.
    CARD_WIDTH = 180   # минимум-эталон для расчёта кол-ва колонок
    CARD_HEIGHT = 120  # фиксированная высота
    # Алиасы для совместимости (старые тесты могут ссылаться).
    MIN_WIDTH = CARD_WIDTH
    MIN_HEIGHT = CARD_HEIGHT

    def __init__(self, table: dict, total_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tableCard")
        self._table_id: int = int(table["id"])
        self._status: str = table.get("status", "free")
        self._selected: bool = False
        # Список активных групп (для multi-group — может быть >1)
        self._active_orders: list[dict] = list(table.get("active_orders") or [])
        self._build(table, total_text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(TableCard.CARD_WIDTH)
        self.setFixedHeight(TableCard.CARD_HEIGHT)
        # Width=Expanding → растягивается на ячейку grid, Height=Fixed → 120.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        base = CARD_QSS.get(self._status, CARD_QSS["free"])
        if self._selected:
            # Подсветка выбора — толстый бордер цветом статуса.
            color = {
                "free": COLORS["success_green"],
                "occupied": COLORS["danger_red"],
                "booking": COLORS["primary_blue"],
                "bill_requested": COLORS["accent_orange"],
            }.get(self._status, COLORS["accent_orange"])
            sel = (
                f"#tableCard {{"
                f"  background-color: {COLORS['bg_white']};"
                f"  border: 2px solid {color};"
                f"  border-left: 4px solid {color};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"}}"
            )
            self.setStyleSheet(sel)
        else:
            self.setStyleSheet(base)

    def _build(self, table: dict, total_text: str) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(4)
        v.setAlignment(Qt.AlignCenter)

        # Если стол — главный в группе (group.primary_table_id == self.id),
        # показываем «5+6» вместо одного имени.
        title_text = table.get("name") or f"Стол {table.get('number', '?')}"
        group = table.get("group")
        if isinstance(group, dict) and group.get("primary_table_id") == self._table_id:
            names = group.get("table_names") or []
            if len(names) > 1:
                # Извлекаем номера: «Стол 5» → «5».
                short = []
                for n in names:
                    parts = n.split()
                    short.append(parts[-1] if parts else n)
                title_text = "+".join(short)

        title = QLabel(title_text)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )

        # Бейдж резервации (если ближайшая активная резервация в окне +60 мин).
        # «Резерв 19:30 · Иванов ×4» — небольшой синий чип над статусом.
        next_res = table.get("next_reservation")
        reservation_chip = None
        if next_res:
            try:
                from datetime import datetime as _dt
                t = _dt.fromisoformat(
                    str(next_res["scheduled_at"]).replace("Z", "+00:00"),
                )
                time_str = t.strftime("%H:%M")
            except Exception:
                time_str = ""
            chip_text = (
                f"⏰ Резерв {time_str}"
                if time_str else "⏰ Резерв"
            )
            party = next_res.get("party_size") or 0
            if party:
                chip_text += f"  ×{party}"
            reservation_chip = QLabel(chip_text)
            reservation_chip.setAlignment(Qt.AlignCenter)
            reservation_chip.setStyleSheet(
                f"QLabel {{"
                f"  background: #DBEAFE;"  # blue-100
                f"  color: {COLORS['primary_blue']};"
                f"  border: none; border-radius: 6px;"
                f"  padding: 2px 8px;"
                f"  font-size: 9pt; font-weight: 700;"
                f"}}"
            )

        status_text = self._status_text(table, total_text)
        status = QLabel(status_text)
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet(
            f"color: {STATUS_COLOR.get(self._status, COLORS['text_secondary'])};"
            f" font-size: 13pt; font-weight: 500;"
            f" border: none; background: transparent;"
        )

        v.addWidget(title)
        if reservation_chip is not None:
            # Чип в обёртке HBoxLayout, чтобы не растягивался на всю ширину
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wh = QHBoxLayout(wrap)
            wh.setContentsMargins(0, 0, 0, 0)
            wh.addStretch(1)
            wh.addWidget(reservation_chip)
            wh.addStretch(1)
            v.addWidget(wrap)
        # Multi-group rendering: если ≥2 активных заказов на столе, показываем
        # «Гр.1: 2 гостя • 680 с.» / «Гр.2: 3 гостя • 376 с.». Каждая строка
        # кликабельна → group_clicked(table_id, order_id).
        if len(self._active_orders) >= 2:
            for i, og in enumerate(self._active_orders, start=1):
                row = self._build_group_row(i, og)
                v.addWidget(row)
        else:
            v.addWidget(status)

    def _build_group_row(self, idx: int, order: dict) -> QWidget:
        """Кликабельная строка одной группы внутри multi-group карточки."""
        from PySide6.QtWidgets import QPushButton

        guests = int(order.get("guests_count") or 0)
        try:
            total_f = float(order.get("total") or 0)
            total_str = f"{total_f:.0f} с."
        except Exception:
            total_str = ""
        text = f"Гр.{idx}: {guests} {self._guests_word(guests)} • {total_str}"
        # Цвет — оранжевый для активной группы (как в дизайне)
        color = STATUS_COLOR.get(order.get("status") or "occupied",
                                 COLORS["accent_orange"])
        btn = QPushButton(text)
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; border: none;"
            f"  color: {color}; font-size: 11pt; font-weight: 600;"
            f"  text-align: left; padding: 0;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}"
        )
        oid = int(order.get("id") or 0)
        btn.clicked.connect(
            lambda _checked=False, o=oid: self.group_clicked.emit(self._table_id, o)
        )
        return btn

    def _status_text(self, table: dict, total_text: str) -> str:
        if self._status == "free":
            return STATUS_LABEL["free"]

        guests = int(table.get("guests_count") or 0)
        prefix = STATUS_LABEL["bill_requested"] if self._status == "bill_requested" else None

        parts: list[str] = []
        if prefix:
            parts.append(prefix)
        if guests:
            parts.append(f"{guests} {self._guests_word(guests)}")
        if total_text:
            parts.append(total_text)
        return " • ".join(parts) or STATUS_LABEL.get(self._status, self._status)

    @staticmethod
    def _guests_word(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return "гость"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "гостя"
        return "гостей"

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            action = {
                "free": "noop",
                "occupied": "detail",
                "booking": "detail",
                "bill_requested": "pay",
                "merged": "noop",  # клик по смерженному уходит в no-op
            }.get(self._status, "noop")
            self.clicked.emit(self._table_id, action)
        elif event.button() == Qt.RightButton:
            # Контекстное меню: позиция в глобальных координатах для popup.
            self.context_menu_requested.emit(
                self._table_id, event.globalPosition().toPoint(),
            )
        super().mousePressEvent(event)
