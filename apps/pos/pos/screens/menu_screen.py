"""Экран меню — frame "4. POS — Категории меню" (id=4dDIq) в design/pos_cashier.pen.

Тонкая обёртка Sidebar + MenuPanel. Используется как отдельный экран в outer
QStackedWidget (`main.py`) для случаев, когда меню запускается НЕ из карты
зала: «С собой» / «Доставка» / дозаказ к существующему заказу из
ActiveOrdersScreen. Для клика по свободному столу зал использует embedded
MenuPanel внутри TablesScreen — без переключения экрана.

Signатуры публичных методов и сигналов сохранены 1:1 с предыдущей версией
MenuScreen, чтобы main.py не требовал изменений.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS
from pos.state import State
from pos.widgets.menu_panel import MenuPanel
from pos.widgets.sidebar import Sidebar


class MenuScreen(QWidget):
    """Сигналы:
        order_submitted(order_id) — успешно создан/обновлён, main возвращает
            пользователя на TablesScreen
        cancelled() — пользователь отменил, без отправки
        requested_logout() — клик «Выйти» в Sidebar
        reservation_requested(table_id) — клик «Бронирование» в CartPanel
            (актуально только для hall с привязанным столом)
    """

    order_submitted = Signal(int)
    cancelled = Signal()
    requested_logout = Signal()
    reservation_requested = Signal(int)

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._cashier_name: str = ""
        self._shift_no: int = 0
        self._build()

    # -------- public API (forwarded to MenuPanel) --------

    def set_cashier(self, name: str, shift_no: int = 0) -> None:
        self._cashier_name = name
        self._shift_no = shift_no
        # MenuPanel сам кассира не показывает (компактный topbar) — нужно
        # хранилище для совместимости с прежним API.

    def configure_create(
        self,
        order_type: str,
        table_id: int | None = None,
        customer_name: str = "",
        customer_phone: str = "",
        customer_address: str = "",
    ) -> None:
        self.panel.configure_create(
            order_type,
            table_id=table_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_address=customer_address,
        )

    def configure_add_items(self, order_id: int) -> None:
        self.panel.configure_add_items(order_id)

    def reload(self) -> None:
        self.panel.reload()

    # -------- proxy для совместимости с существующими тестами --------
    # Старые тесты обращались к приватным полям/методам напрямую — после
    # рефакторинга MenuScreen→MenuPanel прокидываем основные атрибуты.

    def __getattr__(self, name: str):
        # __getattr__ зовётся только если обычный lookup не нашёл атрибут.
        # Используем self.__dict__["panel"] чтобы избежать рекурсии.
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        # Для совместимости со старыми тестами: запись атрибутов, которые
        # реально живут на MenuPanel (_categories, _items_by_cat, и т.п.),
        # форвардится в panel. Свои атрибуты MenuScreen — на себя.
        panel = self.__dict__.get("panel")
        if (
            panel is not None
            and name not in ("panel", "sidebar", "state",
                             "_cashier_name", "_shift_no")
            and hasattr(panel, name)
        ):
            setattr(panel, name, value)
            return
        super().__setattr__(name, value)

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"MenuScreen {{ background-color: {COLORS['bg_light']}; }}"
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # «menu» (utensils) убран из sidebar — на экране меню активен tables.
        self.sidebar = Sidebar(active="tables")
        self.sidebar.nav_clicked.connect(self._on_nav)
        root.addWidget(self.sidebar)

        # Центр: компактный header с полем «Поиск блюда…» + MenuPanel.
        # MenuPanel сам topbar не строит (его удалили), поэтому host
        # (этот MenuScreen) даёт ей поле поиска поверх. Back-навигация —
        # inline-чип «← Все категории» внутри grid'а MenuPanel.
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        header = QFrame()
        header.setObjectName("menuScreenHeader")
        header.setFixedHeight(44)
        header.setStyleSheet(
            f"#menuScreenHeader {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        hh = QHBoxLayout(header)
        hh.setContentsMargins(16, 0, 16, 0)
        hh.addStretch(1)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Поиск блюда…")
        self._search_input.setFixedHeight(32)
        self._search_input.setMinimumWidth(260)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        hh.addWidget(self._search_input)
        cv.addWidget(header)

        self.panel = MenuPanel(self.state)
        self.panel.order_submitted.connect(self.order_submitted.emit)
        self.panel.cancelled.connect(self.cancelled.emit)
        self.panel.reservation_requested.connect(self.reservation_requested.emit)
        # Связываем поиск header'а с панелью.
        self._search_input.textChanged.connect(self.panel.set_search_query)
        # Когда panel сбрасывает search (back-чип), синхронизируем input.
        self.panel.search_query_cleared.connect(self._on_search_cleared)
        cv.addWidget(self.panel, 1)

        root.addWidget(center, 1)
        # CartPanel из MenuPanel теперь рендерится снаружи (host-owned),
        # чтобы шла на всю высоту экрана. Добавляем рядом с center на root.
        root.addWidget(self.panel.cart)

    # -------- handlers --------

    def _on_search_cleared(self) -> None:
        """Panel сбросил search query (back) — синхронизируем QLineEdit."""
        self._search_input.blockSignals(True)
        self._search_input.clear()
        self._search_input.blockSignals(False)

    def _on_nav(self, name: str) -> None:
        # Любой клик по sidebar — спросить confirm если корзина непуста.
        if self.panel.is_dirty() and not self.panel.confirm_discard():
            return
        if name == "logout":
            self.requested_logout.emit()
            return
        self.cancelled.emit()
