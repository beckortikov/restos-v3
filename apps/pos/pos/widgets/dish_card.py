"""Карточка блюда — frame 4 в design/pos_cashier.pen.

Состояния:
- available (default): белый фон, серый бордер, название по центру, зелёная цена
- selected: оранжевый бордер 1.5px + светло-оранжевый фон, название и цена оранжевые
- stop: светло-красный фон + красный бордер, название красное, надпись «СТОП» красная

`fill_container` из дизайна — карточка тянется внутри grid-ячейки.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from pos.resources.tokens import COLORS, RADIUS

# Эмодзи kind на карточке блюда отключены по запросу — только название и цена.
KIND_EMOJI: dict[str, str] = {}

UNIT_LABEL = {
    "piece": "",
    "g": "г",
    "kg": "кг",
}


class DishCard(QFrame):
    """Сигнал clicked(menu_item_id) — клик добавляет в корзину."""

    clicked = Signal(int)
    # fill_container из дизайна — задаём минимум, остальное растягивает grid.
    MIN_WIDTH = 170
    MIN_HEIGHT = 108

    def __init__(self, item: dict, selected: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dishCard")
        self._item_id: int = int(item["id"])
        self._is_available: bool = bool(item.get("is_available", True))
        self._selected: bool = selected and self._is_available
        self.setMinimumSize(DishCard.MIN_WIDTH, DishCard.MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if self._is_available:
            self.setCursor(Qt.PointingHandCursor)
        self._build(item)
        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = bool(selected) and self._is_available
        self._apply_style()

    def _build(self, item: dict) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(4)
        v.setAlignment(Qt.AlignCenter)

        # Top-row: kind-эмодзи слева, low-stock badge справа (если batch).
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)

        kind = (item.get("kind") or "").strip()
        kind_em = KIND_EMOJI.get(kind, "")
        self._kind_lbl = QLabel(kind_em)
        self._kind_lbl.setStyleSheet(
            "font-size: 14pt; border: none; background: transparent;"
        )
        self._kind_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # Если эмодзи нет — скрываем лейбл целиком, не оставляя пустого места.
        self._kind_lbl.setVisible(bool(kind_em))
        top.addWidget(self._kind_lbl, 0, Qt.AlignLeft)
        top.addStretch(1)

        # Low-stock chip — только для batch-блюд с малым остатком.
        self._lowstock_lbl = QLabel("")
        self._lowstock_lbl.setStyleSheet(
            f"color: {COLORS['accent_orange']};"
            f" font-size: 9pt; font-weight: 700;"
            f" background: #FFF3E0; border: 1px solid {COLORS['accent_orange']};"
            f" border-radius: 4px; padding: 1px 6px;"
        )
        self._lowstock_lbl.setVisible(False)
        if item.get("is_batch_cooking"):
            qty = int(item.get("prepared_qty") or 0)
            if bool(item.get("is_low_stock")):
                self._lowstock_lbl.setText(f"⚠ {qty} порц.")
                self._lowstock_lbl.setVisible(True)
            else:
                # Просто счётчик готовых порций (зелёным)
                self._lowstock_lbl.setText(f"{qty} порц.")
                self._lowstock_lbl.setStyleSheet(
                    f"color: {COLORS['success_green']};"
                    f" font-size: 9pt; font-weight: 700;"
                    f" background: #E8F5E9; border: 1px solid {COLORS['success_green']};"
                    f" border-radius: 4px; padding: 1px 6px;"
                )
                self._lowstock_lbl.setVisible(True)
        top.addWidget(self._lowstock_lbl, 0, Qt.AlignRight)
        v.addLayout(top)

        self._name_lbl = QLabel(item.get("name", ""))
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setAlignment(Qt.AlignCenter)
        # Базовые стили — цвета подменяет _apply_style.
        self._name_lbl.setStyleSheet(
            f"font-size: 13pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        v.addWidget(self._name_lbl, 1)

        price = item.get("price") or "0.00"
        unit = item.get("unit") or "piece"
        unit_size = item.get("unit_size") or 1
        # Для веса: «12.00 / 100г» вместо просто «12.00»
        if unit in ("g", "kg") and unit != "piece":
            price_text = f"{price} / {unit_size}{UNIT_LABEL.get(unit, '')}"
        else:
            price_text = f"{price}"
        self._price_lbl = QLabel(price_text)
        self._price_lbl.setAlignment(Qt.AlignCenter)
        self._price_lbl.setStyleSheet(
            f"font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(self._price_lbl)

        # Метка «СТОП» — только для is_available=False.
        self._stop_lbl = QLabel("СТОП")
        self._stop_lbl.setAlignment(Qt.AlignCenter)
        self._stop_lbl.setStyleSheet(
            f"color: {COLORS['danger_red']}; font-size: 11pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        self._stop_lbl.setVisible(not self._is_available)
        v.addWidget(self._stop_lbl)

    # -------- styling --------

    def _apply_style(self) -> None:
        if not self._is_available:
            # Стоп-лист: светло-красный фон, красный бордер.
            self.setStyleSheet(
                f"#dishCard {{"
                f"  background-color: #FEF2F2;"
                f"  border: 1.5px solid {COLORS['danger_red']};"
                f"  border-radius: {RADIUS['md']}px;"
                f"}}"
            )
            self._name_lbl.setStyleSheet(
                f"color: {COLORS['danger_red']}; font-size: 14pt; font-weight: 600;"
                f" border: none; background: transparent;"
            )
            self._price_lbl.setStyleSheet(
                f"color: {COLORS['danger_red']}; font-size: 14pt; font-weight: 600;"
                f" border: none; background: transparent;"
            )
            return

        if self._selected:
            # Выбранное — светло-оранжевый фон + оранжевый бордер.
            self.setStyleSheet(
                f"#dishCard {{"
                f"  background-color: #FEF3E7;"
                f"  border: 1.5px solid {COLORS['accent_orange']};"
                f"  border-radius: {RADIUS['md']}px;"
                f"}}"
            )
            self._name_lbl.setStyleSheet(
                f"color: {COLORS['accent_orange']}; font-size: 14pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            self._price_lbl.setStyleSheet(
                f"color: {COLORS['accent_orange']}; font-size: 16pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            return

        # Default available: белый фон, серый бордер, зелёная цена.
        self.setStyleSheet(
            f"#dishCard {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
            f"#dishCard:hover {{"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"}}"
        )
        self._name_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        self._price_lbl.setStyleSheet(
            f"color: {COLORS['success_green']}; font-size: 16pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._is_available:
            self.clicked.emit(self._item_id)
        super().mousePressEvent(event)
