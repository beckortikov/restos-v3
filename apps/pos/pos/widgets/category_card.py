"""Карточка категории меню — frame "4. POS — Категории меню" (id 0q10P/9xXxL).

Active state: оранжевый фон, белые текст и иконка. Inactive: белый фон, оранжевая
иконка, primary текст."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from pos.resources.tokens import COLORS, RADIUS

class CategoryCard(QFrame):
    """Карточка категории. Сигнал clicked(category_id).

    По дизайну размер ~180×100 (frame 4). Фиксируем — grid укладывает
    сверху-влево без растягивания (1 категория не должна занимать экран)."""

    clicked = Signal(int)
    # По дизайну fill_container — карточка тянется в ячейке grid'а; задаём
    # только минимальные размеры, реальные ширина/высота — от layout'а.
    MIN_WIDTH = 180
    MIN_HEIGHT = 110

    def __init__(self, category: dict, item_count: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("categoryCard")
        self._category_id: int = int(category["id"])
        self._name: str = category.get("name", "")
        self._item_count = int(item_count)
        self._active: bool = False
        self.setMinimumSize(CategoryCard.MIN_WIDTH, CategoryCard.MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        # Лёгкая тень из дизайна (offset y=2, blur=4, alpha ~0.04).
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(6)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 18))
        self.setGraphicsEffect(shadow)
        self._build()
        self._apply_style()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 16, 12, 16)
        v.setSpacing(6)
        v.setAlignment(Qt.AlignCenter)

        # По требованию пользователя: иконки убраны — только название и счётчик
        # блюд. Шрифт названия — 16pt/700 для читаемости на сенсорном экране.
        self._title = QLabel(self._name)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            f"font-size: 16pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(self._title)

        self._count = QLabel(f"{self._item_count} блюд")
        self._count.setAlignment(Qt.AlignCenter)
        self._count.setStyleSheet(
            f"font-size: 12pt; font-weight: 500;"
            f" border: none; background: transparent;"
        )
        v.addWidget(self._count)

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                f"#categoryCard {{"
                f"  background-color: {COLORS['accent_orange']};"
                f"  border: none;"
                f"  border-radius: {RADIUS['md']}px;"
                f"}}"
            )
            self._title.setStyleSheet(
                f"color: {COLORS['text_white']}; font-size: 16pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            self._count.setStyleSheet(
                f"color: rgba(255,255,255,0.85); font-size: 12pt; font-weight: 500;"
                f" border: none; background: transparent;"
            )
        else:
            self.setStyleSheet(
                f"#categoryCard {{"
                f"  background-color: {COLORS['bg_white']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['md']}px;"
                f"}}"
            )
            self._title.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
                f" border: none; background: transparent;"
            )
            self._count.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt; font-weight: 500;"
                f" border: none; background: transparent;"
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._category_id)
        super().mousePressEvent(event)
