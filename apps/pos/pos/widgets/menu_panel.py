"""MenuPanel — переиспользуемый виджет «work area + cart».

Извлечён из MenuScreen, чтобы можно было встраивать меню (категории/блюда +
корзина) внутрь TablesScreen без переключения экрана. MenuScreen теперь
становится тонкой обёрткой Sidebar + MenuPanel.

Layout: [center (компактный topbar: back / breadcrumb / поиск блюд) +
work-grid] | CartPanel (360px справа).

Сигналы наружу:
    order_submitted(order_id: int) — успешный POST /orders/ или /add_items/
    cancelled() — пользователь нажал «Отмена» или «Назад» с пустой корзиной
    reservation_requested(table_id: int) — кнопка «Бронирование» в CartPanel
"""
from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, SPACING
from pos.state import State
from pos.widgets.cart_panel import CartPanel
from pos.widgets.category_card import CategoryCard
from pos.widgets.dish_card import DishCard


class _SubmitWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self,
        client: ApiClient,
        method: str,
        path: str,
        body: dict,
        idem_key: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.method = method
        self.path = path
        self.body = body
        self.idem_key = idem_key

    def run(self) -> None:
        try:
            data = self.client.request(
                self.method,
                self.path,
                json=self.body,
                extra_headers={"Idempotency-Key": self.idem_key},
            )
            self.success.emit(data if isinstance(data, dict) else {"data": data})
        except ApiError as e:
            self.error.emit(e)


