"""Модалка create/edit для MenuItem — used from MenuSection (frame 19).

Расширенные поля (Phase «v1 menu features»): kind, cogs, cook_time_min,
unit/unit_size/sale_step (продажа на вес), is_purchased, is_batch_cooking +
prepared_qty + low_stock_threshold.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


UNIT_SHORT = {
    "kg": "кг", "g": "г", "l": "л", "ml": "мл",
    "piece": "шт", "pack": "уп", "bottle": "бут",
}

KIND_CHOICES = [
    ("hot_kitchen", "Горячий цех"),
    ("cold_kitchen", "Холодный цех"),
    ("grill", "Гриль"),
    ("bar", "Бар"),
    ("showcase", "Витрина"),
    ("drink", "Напиток"),
    ("dessert", "Десерт"),
]
UNIT_CHOICES = [
    ("piece", "штука"),
    ("g", "грамм"),
    ("kg", "килограмм"),
]

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class ItemEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        categories: list[dict],
        item: dict | None = None,
        default_category_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._categories = categories
        self._item = item or {}
        self._default_cat = default_category_id
        self.saved_data: dict | None = None

        self.setWindowTitle("Блюдо")
        self.setModal(True)
        self.setFixedWidth(540)
        self.setMinimumHeight(640)
        self.setMaximumHeight(900)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scrollable content
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(content)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(scroll, 1)

        title = QLabel("Редактировать блюдо" if self._item else "Добавить блюдо")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.cat_combo = QComboBox()
        for c in self._categories:
            self.cat_combo.addItem(c["name"], int(c["id"]))
        cur = self._item.get("category") or self._default_cat
        if cur is not None:
            for i in range(self.cat_combo.count()):
                if self.cat_combo.itemData(i) == int(cur):
                    self.cat_combo.setCurrentIndex(i)
                    break
        self.cat_combo.setStyleSheet(self._field_qss())
        self.cat_combo.setFixedHeight(40)
        form.addRow(self._lbl("Категория"), self.cat_combo)

        self.name_edit = QLineEdit(self._item.get("name", ""))
        self.name_edit.setPlaceholderText("Цезарь с курицей")
        self.name_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Название"), self.name_edit)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0, 1_000_000.0)
        self.price_spin.setDecimals(2)
        self.price_spin.setSingleStep(1.0)
        try:
            self.price_spin.setValue(float(self._item.get("price", 0) or 0))
        except (TypeError, ValueError):
            self.price_spin.setValue(0.0)
        self.price_spin.setSuffix(" TJS")
        self.price_spin.setStyleSheet(self._field_qss())
        self.price_spin.setFixedHeight(40)
        form.addRow(self._lbl("Цена"), self.price_spin)

        self.emoji_edit = QLineEdit(self._item.get("emoji", ""))
        self.emoji_edit.setMaxLength(8)
        self.emoji_edit.setPlaceholderText("🥗")
        self.emoji_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Эмодзи"), self.emoji_edit)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 999)
        self.sort_spin.setValue(int(self._item.get("sort_order", 0)))
        self.sort_spin.setStyleSheet(self._field_qss())
        self.sort_spin.setFixedHeight(40)
        form.addRow(self._lbl("Порядок"), self.sort_spin)

        outer.addLayout(form)

        self.avail_cb = QCheckBox("Доступно (в меню)")
        self.avail_cb.setChecked(bool(self._item.get("is_available", True)))
        self.avail_cb.setStyleSheet(
            f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 12pt; }}"
        )
        outer.addWidget(self.avail_cb)

        # ── Тип блюда ────────────────────────────────────────────────────
        self.kind_combo = QComboBox()
        for k, label in KIND_CHOICES:
            self.kind_combo.addItem(label, k)
        cur_kind = self._item.get("kind") or "hot_kitchen"
        for i in range(self.kind_combo.count()):
            if self.kind_combo.itemData(i) == cur_kind:
                self.kind_combo.setCurrentIndex(i)
                break
        self.kind_combo.setStyleSheet(self._field_qss())
        self.kind_combo.setFixedHeight(40)
        outer.addWidget(self._lbl("Тип блюда"))
        outer.addWidget(self.kind_combo)

        # ── Себестоимость + время готовки ─────────────────────────────────
        cogs_row = QHBoxLayout()
        cogs_row.setSpacing(SPACING["md"])

        cogs_col = QVBoxLayout()
        cogs_col.addWidget(self._lbl("Себестоимость"))
        self.cogs_spin = QDoubleSpinBox()
        self.cogs_spin.setRange(0.0, 1_000_000.0)
        self.cogs_spin.setDecimals(2)
        self.cogs_spin.setSingleStep(1.0)
        self.cogs_spin.setSuffix(" TJS")
        try:
            self.cogs_spin.setValue(float(self._item.get("cogs", 0) or 0))
        except (TypeError, ValueError):
            self.cogs_spin.setValue(0.0)
        self.cogs_spin.setStyleSheet(self._field_qss())
        self.cogs_spin.setFixedHeight(40)
        cogs_col.addWidget(self.cogs_spin)
        cogs_row.addLayout(cogs_col, 1)

        ck_col = QVBoxLayout()
        ck_col.addWidget(self._lbl("Готовится, мин."))
        self.cook_spin = QSpinBox()
        self.cook_spin.setRange(0, 999)
        ckm = self._item.get("cook_time_min")
        self.cook_spin.setValue(int(ckm) if ckm is not None else 0)
        self.cook_spin.setSpecialValueText("—")  # 0 → «—»
        self.cook_spin.setStyleSheet(self._field_qss())
        self.cook_spin.setFixedHeight(40)
        ck_col.addWidget(self.cook_spin)
        cogs_row.addLayout(ck_col, 1)
        outer.addLayout(cogs_row)

        # ── Toggle row: покупной / заготовочное / на вес ──────────────────
        toggles_lbl = QLabel("Особенности")
        toggles_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        outer.addWidget(toggles_lbl)

        self.purchased_cb = QCheckBox("Покупной товар (без техкарты)")
        self.purchased_cb.setChecked(bool(self._item.get("is_purchased", False)))
        self.auto_consume_cb = QCheckBox(
            "Автосписание со склада (по техкарте)"
        )
        self.auto_consume_cb.setChecked(
            bool(self._item.get("auto_consume", True))
        )
        self.batch_cb = QCheckBox("Заготовочное (партиями)")
        self.batch_cb.setChecked(bool(self._item.get("is_batch_cooking", False)))
        self.weight_cb = QCheckBox("Продажа на вес (г / кг)")
        self.weight_cb.setChecked(
            (self._item.get("unit") or "piece") in ("g", "kg")
        )
        for cb in (self.purchased_cb, self.auto_consume_cb, self.batch_cb, self.weight_cb):
            cb.setStyleSheet(
                f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 11pt; }}"
            )
            outer.addWidget(cb)

        # Mutually exclusive: purchased ↔ batch
        self.purchased_cb.toggled.connect(self._on_purchased_toggled)
        self.batch_cb.toggled.connect(self._on_batch_toggled)
        self.weight_cb.toggled.connect(self._refresh_panels)

        # ── Batch panel (prepared_qty + low_stock_threshold) ──────────────
        self._batch_panel = QFrame()
        self._batch_panel.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px; padding: 10px; }}"
        )
        bv = QHBoxLayout(self._batch_panel)
        bv.setSpacing(SPACING["md"])

        prep_col = QVBoxLayout()
        prep_col.addWidget(self._lbl("Готово порций"))
        self.prepared_spin = QSpinBox()
        self.prepared_spin.setRange(0, 9999)
        self.prepared_spin.setValue(int(self._item.get("prepared_qty", 0) or 0))
        self.prepared_spin.setStyleSheet(self._field_qss())
        self.prepared_spin.setFixedHeight(36)
        prep_col.addWidget(self.prepared_spin)
        bv.addLayout(prep_col, 1)

        thr_col = QVBoxLayout()
        thr_col.addWidget(self._lbl("Порог «заканчивается»"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 999)
        thr = self._item.get("low_stock_threshold")
        self.threshold_spin.setValue(int(thr) if thr else 5)
        self.threshold_spin.setStyleSheet(self._field_qss())
        self.threshold_spin.setFixedHeight(36)
        thr_col.addWidget(self.threshold_spin)
        bv.addLayout(thr_col, 1)

        # «Заготовить +N» — открывает BatchCookDialog (Phase 7E)
        cook_col = QVBoxLayout()
        cook_col.addWidget(self._lbl(" "))
        cook_btn = QPushButton("+ Заготовить")
        cook_btn.setFixedHeight(36)
        cook_btn.setCursor(Qt.PointingHandCursor)
        cook_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 700;"
            f"}}"
        )
        cook_btn.setEnabled(bool(self._item.get("id")))
        cook_btn.clicked.connect(self._open_batch_cook)
        cook_col.addWidget(cook_btn)
        bv.addLayout(cook_col, 0)
        outer.addWidget(self._batch_panel)

        # ── Weight panel (unit + unit_size + sale_step) ───────────────────
        self._weight_panel = QFrame()
        self._weight_panel.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px; padding: 10px; }}"
        )
        wv = QHBoxLayout(self._weight_panel)
        wv.setSpacing(SPACING["md"])

        u_col = QVBoxLayout()
        u_col.addWidget(self._lbl("Единица"))
        self.unit_combo = QComboBox()
        for u, ulbl in UNIT_CHOICES:
            self.unit_combo.addItem(ulbl, u)
        cur_unit = self._item.get("unit") or "piece"
        for i in range(self.unit_combo.count()):
            if self.unit_combo.itemData(i) == cur_unit:
                self.unit_combo.setCurrentIndex(i)
                break
        self.unit_combo.setStyleSheet(self._field_qss())
        self.unit_combo.setFixedHeight(36)
        u_col.addWidget(self.unit_combo)
        wv.addLayout(u_col, 1)

        size_col = QVBoxLayout()
        size_col.addWidget(self._lbl("Цена за"))
        self.unit_size_spin = QSpinBox()
        self.unit_size_spin.setRange(1, 100_000)
        self.unit_size_spin.setValue(int(self._item.get("unit_size", 1) or 1))
        self.unit_size_spin.setStyleSheet(self._field_qss())
        self.unit_size_spin.setFixedHeight(36)
        size_col.addWidget(self.unit_size_spin)
        wv.addLayout(size_col, 1)

        step_col = QVBoxLayout()
        step_col.addWidget(self._lbl("Шаг продажи"))
        self.sale_step_spin = QSpinBox()
        self.sale_step_spin.setRange(0, 100_000)
        self.sale_step_spin.setValue(int(self._item.get("sale_step", 0) or 0))
        self.sale_step_spin.setStyleSheet(self._field_qss())
        self.sale_step_spin.setFixedHeight(36)
        step_col.addWidget(self.sale_step_spin)
        wv.addLayout(step_col, 1)
        outer.addWidget(self._weight_panel)

        # Группы модификаторов — checkable list (multi-select).
        outer.addWidget(self._lbl("Группы модификаторов"))
        self.mods_list = QListWidget()
        self.mods_list.setMaximumHeight(140)
        self.mods_list.setStyleSheet(
            f"QListWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt;"
            f"}}"
        )
        self._load_modifier_groups()
        outer.addWidget(self.mods_list)

        # ── Техкарта (recipe lines на 1 порцию блюда) ─────────────────────
        self._techcard_lines: list[dict] = []
        self._tc_ingredients: list[dict] = []
        self._tc_semis: list[dict] = []
        self._tc_rows: list[dict] = []

        self._techcard_panel = QFrame()
        self._techcard_panel.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_white']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px; padding: 10px; }}"
        )
        tcv = QVBoxLayout(self._techcard_panel)
        tcv.setSpacing(SPACING["sm"])
        tcv.setContentsMargins(0, 0, 0, 0)

        tc_head = QHBoxLayout()
        tc_title = QLabel("Техкарта (на 1 порцию)")
        tc_title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700;"
        )
        tc_head.addWidget(tc_title)
        tc_head.addStretch(1)
        self._tc_cogs_lbl = QLabel("Себестоимость: —")
        self._tc_cogs_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; font-style: italic;"
        )
        tc_head.addWidget(self._tc_cogs_lbl)
        tcv.addLayout(tc_head)

        self._tc_rows_holder = QWidget()
        self._tc_rows_holder.setStyleSheet("background: transparent;")
        self._tc_rows_layout = QVBoxLayout(self._tc_rows_holder)
        self._tc_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._tc_rows_layout.setSpacing(SPACING["sm"])
        tcv.addWidget(self._tc_rows_holder)

        tc_add = QPushButton("+ Компонент")
        tc_add.setFixedHeight(34)
        tc_add.setCursor(Qt.PointingHandCursor)
        tc_add.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px dashed {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        tc_add.clicked.connect(lambda: self._add_tc_row(None))
        tcv.addWidget(tc_add)

        outer.addWidget(self._techcard_panel)
        self._load_techcard_components()

        self._refresh_panels()
        outer.addStretch(1)

        # Footer (вне scroll, всегда виден)
        footer = QFrame()
        footer.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        btns = QHBoxLayout(footer)
        btns.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])
        btns.addStretch(1)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        save = QPushButton("Сохранить")
        save.setFixedHeight(40)
        save.setMinimumWidth(140)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(self._save_qss())
        save.clicked.connect(self._save)
        btns.addWidget(save)
        root.addWidget(footer)

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"}}"
        )

    def _cancel_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _save_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )

    # ── Toggles / panels ────────────────────────────────────────────────

    def _on_purchased_toggled(self, checked: bool) -> None:
        if checked:
            self.batch_cb.setChecked(False)
        self._refresh_panels()

    def _on_batch_toggled(self, checked: bool) -> None:
        if checked:
            self.purchased_cb.setChecked(False)
        self._refresh_panels()

    def _refresh_panels(self) -> None:
        """Показывает / скрывает batch и weight панели в зависимости от toggle."""
        if hasattr(self, "_batch_panel"):
            self._batch_panel.setVisible(self.batch_cb.isChecked())
        if hasattr(self, "_weight_panel"):
            self._weight_panel.setVisible(self.weight_cb.isChecked())
        if hasattr(self, "_techcard_panel"):
            # У покупных товаров техкарты быть не может
            self._techcard_panel.setVisible(not self.purchased_cb.isChecked())
        # Если weight выключен — unit принудительно сбросим в piece при сохранении.
        # Если включён, но в combo стоит "piece" — переключаем в "g".
        if self.weight_cb.isChecked():
            cur = self.unit_combo.currentData()
            if cur == "piece":
                for i in range(self.unit_combo.count()):
                    if self.unit_combo.itemData(i) == "g":
                        self.unit_combo.setCurrentIndex(i)
                        break
                if self.unit_size_spin.value() <= 1:
                    self.unit_size_spin.setValue(100)
                if self.sale_step_spin.value() == 0:
                    self.sale_step_spin.setValue(50)

    def _load_modifier_groups(self) -> None:
        """Заполнить self.mods_list группами ресторана. Преселектить — те, что
        уже привязаны к редактируемому блюду (`item.modifier_groups`)."""
        try:
            data = self._client.get("/menu/modifier-groups/")
        except ApiError:
            return
        groups = data if isinstance(data, list) else (data or {}).get("data", [])
        already = {
            int(g.get("id")) for g in (self._item.get("modifier_groups") or [])
            if g.get("id") is not None
        }
        for g in groups:
            it = QListWidgetItem(g.get("name", ""))
            it.setData(Qt.UserRole, int(g["id"]))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(
                Qt.Checked if int(g["id"]) in already else Qt.Unchecked
            )
            self.mods_list.addItem(it)

    def _selected_modifier_group_ids(self) -> list[int]:
        ids: list[int] = []
        for i in range(self.mods_list.count()):
            it = self.mods_list.item(i)
            if it.checkState() == Qt.Checked:
                ids.append(int(it.data(Qt.UserRole)))
        return ids

    # ── Batch cooking «+N порций» ───────────────────────────────────────

    def _open_batch_cook(self) -> None:
        if not self._item.get("id"):
            return
        from .batch_cook_dialog import BatchCookDialog

        dlg = BatchCookDialog(self._client, self._item, parent=self)
        if dlg.exec() == QDialog.Accepted:
            # Перечитать актуальный prepared_qty (после успешной заготовки)
            try:
                fresh = self._client.get(f"/menu/items/{self._item['id']}/")
                if isinstance(fresh, dict):
                    self._item.update(fresh.get("data", fresh))
                    self.prepared_spin.setValue(
                        int(self._item.get("prepared_qty", 0) or 0)
                    )
            except Exception:
                pass

    # ── Tech-card editor ────────────────────────────────────────────────

    def _load_techcard_components(self) -> None:
        """Sync-загрузка компонентов + существующих строк техкарты."""
        try:
            data = self._client.get("/inventory/ingredients/")
            self._tc_ingredients = (
                data if isinstance(data, list) else (data or {}).get("data", [])
            )
        except ApiError:
            self._tc_ingredients = []
        try:
            data = self._client.get("/inventory/semi/")
            self._tc_semis = (
                data if isinstance(data, list) else (data or {}).get("data", [])
            )
        except ApiError:
            self._tc_semis = []

        existing: list[dict] = []
        if self._item.get("id"):
            try:
                resp = self._client.get(
                    f"/menu/items/{self._item['id']}/tech_card/"
                )
                existing = (
                    resp if isinstance(resp, list) else (resp or {}).get("data", [])
                )
            except ApiError:
                existing = []

        if existing:
            for ln in existing:
                self._add_tc_row(ln)
        # Не добавляем пустую строку: техкарта может отсутствовать (товар без рецепта).

    def _add_tc_row(self, line: dict | None) -> None:
        row = QFrame()
        row.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(8)

        type_combo = QComboBox()
        type_combo.addItem("Ингредиент", "ingredient")
        type_combo.addItem("Полуфабрикат", "semi")
        type_combo.setStyleSheet(self._field_qss())
        type_combo.setFixedWidth(140)
        h.addWidget(type_combo)

        comp_combo = QComboBox()
        comp_combo.setStyleSheet(self._field_qss())
        comp_combo.setMinimumWidth(200)
        h.addWidget(comp_combo, 1)

        qty_spin = QDoubleSpinBox()
        qty_spin.setRange(0.0001, 1_000_000)
        qty_spin.setDecimals(2)
        qty_spin.setStyleSheet(self._field_qss())
        qty_spin.setFixedWidth(110)
        h.addWidget(qty_spin)

        unit_lbl = QLabel("—")
        unit_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; padding: 0 4px;"
        )
        unit_lbl.setFixedWidth(50)
        h.addWidget(unit_lbl)

        rm_btn = QPushButton("×")
        rm_btn.setFixedSize(32, 32)
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  font-size: 16pt; font-weight: 700;"
            f"  border: 1px solid transparent;"
            f"  border-radius: 4px;"
            f"}}"
            f"QPushButton:hover {{ background: #FEF2F2; }}"
        )
        h.addWidget(rm_btn)

        entry = {
            "row": row, "type": type_combo, "comp": comp_combo,
            "qty": qty_spin, "unit": unit_lbl,
        }

        def fill_comp_list(*_a):
            t = type_combo.currentData()
            comp_combo.clear()
            items = self._tc_ingredients if t == "ingredient" else self._tc_semis
            for it in items:
                comp_combo.addItem(it.get("name", "?"), int(it["id"]))
            update_unit()

        def update_unit(*_a):
            t = type_combo.currentData()
            cid = comp_combo.currentData()
            if cid is None:
                unit_lbl.setText("—")
                self._update_tc_cogs()
                return
            items = self._tc_ingredients if t == "ingredient" else self._tc_semis
            picked = next((i for i in items if int(i["id"]) == cid), None)
            if picked is None:
                unit_lbl.setText("—")
                self._update_tc_cogs()
                return
            unit_key = picked.get("unit") or picked.get("output_unit") or ""
            unit_lbl.setText(UNIT_SHORT.get(unit_key, unit_key))
            self._update_tc_cogs()

        type_combo.currentIndexChanged.connect(fill_comp_list)
        comp_combo.currentIndexChanged.connect(update_unit)
        qty_spin.valueChanged.connect(self._update_tc_cogs)
        rm_btn.clicked.connect(lambda: self._remove_tc_row(entry))

        if line:
            if line.get("ingredient"):
                type_combo.setCurrentIndex(0)
                fill_comp_list()
                cid = int(line["ingredient"])
                for i in range(comp_combo.count()):
                    if comp_combo.itemData(i) == cid:
                        comp_combo.setCurrentIndex(i)
                        break
            elif line.get("nested_semi"):
                type_combo.setCurrentIndex(1)
                fill_comp_list()
                cid = int(line["nested_semi"])
                for i in range(comp_combo.count()):
                    if comp_combo.itemData(i) == cid:
                        comp_combo.setCurrentIndex(i)
                        break
            qty_spin.setValue(float(line.get("qty_per_unit") or 0))
        else:
            fill_comp_list()

        self._tc_rows.append(entry)
        self._tc_rows_layout.addWidget(row)
        self._update_tc_cogs()

    def _remove_tc_row(self, entry: dict) -> None:
        try:
            self._tc_rows.remove(entry)
        except ValueError:
            pass
        w = entry.get("row")
        if w is not None:
            w.deleteLater()
        self._update_tc_cogs()

    def _update_tc_cogs(self) -> None:
        """Live preview: Σ(qty × component.avg_cost)."""
        from decimal import Decimal
        total = Decimal("0")
        any_priced = False
        for e in self._tc_rows:
            t = e["type"].currentData()
            cid = e["comp"].currentData()
            qty = e["qty"].value()
            if cid is None or qty <= 0:
                continue
            items = self._tc_ingredients if t == "ingredient" else self._tc_semis
            picked = next((i for i in items if int(i["id"]) == cid), None)
            if not picked:
                continue
            cost = picked.get("avg_cost_per_unit") or picked.get("avg_cost") or 0
            try:
                total += Decimal(str(qty)) * Decimal(str(cost))
                any_priced = True
            except Exception:
                pass
        if any_priced:
            self._tc_cogs_lbl.setText(f"Себестоимость: {total:.2f} TJS")
        else:
            self._tc_cogs_lbl.setText("Себестоимость: —")

    def _collect_techcard_lines(self) -> list[dict]:
        lines: list[dict] = []
        sort_idx = 0
        for e in self._tc_rows:
            t = e["type"].currentData()
            cid = e["comp"].currentData()
            qty = e["qty"].value()
            if cid is None or qty <= 0:
                continue
            line: dict = {
                "qty_per_unit": f"{qty:.2f}",
                "sort_order": sort_idx,
            }
            if t == "ingredient":
                line["ingredient"] = int(cid)
            else:
                line["nested_semi"] = int(cid)
            lines.append(line)
            sort_idx += 1
        return lines

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        if self.cat_combo.currentData() is None:
            QMessageBox.warning(self, "Ошибка", "Сначала добавьте категорию")
            return
        # Расширенные поля
        cook = int(self.cook_spin.value())
        body = {
            "category": int(self.cat_combo.currentData()),
            "name": name,
            "price": f"{self.price_spin.value():.2f}",
            "emoji": self.emoji_edit.text().strip(),
            "sort_order": int(self.sort_spin.value()),
            "is_available": self.avail_cb.isChecked(),
            "modifier_group_ids": self._selected_modifier_group_ids(),
            "kind": self.kind_combo.currentData() or "hot_kitchen",
            "cogs": f"{self.cogs_spin.value():.2f}",
            "cook_time_min": cook if cook > 0 else None,
            "is_purchased": self.purchased_cb.isChecked(),
            "auto_consume": self.auto_consume_cb.isChecked(),
            "is_batch_cooking": self.batch_cb.isChecked(),
        }
        if self.batch_cb.isChecked():
            body["prepared_qty"] = int(self.prepared_spin.value())
            body["low_stock_threshold"] = int(self.threshold_spin.value())
        else:
            body["prepared_qty"] = 0
        if self.weight_cb.isChecked():
            body["unit"] = self.unit_combo.currentData() or "g"
            body["unit_size"] = max(1, int(self.unit_size_spin.value()))
            body["sale_step"] = int(self.sale_step_spin.value())
        else:
            body["unit"] = "piece"
            body["unit_size"] = 1
            body["sale_step"] = 0
        try:
            if self._item.get("id"):
                data = self._client.request(
                    "PATCH",
                    f"/menu/items/{self._item['id']}/",
                    json=body,
                    idempotent=True,
                )
            else:
                data = self._client.request(
                    "POST", "/menu/items/", json=body, idempotent=True
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e.message}")
            return

        # Сохраняем техкарту (если блюдо не покупное)
        item_id = None
        if isinstance(data, dict):
            item_id = data.get("id")
        if item_id is None:
            item_id = self._item.get("id")
        if item_id and not self.purchased_cb.isChecked():
            tc_lines = self._collect_techcard_lines()
            try:
                self._client.request(
                    "PUT",
                    f"/menu/items/{item_id}/tech_card/",
                    json={"lines": tc_lines},
                    idempotent=True,
                )
            except ApiError as e:
                QMessageBox.warning(
                    self, "Техкарта не сохранена",
                    f"Блюдо сохранено, но техкарта не обновлена: [{e.code}] {e.message}",
                )

        self.saved_data = data if isinstance(data, dict) else body
        self.accept()
