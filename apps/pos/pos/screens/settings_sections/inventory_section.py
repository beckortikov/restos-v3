"""Settings → «Склад» — ингредиенты + полуфабрикаты.

Phase 7D-1: ингредиенты (CRUD + приёмка + списание + инвент + история).
Phase 7D-2: полуфабрикаты (CRUD + рецепт + варка партии + история) + tabs.

InventorySection — QTabWidget с двумя pane:
- IngredientsPane (sec._ingredients_pane)
- SemiPane (sec._semi_pane)

Для backwards-compat с тестами: `sec._table`, `sec._on_loaded`, `sec._items`,
`sec._items_pane`, etc. делегируют к IngredientsPane.
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QObject, Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.screens.settings_sections.inventory_widgets import (
    KpiStrip,
    SearchBar,
    StatusBadge,
)
from pos.resources.format import fmt_money, fmt_qty


UNIT_LABEL = {
    "kg": "кг", "g": "г", "l": "л", "ml": "мл",
    "piece": "шт", "pack": "уп", "bottle": "бут",
}


# ─────────────────────────────────────────────────────────────────────────
# Workers (общие)
# ─────────────────────────────────────────────────────────────────────────


class _LoadIngredientsWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient, kind: str = "food") -> None:
        super().__init__()
        self.client = client
        self.kind = kind

    def run(self) -> None:
        try:
            data = self.client.get(f"/inventory/ingredients/?kind={self.kind}")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _LoadSummaryWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, kind: str = "food") -> None:
        super().__init__()
        self.client = client
        self.kind = kind

    def run(self) -> None:
        try:
            data = self.client.get(f"/inventory/ingredients/summary/?kind={self.kind}")
            summary = (data or {}).get("data") if isinstance(data, dict) else {}
            self.success.emit(summary or {})
        except ApiError as e:
            self.error.emit(e)


class _LoadSemiWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/inventory/semi/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _DeleteWorker(QObject):
    success = Signal(int)
    error = Signal(int, object)

    def __init__(self, client: ApiClient, path: str, obj_id: int) -> None:
        super().__init__()
        self.client = client
        self.path = path
        self.obj_id = obj_id

    def run(self) -> None:
        try:
            self.client.request(
                "DELETE", f"{self.path}{self.obj_id}/", idempotent=True,
            )
            self.success.emit(self.obj_id)
        except ApiError as e:
            self.error.emit(self.obj_id, e)


# ─────────────────────────────────────────────────────────────────────────
# Стили общие
# ─────────────────────────────────────────────────────────────────────────


def _top_btn(label: str, *, primary: bool) -> QPushButton:
    b = QPushButton(label)
    b.setFixedHeight(40)
    b.setMinimumWidth(140)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
    else:
        b.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
    return b


def _table_qss() -> str:
    return (
        f"QTableWidget {{"
        f"  background-color: {COLORS['bg_white']};"
        f"  alternate-background-color: #FAFBFC;"
        f"  border: 1px solid {COLORS['border_light']};"
        f"  border-radius: {RADIUS['md']}px;"
        f"  font-size: 11pt;"
        f"  outline: none;"
        f"}}"
        f"QTableWidget::item {{"
        f"  border-bottom: 1px solid {COLORS['border_light']};"
        f"  padding: 12px 6px;"
        f"  color: {COLORS['text_primary']};"
        f"}}"
        f"QHeaderView::section {{"
        f"  background: {COLORS['bg_gray']};"
        f"  color: {COLORS['text_secondary']};"
        f"  border: none;"
        f"  border-bottom: 1px solid {COLORS['border_light']};"
        f"  padding: 8px 6px;"
        f"  font-weight: 700; font-size: 10pt;"
        f"}}"
    )


def _mini_btn_qss(*, danger: bool = False) -> str:
    if danger:
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  font-size: 14pt; font-weight: 700;"
            f"  border: 1px solid transparent;"
            f"  border-radius: 4px;"
            f"  padding: 0 8px;"
            f"}}"
            f"QPushButton:hover {{ background: #FEF2F2; }}"
        )
    return (
        f"QPushButton {{"
        f"  background: {COLORS['bg_white']};"
        f"  color: {COLORS['text_primary']};"
        f"  border: 1px solid {COLORS['border_light']};"
        f"  border-radius: 4px;"
        f"  padding: 0 10px; font-size: 10pt; font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
    )


# ─────────────────────────────────────────────────────────────────────────
# IngredientsPane — ингредиенты (Phase 7D-1)
# ─────────────────────────────────────────────────────────────────────────


class IngredientsPane(QWidget):
    """Phase 8D — параметризован по kind ("food" = Продукты, "household" = Хозтовары).

    Различия:
      - заголовок и подпись add-кнопки
      - 5-я KPI «Стоимость остатков» для food, «Запас на складе» для household
      - GET /inventory/ingredients/?kind=... → фильтр на сервере
    """

    def __init__(
        self,
        client: ApiClient,
        kind: str = "food",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._kind = kind
        self._items: list[dict] = []
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"IngredientsPane {{ background: {COLORS['bg_light']}; }}"
        )
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        # Phase 8D — content padding 24 по дизайну (frame Hj7LK в pos_cashier.pen),
        # gap 16 между секциями (header → KPI → search → table).
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        head = QHBoxLayout()
        is_food = self._kind == "food"
        title_text = "Продукты" if is_food else "Хозтовары"
        add_text = "+ Ингредиент" if is_food else "+ Хозтовар"
        # Title + subtitle (для Хозтоваров) — по дизайну frame lqyIm/iLR1T8
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        tcol.setContentsMargins(0, 0, 0, 0)
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 22px; font-weight: 700;"
        )
        tcol.addWidget(title)
        if not is_food:
            subtitle = QLabel(
                "Непродуктовые позиции: моющие, посуда, бумага, упаковка, спецодежда."
            )
            subtitle.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px;"
            )
            tcol.addWidget(subtitle)
        head.addLayout(tcol)
        head.addStretch(1)

        # Phase 8D — порядок кнопок по дизайну: Шаблон XLSX → Импорт XLSX → +Продукт (primary)
        tpl_btn = _top_btn("⬇ Шаблон XLSX", primary=False)
        tpl_btn.clicked.connect(self._download_template)
        head.addWidget(tpl_btn)
        imp_btn = _top_btn("⬆ Импорт XLSX", primary=False)
        imp_btn.clicked.connect(self._import_xlsx)
        head.addWidget(imp_btn)
        add_btn = _top_btn(add_text, primary=True)
        add_btn.clicked.connect(self._on_add)
        head.addWidget(add_btn)

        v.addLayout(head)

        # Phase 8D — KPI strip (5 для Продуктов с "Стоимость остатков",
        # 4 для Хозтоваров с "Запас на складе")
        kpi_specs = [
            ("total",   "Всего",         COLORS["primary_blue"]),
            ("low",     "Заканчивается", COLORS["warning_yellow"]),
            ("out",     "Закончилось",   COLORS["danger_red"]),
            ("off",     "Отключено",     COLORS["text_secondary"]),
            ("value",   "Стоимость остатков" if is_food else "Запас на складе",
             COLORS["success_green"]),
        ]
        self._kpis = KpiStrip(kpi_specs)
        v.addWidget(self._kpis)

        # Phase 8D — поиск + chip-фильтры
        self._search = SearchBar(placeholder="Поиск по названию…")
        self._search.text_changed.connect(self._on_filter_changed)
        self._filter_state = "all"
        self._chip_all = self._search.add_chip("Все", self._on_chip)
        self._chip_low = self._search.add_chip("Заканчивается", self._on_chip)
        self._chip_out = self._search.add_chip("Нет на складе", self._on_chip)
        self._chip_all.setChecked(True)
        v.addWidget(self._search)

        # Phase 8D — 7 колонок (Тип убран, секции разделены на Продукты/Хозтовары)
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Название", "Ед.", "Остаток", "Себест.", "Сорт.",
            "Статус", "Действия",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        self._table.setColumnWidth(0, 450) # Название (stretches)
        self._table.setColumnWidth(1, 60)  # Ед.
        self._table.setColumnWidth(2, 120) # Остаток
        self._table.setColumnWidth(3, 100) # Себест.
        self._table.setColumnWidth(4, 60)  # Сорт.
        self._table.setColumnWidth(5, 130) # Статус
        self._table.setColumnWidth(6, 110) # Действия
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self._table, 1)

    def _on_chip(self, clicked) -> None:
        # Радиокнопочное поведение
        for chip, key in [
            (self._chip_all, "all"),
            (self._chip_low, "low"),
            (self._chip_out, "out"),
        ]:
            if chip is clicked:
                self._filter_state = key
                chip.setChecked(True)
            else:
                chip.setChecked(False)
        self._render_table()

    def _on_filter_changed(self, _text: str) -> None:
        self._render_table()

    def _filtered_items(self) -> list[dict]:
        text = (self._search.text or "").strip().lower()
        result = []
        for ing in self._items:
            if text and text not in (ing.get("name") or "").lower():
                continue
            qty = float(ing.get("current_qty") or 0)
            low = bool(ing.get("is_low_stock"))
            is_out = qty <= 0
            if self._filter_state == "low" and not (low or is_out):
                continue
            if self._filter_state == "out" and not is_out:
                continue
            result.append(ing)
        return result

    def _update_kpis(self) -> None:
        total = len(self._items)
        low = sum(1 for i in self._items if i.get("is_low_stock"))
        out = sum(1 for i in self._items if float(i.get("current_qty") or 0) <= 0)
        off = sum(1 for i in self._items if not i.get("is_active", True))
        self._kpis.update_kpis({"total": total, "low": low, "out": out, "off": off})

    # -------- public --------

    def reload(self) -> None:
        # Список
        thread = QThread(self)
        worker = _LoadIngredientsWorker(self._client, kind=self._kind)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_loaded)
        worker.error.connect(self._on_load_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

        # KPI summary (агрегат с сервера — точная стоимость остатков)
        sthread = QThread(self)
        sworker = _LoadSummaryWorker(self._client, kind=self._kind)
        sworker.moveToThread(sthread)
        sthread.started.connect(sworker.run)
        sworker.success.connect(self._on_summary)
        sworker.error.connect(lambda _e: None)
        sworker.success.connect(sthread.quit)
        sworker.error.connect(sthread.quit)
        sthread.finished.connect(sthread.deleteLater)
        sthread._worker = sworker  # noqa: SLF001
        self._threads.append(sthread)
        sthread.start()

    def _on_summary(self, summary: dict) -> None:
        """Обновить KPI из агрегатного endpoint'а (точная стоимость остатков)."""
        value = summary.get("total_value", "0")
        try:
            from decimal import Decimal
            v = Decimal(str(value))
            if v >= 1000:
                value_str = f"{v:,.0f} TJS".replace(",", " ")
            else:
                value_str = f"{v:.2f} TJS"
        except Exception:
            value_str = f"{value} TJS"
        self._kpis.update_kpis({
            "total":  summary.get("total", 0),
            "low":    summary.get("low_stock", 0),
            "out":    summary.get("out_of_stock", 0),
            "off":    summary.get("inactive", 0),
            "value":  value_str,
        })

    # -------- rendering --------

    def _on_loaded(self, items: list) -> None:
        self._items = sorted(
            items, key=lambda i: (int(i.get("sort_order", 0)), i.get("name", "")),
        )
        self._render_table()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить ингредиенты:\n[{exc.code}] {exc.message}",
        )

    def _render_table(self) -> None:
        from PySide6.QtGui import QBrush, QColor

        self._update_kpis()
        items = self._filtered_items()
        self._table.setRowCount(len(items))
        for i, ing in enumerate(items):
            # 0: Название (bold)
            name_item = QTableWidgetItem(ing.get("name", ""))
            f = name_item.font()
            f.setBold(True)
            name_item.setFont(f)
            self._table.setItem(i, 0, name_item)
            # 1: Ед.
            unit = ing.get("unit") or ""
            self._table.setItem(
                i, 1, QTableWidgetItem(UNIT_LABEL.get(unit, unit)),
            )
            # 2: Остаток — адаптивный формат до 2 знаков, без trailing нулей
            qty_raw = ing.get("current_qty", "0")
            qty_val = float(qty_raw or 0)
            qty_item = QTableWidgetItem(fmt_qty(qty_val, UNIT_LABEL.get(unit, unit)))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if qty_val <= 0:
                qty_item.setForeground(QBrush(QColor(COLORS["danger_red"])))
                f = qty_item.font()
                f.setBold(True)
                qty_item.setFont(f)
            elif ing.get("is_low_stock"):
                qty_item.setForeground(QBrush(QColor(COLORS["warning_yellow"])))
            self._table.setItem(i, 2, qty_item)
            # 3: Себест. — деньги, всегда 2dp
            cost_item = QTableWidgetItem(fmt_money(ing.get("avg_cost_per_unit")))
            cost_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 3, cost_item)
            # 4: Сорт.
            self._table.setItem(
                i, 4, QTableWidgetItem(str(ing.get("sort_order", 0))),
            )
            # 5: Статус (pill-badge)
            if not ing.get("is_active", True):
                key = "off"
            elif qty_val <= 0:
                key = "out"
            elif ing.get("is_low_stock"):
                key = "low"
            else:
                key = "ok"
            badge_wrap = QWidget()
            badge_wrap.setStyleSheet("background: transparent;")
            bl = QHBoxLayout(badge_wrap)
            bl.setContentsMargins(4, 4, 4, 4)
            bl.addWidget(StatusBadge(key))
            bl.addStretch(1)
            self._table.setCellWidget(i, 5, badge_wrap)
            # 6: Действия
            self._table.setCellWidget(i, 6, self._build_actions(ing))

    def _build_actions(self, ing: dict) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(4)

        # Phase 8D — в строке остаётся только «Изм.» (Приёмка/Списание — через
        # документы Накладные/Списания; История и Удалить — внутри edit-диалога).
        b = QPushButton("Изм.")
        b.setFixedHeight(30)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(_mini_btn_qss())
        from pos.resources.icons import qicon
        b.setIcon(qicon("edit-2", COLORS["text_primary"], 14))
        b.setIconSize(QSize(14, 14))
        b.clicked.connect(lambda _c=False, i=ing: self._on_edit(i))
        h.addWidget(b)
        h.addStretch(1)
        return wrap

    # -------- handlers --------

    def _on_add(self) -> None:
        from pos.screens.settings_sections.ingredient_edit_dialog import (
            IngredientEditDialog,
        )

        dlg = IngredientEditDialog(self._client, ingredient=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _download_template(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить шаблон", "ingredients_template.xlsx", "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            content = self._client.get_raw("/inventory/ingredients/template/")
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        with open(path, "wb") as f:
            f.write(content)
        QMessageBox.information(self, "Готово", f"Шаблон сохранён: {path}")

    def _import_xlsx(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите XLSX", "", "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                content = f.read()
            data = self._client.post_file(
                "/inventory/ingredients/import/", field="file",
                filename=path.split("/")[-1], content=content,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка импорта", f"[{e.code}] {e.message}")
            return
        d = data if isinstance(data, dict) else {}
        QMessageBox.information(
            self, "Импорт",
            f"Создано: {d.get('created', 0)}\n"
            f"Обновлено: {d.get('updated', 0)}\n"
            f"Ошибок: {len(d.get('errors') or [])}",
        )
        self.reload()

    def _on_edit(self, ing: dict) -> None:
        from pos.screens.settings_sections.ingredient_edit_dialog import (
            IngredientEditDialog,
        )

        dlg = IngredientEditDialog(self._client, ingredient=ing, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete(self, ing: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить ингредиент?",
            f"«{ing.get('name', '?')}» будет удалён.\n"
            "Если есть история движений — soft-delete (станет неактивен).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_delete(int(ing["id"]))

    def _spawn_delete(self, obj_id: int) -> None:
        thread = QThread(self)
        worker = _DeleteWorker(self._client, "/inventory/ingredients/", obj_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _i: self.reload())
        worker.error.connect(
            lambda _i, e: QMessageBox.warning(
                self, "Ошибка удаления", f"[{e.code}] {e.message}",
            )
        )
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_purchase(self, ing: dict) -> None:
        from pos.screens.settings_sections.stock_action_dialogs import PurchaseDialog
        dlg = PurchaseDialog(self._client, ingredient=ing, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_waste(self, ing: dict) -> None:
        from pos.screens.settings_sections.stock_action_dialogs import WasteDialog
        dlg = WasteDialog(self._client, ingredient=ing, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_inventory(self, ing: dict) -> None:
        from pos.screens.settings_sections.stock_action_dialogs import (
            InventoryCorrectDialog,
        )
        dlg = InventoryCorrectDialog(self._client, ingredient=ing, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_history(self, ing: dict) -> None:
        from pos.screens.settings_sections.movements_history_dialog import (
            MovementsHistoryDialog,
        )
        dlg = MovementsHistoryDialog(self._client, ingredient=ing, parent=self)
        dlg.exec()


# ─────────────────────────────────────────────────────────────────────────
# SemiPane — полуфабрикаты (Phase 7D-2)
# ─────────────────────────────────────────────────────────────────────────


class SemiPane(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"SemiPane {{ background: {COLORS['bg_light']}; }}"
        )
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        head = QHBoxLayout()
        # Title + subtitle по дизайну frame x1QbGF
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        tcol.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Полуфабрикаты")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 22px; font-weight: 700;"
        )
        tcol.addWidget(title)
        subtitle = QLabel(
            "Заготовки из ингредиентов, расходуются на блюда по техкарте"
        )
        subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;"
        )
        tcol.addWidget(subtitle)
        head.addLayout(tcol)
        head.addStretch(1)
        add_btn = _top_btn("+ Полуфабрикат", primary=True)
        add_btn.clicked.connect(self._on_add)
        head.addWidget(add_btn)
        v.addLayout(head)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Название", "Ед.", "Yield %", "Остаток", "Себест.",
            "Сорт.", "Статус", "Действия",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        self._table.setColumnWidth(0, 350) # Название (stretches)
        self._table.setColumnWidth(1, 60)  # Ед.
        self._table.setColumnWidth(2, 80)  # Yield %
        self._table.setColumnWidth(3, 120) # Остаток
        self._table.setColumnWidth(4, 100) # Себест.
        self._table.setColumnWidth(5, 60)  # Сорт.
        self._table.setColumnWidth(6, 130) # Статус
        self._table.setColumnWidth(7, 180) # Действия
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self._table, 1)

    # -------- public --------

    def reload(self) -> None:
        thread = QThread(self)
        worker = _LoadSemiWorker(self._client)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_loaded)
        worker.error.connect(self._on_load_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_loaded(self, items: list) -> None:
        self._items = sorted(
            items, key=lambda i: (int(i.get("sort_order", 0)), i.get("name", "")),
        )
        self._render_table()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить полуфабрикаты:\n[{exc.code}] {exc.message}",
        )

    def _render_table(self) -> None:
        from PySide6.QtGui import QBrush, QColor

        self._table.setRowCount(len(self._items))
        for i, semi in enumerate(self._items):
            self._table.setItem(i, 0, QTableWidgetItem(semi.get("name", "")))
            unit = semi.get("output_unit") or ""
            self._table.setItem(
                i, 1, QTableWidgetItem(UNIT_LABEL.get(unit, unit)),
            )
            # Yield % — без trailing нулей
            self._table.setItem(i, 2, QTableWidgetItem(fmt_qty(semi.get("yield_percent", 100)) + "%"))
            # Остаток — адаптивный формат + единица
            qty_item = QTableWidgetItem(fmt_qty(semi.get("current_qty"), UNIT_LABEL.get(unit, unit)))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if semi.get("is_low_stock"):
                qty_item.setForeground(QBrush(QColor(COLORS["danger_red"])))
                f = qty_item.font()
                f.setBold(True)
                qty_item.setFont(f)
            self._table.setItem(i, 3, qty_item)
            # Себест. — деньги, всегда 2dp
            cost_item = QTableWidgetItem(fmt_money(semi.get("avg_cost_per_unit")))
            cost_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 4, cost_item)
            self._table.setItem(
                i, 5, QTableWidgetItem(str(semi.get("sort_order", 0))),
            )

            qty_val = float(semi.get("current_qty") or 0)
            if not semi.get("is_active", True):
                key = "off"
            elif qty_val <= 0:
                key = "out"
            elif semi.get("is_low_stock"):
                key = "low"
            else:
                key = "ok"
            badge_wrap = QWidget()
            badge_wrap.setStyleSheet("background: transparent;")
            bl = QHBoxLayout(badge_wrap)
            bl.setContentsMargins(4, 4, 4, 4)
            bl.addWidget(StatusBadge(key))
            bl.addStretch(1)
            self._table.setCellWidget(i, 6, badge_wrap)

            self._table.setCellWidget(i, 7, self._build_actions(semi))

    def _build_actions(self, semi: dict) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(4)
        # Phase 8D — в строке только «Произвести» (партия) + «Изм.».
        # Списание/инвентаризация — через документы; удаление — внутри edit-диалога.
        for label, slot in [
            ("Произвести", lambda s=semi: self._on_produce(s)),
            ("Изм.",       lambda s=semi: self._on_edit(s)),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            # «Произвести» — primary; «Изм.» — secondary
            if label == "Произвести":
                from pos.resources.tokens import COLORS as _C, RADIUS as _R
                b.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {_C['accent_orange']};"
                    f"  color: {_C['text_white']};"
                    f"  border: 1px solid {_C['accent_orange']};"
                    f"  border-radius: {_R['sm']}px;"
                    f"  padding: 0 12px; font-size: 11pt; font-weight: 700;"
                    f"}}"
                )
            else:
                b.setStyleSheet(_mini_btn_qss())
                from pos.resources.icons import qicon
                b.setIcon(qicon("edit-2", COLORS["text_primary"], 14))
                b.setIconSize(QSize(14, 14))
            b.clicked.connect(slot)
            h.addWidget(b)
        h.addStretch(1)
        return wrap

    # -------- handlers --------

    def _on_add(self) -> None:
        from pos.screens.settings_sections.semi_edit_dialog import SemiEditDialog
        dlg = SemiEditDialog(self._client, semi=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit(self, semi: dict) -> None:
        from pos.screens.settings_sections.semi_edit_dialog import SemiEditDialog
        # Подтянем full snapshot с recipe_lines
        try:
            full = self._client.get(f"/inventory/semi/{semi['id']}/")
            data = full if isinstance(full, dict) else (full or {}).get("data") or semi
        except ApiError:
            data = semi
        dlg = SemiEditDialog(self._client, semi=data, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete(self, semi: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить полуфабрикат?",
            f"«{semi.get('name', '?')}» будет удалён.\n"
            "Если есть история — soft-delete.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        thread = QThread(self)
        worker = _DeleteWorker(self._client, "/inventory/semi/", int(semi["id"]))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _i: self.reload())
        worker.error.connect(
            lambda _i, e: QMessageBox.warning(
                self, "Ошибка удаления", f"[{e.code}] {e.message}",
            )
        )
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_produce(self, semi: dict) -> None:
        from pos.screens.settings_sections.semi_produce_dialog import (
            SemiProduceDialog,
        )
        dlg = SemiProduceDialog(self._client, semi=semi, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_waste(self, semi: dict) -> None:
        from pos.screens.settings_sections.semi_simple_dialogs import (
            SemiWasteDialog,
        )
        dlg = SemiWasteDialog(self._client, semi=semi, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_inventory(self, semi: dict) -> None:
        from pos.screens.settings_sections.semi_simple_dialogs import (
            SemiInventoryCorrectDialog,
        )
        dlg = SemiInventoryCorrectDialog(self._client, semi=semi, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()


# ─────────────────────────────────────────────────────────────────────────
# AutoStopPane — блюда, попавшие в авто-стоп (Phase 8D)
# ─────────────────────────────────────────────────────────────────────────


class _LoadAutoStopWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/menu/items/auto_stopped/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _OversellWorker(QObject):
    success = Signal(int, dict)
    error = Signal(int, object)

    def __init__(self, client: ApiClient, item_id: int, enabled: bool) -> None:
        super().__init__()
        self.client = client
        self.item_id = item_id
        self.enabled = enabled

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/menu/items/{self.item_id}/allow_oversell/",
                json={"enabled": self.enabled},
            )
            payload = data.get("data") if isinstance(data, dict) and "data" in data else data
            self.success.emit(
                self.item_id, payload if isinstance(payload, dict) else {},
            )
        except ApiError as e:
            self.error.emit(self.item_id, e)


class AutoStopPane(QWidget):
    """Блюда, автоматически снятые со стопа из-за нехватки склада."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"AutoStopPane {{ background: {COLORS['bg_light']}; }}"
        )
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        head = QHBoxLayout()
        title = QLabel("Авто-стоп блюд")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 22px; font-weight: 700;"
        )
        head.addWidget(title)
        subtitle = QLabel("Эти блюда нельзя заказать — нет ингредиентов на складе.")
        subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        head.addWidget(subtitle)
        head.addStretch(1)
        refresh = _top_btn("⟳ Обновить", primary=False)
        refresh.clicked.connect(self.reload)
        head.addWidget(refresh)
        v.addLayout(head)

        self._kpis = KpiStrip([
            ("stopped",  "В авто-стопе", COLORS["danger_red"]),
            ("oversell", "Продают в минус", "#7C3AED"),
        ])
        v.addWidget(self._kpis)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Блюдо", "Цена", "Причина", "Статус", "Действие",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        self._table.setColumnWidth(0, 350) # Блюдо (stretches)
        self._table.setColumnWidth(1, 120) # Цена
        self._table.setColumnWidth(2, 200) # Причина
        self._table.setColumnWidth(3, 130) # Статус
        self._table.setColumnWidth(4, 180) # Действие
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        v.addWidget(self._table, 1)

        self._empty_state = QLabel("✓ Все блюда в наличии — авто-стопа нет.")
        self._empty_state.setAlignment(Qt.AlignCenter)
        self._empty_state.setStyleSheet(
            f"color: {COLORS['success_green']};"
            f" font-size: 13pt; font-weight: 600; padding: 40px;"
        )
        v.addWidget(self._empty_state)
        self._empty_state.hide()

    # -------- public --------

    def reload(self) -> None:
        thread = QThread(self)
        worker = _LoadAutoStopWorker(self._client)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_loaded)
        worker.error.connect(self._on_load_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_loaded(self, items: list) -> None:
        self._items = list(items)
        self._render()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить авто-стоп:\n[{exc.code}] {exc.message}",
        )

    def _render(self) -> None:
        # KPI: stopped — текущие в стопе; oversell — отдельный запрос пропускаем,
        # считаем флаг allow_oversell у возвращённых записей (если их API отдал).
        oversell = sum(1 for i in self._items if i.get("allow_oversell"))
        self._kpis.update_kpis({
            "stopped": len(self._items),
            "oversell": oversell,
        })

        empty = not self._items
        self._table.setVisible(not empty)
        self._empty_state.setVisible(empty)

        self._table.setRowCount(len(self._items))
        for i, mi in enumerate(self._items):
            name = mi.get("name", "?")
            emoji = (mi.get("emoji") or "").strip()
            name_text = f"{emoji} {name}".strip()
            name_item = QTableWidgetItem(name_text)
            f = name_item.font()
            f.setBold(True)
            name_item.setFont(f)
            self._table.setItem(i, 0, name_item)

            price_item = QTableWidgetItem(f"{mi.get('price', '0.00')} TJS")
            price_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(i, 1, price_item)

            reason = mi.get("stop_reason") or "—"
            reason_item = QTableWidgetItem(reason)
            from PySide6.QtGui import QBrush, QColor
            reason_item.setForeground(QBrush(QColor(COLORS["danger_red"])))
            self._table.setItem(i, 2, reason_item)

            badge_wrap = QWidget()
            badge_wrap.setStyleSheet("background: transparent;")
            bl = QHBoxLayout(badge_wrap)
            bl.setContentsMargins(4, 4, 4, 4)
            key = "oversell" if mi.get("allow_oversell") else "stopped"
            bl.addWidget(StatusBadge(key))
            bl.addStretch(1)
            self._table.setCellWidget(i, 3, badge_wrap)

            self._table.setCellWidget(i, 4, self._build_actions(mi))

    def _build_actions(self, mi: dict) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(6)
        is_over = bool(mi.get("allow_oversell"))
        label = "Отключить «в минус»" if is_over else "Продавать в минус"
        b = QPushButton(label)
        b.setFixedHeight(30)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(_mini_btn_qss(danger=False))
        b.clicked.connect(lambda _c=False, m=mi: self._on_oversell(m, not is_over))
        h.addWidget(b)
        h.addStretch(1)
        return wrap

    def _on_oversell(self, mi: dict, enabled: bool) -> None:
        thread = QThread(self)
        worker = _OversellWorker(self._client, int(mi["id"]), enabled)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _id, _d: self.reload())
        worker.error.connect(
            lambda _id, e: QMessageBox.warning(
                self, "Ошибка", f"[{e.code}] {e.message}",
            ),
        )
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()


# ─────────────────────────────────────────────────────────────────────────
# InventorySection — wrapper с табами
# ─────────────────────────────────────────────────────────────────────────


class InventorySection(QWidget):
    """Управление складом — таб «Ингредиенты» / таб «Полуфабрикаты»."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"InventorySection {{ background: {COLORS['bg_light']}; }}"
        )
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        # Phase 8D — InventorySection занимает всю ширину content-area из SettingsScreen.
        # «Склад» заголовок уже виден в breadcrumb + sub-nav SettingsScreen — здесь не дублируем.
        # Tabbar — full-width white panel под main top-bar (см. frame sthqt).
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Phase 8D — tab-bar по дизайну (frame sthqt в pos_cashier.pen):
        # - неактивный: white fill, secondary text, 12px вес 600, без бордеров
        # - активный: bg-light fill, orange text/bottom-border 3px, вес 700
        # - tabbar fill white, гэп 4px, нижняя полоса 1px border-light
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{"
            f"  border: none;"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  background: {COLORS['bg_light']};"
            f"}}"
            f"QTabBar {{ background: {COLORS['bg_white']}; }}"
            f"QTabBar::tab {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_secondary']};"
            f"  height: 44px;"
            f"  padding: 0 12px;"
            f"  border: none;"
            f"  border-top-left-radius: 8px;"
            f"  border-top-right-radius: 8px;"
            f"  font-size: 12px; font-weight: 600;"
            f"  margin-right: 4px;"
            f"}}"
            f"QTabBar::tab:hover {{ background: {COLORS['bg_light']}; }}"
            f"QTabBar::tab:selected {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['accent_orange']};"
            f"  font-weight: 700;"
            f"  border-bottom: 3px solid {COLORS['accent_orange']};"
            f"}}"
        )
        # Phase 8D — 9 вкладок по дизайну (frames 25-33 in pos_cashier.pen):
        # 0 Продукты, 1 Хозтовары, 2 Полуфабрикаты, 3 Авто-стоп,
        # 4 Поставщики, 5 Накладные, 6 Списания, 7 Расход хозтоваров, 8 Инвентаризация
        self._products_pane = IngredientsPane(self._client, kind="food")
        self._household_pane = IngredientsPane(self._client, kind="household")
        self._semi_pane = SemiPane(self._client)
        self._autostop_pane = AutoStopPane(self._client)
        self._tabs.addTab(self._products_pane, "Продукты")
        self._tabs.addTab(self._household_pane, "Хозтовары")
        self._tabs.addTab(self._semi_pane, "Полуфабрикаты")
        self._tabs.addTab(self._autostop_pane, "Авто-стоп")

        # Phase 8A — лениво создаём остальные табы при первом переключении
        from pos.screens.settings_sections.inventory_panes_8a import (
            InventoryChecksPane,
            ReceiptsPane,
            SuppliersPane,
            SupplyExpensesPane,
            WriteoffsPane,
        )
        self._suppliers_pane = SuppliersPane(self._client)
        self._receipts_pane = ReceiptsPane(self._client)
        self._writeoffs_pane = WriteoffsPane(self._client)
        self._supply_pane = SupplyExpensesPane(self._client)
        self._checks_pane = InventoryChecksPane(self._client)
        self._tabs.addTab(self._suppliers_pane, "Поставщики")
        self._tabs.addTab(self._receipts_pane, "Накладные")
        self._tabs.addTab(self._writeoffs_pane, "Списания")
        self._tabs.addTab(self._supply_pane, "Расход хозтоваров")
        self._tabs.addTab(self._checks_pane, "Инвентаризация")

        # Backwards-compat alias для существующих тестов и кода:
        # `sec._ingredients_pane` теперь = Продукты (food)
        self._ingredients_pane = self._products_pane

        self._tabs.currentChanged.connect(self._on_tab_changed)
        v.addWidget(self._tabs, 1)

    def _on_tab_changed(self, idx: int) -> None:
        # Lazy-load для вкладок, требующих свежих данных
        if idx == 1 and not self._household_pane._items:
            self._household_pane.reload()
        elif idx == 2 and not self._semi_pane._items:
            self._semi_pane.reload()
        elif idx == 3:
            # AutoStop — всегда reload (быстро меняется)
            self._autostop_pane.reload()

    # -------- public --------

    def reload(self) -> None:
        """Перезагрузить активный таб."""
        idx = self._tabs.currentIndex()
        panes = {
            0: self._products_pane,
            1: self._household_pane,
            2: self._semi_pane,
            3: self._autostop_pane,
            4: self._suppliers_pane,
            5: self._receipts_pane,
            6: self._writeoffs_pane,
            7: self._supply_pane,
            8: self._checks_pane,
        }
        pane = panes.get(idx)
        if pane is not None and hasattr(pane, "reload"):
            pane.reload()

    # Backwards-compat для старых тестов: эти аттрибуты были на InventorySection
    @property
    def _table(self):
        return self._ingredients_pane._table

    @property
    def _items(self):
        return self._ingredients_pane._items

    def _on_loaded(self, items: list) -> None:
        self._ingredients_pane._on_loaded(items)