class MenuPanel(QWidget):
    """Переиспользуемая панель «категории/блюда + корзина»."""

    order_submitted = Signal(int)
    cancelled = Signal()
    reservation_requested = Signal(int)
    # Эмитится когда panel программно сбрасывает search (back из dishes/search
    # обратно в categories). Host (TablesScreen / MenuScreen) подписывается и
    # очищает свой QLineEdit, чтобы не было desync между UI и состоянием.
    search_query_cleared = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._mode: str = "create"
        self._order_type: str = "hall"
        self._table_id: int | None = None
        self._order_id: int | None = None
        self._customer_name: str = ""
        self._customer_phone: str = ""
        self._customer_address: str = ""

        self._categories: list[dict] = []
        self._items_by_cat: dict[int, list[dict]] = {}
        self._selected_cat_id: int | None = None
        self._search_query: str = ""

        self._idem_key: str = str(uuid.uuid4())
        self._thread: QThread | None = None
        self._worker: _SubmitWorker | None = None

        self._build()

    # -------- public API --------

    def configure_create(
        self,
        order_type: str,
        table_id: int | None = None,
        customer_name: str = "",
        customer_phone: str = "",
        customer_address: str = "",
    ) -> None:
        self._mode = "create"
        self._order_type = order_type
        self._table_id = table_id
        self._order_id = None
        self._customer_name = customer_name
        self._customer_phone = customer_phone
        self._customer_address = customer_address
        self._idem_key = str(uuid.uuid4())
        self._cart.clear()

        if order_type == "hall":
            tname = self._lookup_table_name(table_id)
            self._cart.set_title(f"Новый заказ • {tname}")
        elif order_type == "takeaway":
            self._cart.set_title("Новый: С собой")
        else:
            self._cart.set_title("Новый: Доставка")
        self._cart.set_submit_label("Отправить →")
        self._cart.set_reservation_enabled(
            order_type == "hall" and table_id is not None,
        )

    def configure_add_items(self, order_id: int) -> None:
        self._mode = "add_items"
        self._order_id = order_id
        self._idem_key = str(uuid.uuid4())
        self._cart.clear()
        self._cart.set_title(f"Дозаказ к #{order_id}")
        self._cart.set_submit_label("+ Добавить")
        self._cart.set_reservation_enabled(False)

    def reload(self) -> None:
        try:
            self._categories = self.state.client.get("/menu/categories/") or []
            items = self.state.client.get("/menu/items/") or []
        except ApiError:
            self._categories = []
            items = []

        self._items_by_cat.clear()
        for it in items:
            self._items_by_cat.setdefault(int(it["category"]), []).append(it)

        self._selected_cat_id = None
        self._search_query = ""
        self._render_categories()

    def is_dirty(self) -> bool:
        """Корзина непуста — главный экран должен спросить подтверждение."""
        return not self._cart.is_empty()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"MenuPanel {{ background-color: {COLORS['bg_light']}; }}"
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        # Свой topbar (back/title/search) удалён — host (TablesScreen / MenuScreen)
        # отвечает за бар с поиском. Back в dishes-view — inline-чип в grid'е.
        cv.addWidget(self._build_work_area(), 1)
        root.addWidget(center, 1)

        # CartPanel создаётся, но **не добавляется в этот layout**.
        # Host (TablesScreen / MenuScreen) забирает виджет через `self.cart`
        # и кладёт куда нужно (например, в QStackedWidget справа на root
        # уровне TablesScreen, чтобы правая панель шла на всю высоту).
        self._cart = CartPanel(title="Корзина", submit_label="Отправить →")
        self._cart.submit_requested.connect(self._on_submit)
        self._cart.cancelled.connect(self._on_cancel)
        self._cart.note_edit_requested.connect(self._on_note_edit_requested)
        self._cart.reservation_requested.connect(self._on_reservation_requested)

    @property
    def cart(self) -> CartPanel:
        """Внешний доступ к CartPanel'у для host'а (host сам решает где
        отрендерить корзину — справа full-height, или в собственном layout)."""
        return self._cart

    def _build_back_chip(self) -> QPushButton:
        """Inline-чип «← Все категории» — занимает первую ячейку grid'а
        в dishes/search views. Не topbar, просто навигационная ссылка."""
        btn = QPushButton("  ← Все категории")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFlat(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setMinimumHeight(48)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none; padding: 8px 12px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"  text-align: left;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['accent_orange']}; }}"
        )
        btn.clicked.connect(self.go_back)
        return btn

    def _build_work_area(self) -> QWidget:
        self._work_holder = QWidget()
        self._work_layout = QGridLayout(self._work_holder)
        self._work_layout.setContentsMargins(16, 16, 16, 16)
        self._work_layout.setHorizontalSpacing(SPACING["sm"] + 2)
        self._work_layout.setVerticalSpacing(SPACING["sm"] + 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._work_holder)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_light']}; border: none; }}"
            f" QWidget {{ background: {COLORS['bg_light']}; }}"
        )
        self._scroll = scroll
        return scroll

    # -------- rendering --------

    def _clear_grid(self) -> None:
        while self._work_layout.count():
            child = self._work_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        for c in range(self._work_layout.columnCount()):
            self._work_layout.setColumnStretch(c, 0)
        for r in range(self._work_layout.rowCount()):
            self._work_layout.setRowStretch(r, 0)

    def _compute_cols(self, min_w: int, *, max_cols: int = 8) -> int:
        viewport = self._scroll.viewport().width() if hasattr(self, "_scroll") else self.width()
        usable = max(0, viewport - 32)
        gap = SPACING["sm"] + 2
        cell = min_w + gap
        cols = (usable + gap) // cell if cell > 0 else 2
        return max(2, min(max_cols, int(cols) or 2))

    def _render_categories(self) -> None:
        self._clear_grid()
        cols = self._compute_cols(CategoryCard.MIN_WIDTH, max_cols=6)
        for i, cat in enumerate(self._categories):
            row, col = divmod(i, cols)
            count = len(self._items_by_cat.get(int(cat["id"]), []))
            card = CategoryCard(cat, item_count=count)
            card.clicked.connect(self._on_category_clicked)
            self._work_layout.addWidget(card, row, col)
        for c in range(cols):
            self._work_layout.setColumnStretch(c, 1)
        if self._categories:
            rows = math.ceil(len(self._categories) / cols)
            self._work_layout.setRowStretch(rows, 1)

    def _place_with_back_chip(self, widgets: list, cols: int) -> int:
        """Кладёт «← Все категории» в (0,0) и далее widgets начиная с (0,1).
        Возвращает количество занятых строк."""
        self._work_layout.addWidget(self._build_back_chip(), 0, 0)
        offset = 1  # первая ячейка занята чипом
        for i, w in enumerate(widgets):
            slot = i + offset
            row, col = divmod(slot, cols)
            self._work_layout.addWidget(w, row, col)
        total_slots = len(widgets) + offset
        return math.ceil(total_slots / cols)

    def _render_dishes(self, category_id: int) -> None:
        self._clear_grid()
        items = self._items_by_cat.get(category_id, [])
        cols = self._compute_cols(DishCard.MIN_WIDTH, max_cols=8)
        cards = []
        for item in items:
            card = DishCard(item)
            card.clicked.connect(lambda mid, it=item: self._on_dish_clicked(it))
            cards.append(card)
        rows = self._place_with_back_chip(cards, cols)
        for c in range(cols):
            self._work_layout.setColumnStretch(c, 1)
        if cards:
            self._work_layout.setRowStretch(rows, 1)

    def _render_search_results(self) -> None:
        self._clear_grid()
        q = self._search_query.lower()
        matches: list[dict] = []
        for items in self._items_by_cat.values():
            for it in items:
                name = (it.get("name") or "").lower()
                if q in name:
                    matches.append(it)

        if not matches:
            self._work_layout.addWidget(self._build_back_chip(), 0, 0)
            empty = QLabel("Ничего не найдено")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 14pt;"
                f" font-style: italic; padding: 60px 0;"
                f" background: transparent; border: none;"
            )
            self._work_layout.addWidget(empty, 1, 0, 1, -1)
            self._work_layout.setColumnStretch(0, 1)
            self._work_layout.setRowStretch(2, 1)
            self._empty_search_lbl = empty
            return

        cols = self._compute_cols(DishCard.MIN_WIDTH, max_cols=8)
        cards = []
        for item in matches:
            card = DishCard(item)
            card.clicked.connect(lambda mid, it=item: self._on_dish_clicked(it))
            cards.append(card)
        rows = self._place_with_back_chip(cards, cols)
        for c in range(cols):
            self._work_layout.setColumnStretch(c, 1)
        self._work_layout.setRowStretch(rows, 1)

    def set_search_query(self, text: str) -> None:
        """Публичный API: host (TablesScreen/MenuScreen topbar) подаёт сюда
        текст поискового поля. Эмитированный textChanged → set_search_query."""
        self._search_query = (text or "").strip()
        if self._search_query:
            self._render_search_results()
        else:
            if self._selected_cat_id is None:
                self._render_categories()
            else:
                self._render_dishes(self._selected_cat_id)

    # Сохранён для обратной совместимости со старыми тестами/кодом.
    def _on_search_text(self, text: str) -> None:
        return self.set_search_query(text)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._search_query:
            self._render_search_results()
        elif self._selected_cat_id is None:
            if self._categories:
                self._render_categories()
        else:
            self._render_dishes(self._selected_cat_id)

    # -------- handlers --------

    def _on_category_clicked(self, cat_id: int) -> None:
        self._selected_cat_id = cat_id
        self._render_dishes(cat_id)

    def go_back(self) -> None:
        """Публичный API: back-навигация по уровням внутри MenuPanel.
        dishes/search → categories. Эмитит `search_query_cleared` чтобы
        host (TablesScreen/MenuScreen) синхронизировал свой QLineEdit."""
        if self._search_query:
            self._search_query = ""
            self.search_query_cleared.emit()
            if self._selected_cat_id is not None:
                self._render_dishes(self._selected_cat_id)
            else:
                self._render_categories()
            return
        self._selected_cat_id = None
        self._render_categories()

    # Alias для старых тестов.
    def _on_back(self) -> None:
        return self.go_back()

    def _confirm_discard(self) -> bool:
        if self._cart.is_empty():
            return True
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Корзина не пуста")
        confirm.setText("Покинуть меню? Несохранённые позиции пропадут.")
        confirm.setIcon(QMessageBox.Question)
        yes = confirm.addButton("Покинуть", QMessageBox.YesRole)
        confirm.addButton("Остаться", QMessageBox.NoRole)
        confirm.exec()
        return confirm.clickedButton() == yes

    def confirm_discard(self) -> bool:
        """Публичная версия для wrapper-экранов (например, sidebar-nav)."""
        return self._confirm_discard()

    def _on_dish_clicked(self, item: dict) -> None:
        groups = item.get("modifier_groups") or []
        if not groups:
            self._cart.add_item(item)
            return
        from pos.screens.modifier_picker_dialog import ModifierPickerDialog

        dlg = ModifierPickerDialog(menu_item=item, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._cart.add_item(
                item,
                modifier_ids=dlg.chosen_modifier_ids,
                modifiers=dlg.chosen_modifiers_snapshot,
            )

    def _on_note_edit_requested(self, menu_item_id: int, current_note: str) -> None:
        from pos.screens.note_picker_dialog import NotePickerDialog

        item_name = "Блюдо"
        for items_list in self._items_by_cat.values():
            for it in items_list:
                if int(it["id"]) == int(menu_item_id):
                    item_name = it.get("name", "Блюдо")
                    break

        dlg = NotePickerDialog(
            client=self.state.client,
            item_name=item_name,
            current_note=current_note,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            new_note = dlg.chosen_note
            self._cart.set_item_note(menu_item_id, current_note, new_note)

    def _on_cancel(self) -> None:
        if self._cart.is_empty() or self._confirm_discard():
            self.cancelled.emit()

    def _on_reservation_requested(self) -> None:
        if self._table_id is None:
            return
        self.reservation_requested.emit(int(self._table_id))

    def _on_submit(self) -> None:
        if self._thread is not None:
            return
        items = self._cart.get_items()
        if not items:
            return

        if self._mode == "create":
            method = "POST"
            path = "/orders/"
            body: dict = {
                "order_type": self._order_type,
                "items": items,
            }
            if self._order_type == "hall" and self._table_id is not None:
                body["table_id"] = self._table_id
                body["guests_count"] = 1
            if self._order_type in {"takeaway", "delivery"}:
                body["customer_name"] = self._customer_name
                body["customer_phone"] = self._customer_phone
                if self._order_type == "delivery":
                    body["customer_address"] = self._customer_address
        else:  # add_items
            method = "POST"
            path = f"/orders/{self._order_id}/add_items/"
            body = {"items": items}

        thread = QThread(self)
        worker = _SubmitWorker(
            self.state.client, method, path, body, self._idem_key
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_submit_success)
        worker.error.connect(self._on_submit_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_submit_success(self, data) -> None:
        self._thread = None
        self._worker = None
        order = data if isinstance(data, dict) and "id" in data else (
            data.get("data") if isinstance(data, dict) else {}
        )
        order_id = int(order.get("id") or 0)
        self.state.refresh()
        self.order_submitted.emit(order_id)

    def _on_submit_error(self, exc: ApiError) -> None:
        self._thread = None
        self._worker = None
        QMessageBox.warning(self, "Ошибка", f"{exc.message}\n[{exc.code}]")

    def _lookup_table_name(self, table_id: int | None) -> str:
        if table_id is None:
            return ""
        for t in self.state.tables:
            if int(t["id"]) == int(table_id):
                return t.get("name") or f"Стол {t.get('number')}"
        return f"Стол {table_id}"
