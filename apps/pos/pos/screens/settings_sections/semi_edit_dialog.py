"""Создание/редактирование полуфабриката + inline recipe editor (Phase 7D-2).

Recipe rows: каждая строка = «тип компонента (Ингредиент/Полуфабрикат)»
+ «компонент» (динамический dropdown, фильтруется по типу) + qty_per_output
+ единица (read-only из выбранного) + кнопка удалить.
"""
from __future__ import annotations

from decimal import Decimal

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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


UNIT_CHOICES = [
    ("kg", "Килограмм"),
    ("g", "Грамм"),
    ("l", "Литр"),
    ("ml", "Миллилитр"),
    ("piece", "Штука"),
    ("pack", "Упаковка"),
    ("bottle", "Бутылка"),
]
UNIT_LABEL = {k: v for k, v in UNIT_CHOICES}


class SemiEditDialog(QDialog):
    """Edit semi-finished type + recipe lines."""

    def __init__(
        self,
        client: ApiClient,
        semi: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._semi = semi or {}
        # Список доступных компонентов
        self._ingredients: list[dict] = []
        self._semis: list[dict] = []
        # row_widgets: каждой строке — dict с references на виджеты
        self._rows: list[dict] = []

        self.setWindowTitle(
            "Редактировать полуфабрикат" if self._semi else "Новый полуфабрикат"
        )
        self.setModal(True)
        self.setFixedWidth(720)
        self.setMinimumHeight(600)
        self.setMaximumHeight(900)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 16px;"
            f"}}"
        )
        self._build()
        self._load_components()

    # -------- build --------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header (60px)
        header = QFrame()
        header.setFixedHeight(60)
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

        title = QLabel(self.windowTitle())
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 14pt; font-weight: 700; border: none;"
        )
        head_lay.addWidget(title)
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

        # 2. Scrollable Body
        content = QWidget()
        content.setStyleSheet("border: none; background: transparent;")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # Name field
        self.name_edit = QLineEdit(self._semi.get("name", ""))
        self.name_edit.setPlaceholderText("Фарш говяжий / Тесто / Бульон")
        self.name_edit.setStyleSheet(self._field_qss())
        self.name_edit.setFixedHeight(44)
        outer.addWidget(self._stack("Название полуфабриката", self.name_edit))

        # Numeric fields grid (Output unit, Yield percent, Low stock, Sort order)
        self.output_combo = QComboBox()
        for k, lbl in UNIT_CHOICES:
            self.output_combo.addItem(lbl, k)
        cur_unit = self._semi.get("output_unit") or "kg"
        for i in range(self.output_combo.count()):
            if self.output_combo.itemData(i) == cur_unit:
                self.output_combo.setCurrentIndex(i)
                break
        self.output_combo.setStyleSheet(self._field_qss())
        self.output_combo.setFixedHeight(44)

        self.yield_spin = QDoubleSpinBox()
        self.yield_spin.setRange(0, 100)
        self.yield_spin.setDecimals(2)
        self.yield_spin.setSuffix(" %")
        self.yield_spin.setValue(float(self._semi.get("yield_percent") or 100))
        self.yield_spin.setStyleSheet(self._field_qss())
        self.yield_spin.setFixedHeight(44)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0, 1_000_000)
        self.threshold_spin.setDecimals(2)
        thr = self._semi.get("low_stock_threshold")
        self.threshold_spin.setValue(float(thr) if thr else 0)
        self.threshold_spin.setSpecialValueText("—")
        self.threshold_spin.setStyleSheet(self._field_qss())
        self.threshold_spin.setFixedHeight(44)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 999)
        self.sort_spin.setValue(int(self._semi.get("sort_order", 0)))
        self.sort_spin.setStyleSheet(self._field_qss())
        self.sort_spin.setFixedHeight(44)

        row_nums = QWidget()
        row_lay = QHBoxLayout(row_nums)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(12)
        row_lay.addWidget(self._stack("Выход (ед.)", self.output_combo), 1)
        row_lay.addWidget(self._stack("Выход (% от сырья)", self.yield_spin), 1)
        row_lay.addWidget(self._stack("Низкий остаток", self.threshold_spin), 1)
        row_lay.addWidget(self._stack("Порядок сортировки", self.sort_spin), 1)
        outer.addWidget(row_nums)

        # Checkbox Active
        self.active_cb = QCheckBox("Активен (виден в техкартах и рецептах)")
        self.active_cb.setChecked(bool(self._semi.get("is_active", True)))
        self.active_cb.setStyleSheet(self._checkbox_qss())
        outer.addWidget(self.active_cb)

        # Recipe editor card
        outer.addWidget(self._lbl("Рецепт (расход ингредиентов на 1 единицу выхода)"))

        # G6zLGq container style inside design: white background, border, radius
        self._rows_holder = QWidget()
        self._rows_holder.setObjectName("RecipeRowsHolder")
        self._rows_holder.setStyleSheet(
            f"QWidget#RecipeRowsHolder {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"}}"
        )
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(8, 8, 8, 8)
        self._rows_layout.setSpacing(8)
        outer.addWidget(self._rows_holder)

        add_row_btn = QPushButton("+ Добавить компонент")
        add_row_btn.setFixedHeight(38)
        add_row_btn.setCursor(Qt.PointingHandCursor)
        add_row_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px dashed {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 0 14px; font-size: 10pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['bg_gray']};"
            f"  border: 1px dashed {COLORS['accent_orange']};"
            f"}}"
        )
        add_row_btn.clicked.connect(lambda: self._add_row(None))
        outer.addWidget(add_row_btn)

        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(content)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(scroll, 1)

        # 3. Footer (68px)
        footer = QFrame()
        footer.setFixedHeight(68)
        footer.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  border-bottom-left-radius: 15px;"
            f"  border-bottom-right-radius: 15px;"
            f"}}"
        )
        bv = QHBoxLayout(footer)
        bv.setContentsMargins(24, 0, 24, 0)
        bv.setSpacing(10)

        # Delete button if editing
        if self._semi.get("id"):
            del_btn = QPushButton("Удалить")
            del_btn.setFixedHeight(44)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['danger_red']};"
                f"  border: 1px solid {COLORS['danger_red']};"
                f"  border-radius: 8px;"
                f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: #FEE2E2; }}"
            )
            del_btn.clicked.connect(self._on_delete)
            bv.addWidget(del_btn)

        bv.addStretch(1)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(100)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        bv.addWidget(cancel)

        save = QPushButton("Сохранить")
        save.setFixedHeight(44)
        save.setMinimumWidth(130)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(self._save_qss())
        save.clicked.connect(self._save)
        bv.addWidget(save)
        root.addWidget(footer)

    def _stack(self, label_text: str, widget: QWidget) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = self._lbl(label_text)
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return w

    def _lbl(self, t: str) -> QLabel:
        l = QLabel(t)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; font-weight: 600; border: none;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 11pt;"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{"
            f"  border: 1px solid {COLORS['accent_orange']};"
            f"}}"
        )

    def _checkbox_qss(self) -> str:
        return (
            f"QCheckBox {{"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 10pt; font-weight: 500;"
            f"  spacing: 8px;"
            f"  border: none;"
            f"}}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; }}"
            f"QCheckBox::indicator:unchecked {{"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: 4px; background: {COLORS['bg_white']};"
            f"}}"
            f"QCheckBox::indicator:checked {{"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"  border-radius: 4px; background: {COLORS['accent_orange']};"
            f"}}"
        )

    def _cancel_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 0 22px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _save_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 8px;"
            f"  padding: 0 22px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )

    # -------- components loading + rows --------

    def _load_components(self) -> None:
        """Sync-загрузка — диалог модальный, блок ок."""
        try:
            ings = self._client.get("/inventory/ingredients/")
            self._ingredients = (
                ings if isinstance(ings, list) else (ings or {}).get("data", [])
            )
        except ApiError:
            self._ingredients = []
        try:
            sems = self._client.get("/inventory/semi/")
            all_semis = sems if isinstance(sems, list) else (sems or {}).get("data", [])
        except ApiError:
            all_semis = []
        # Из списка nested-semi исключаем сам себя (нельзя рекурсивный рецепт)
        my_id = self._semi.get("id")
        self._semis = [s for s in all_semis if s.get("id") != my_id]

        # Подгружаем существующие строки рецепта
        existing_lines = self._semi.get("recipe_lines") or []
        if existing_lines:
            for line in existing_lines:
                self._add_row(line)
        else:
            # пустой рецепт — 1 пустая строка для удобства
            self._add_row(None)

    def _add_row(self, line: dict | None) -> None:
        row = QFrame()
        row.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(8)

        type_combo = QComboBox()
        type_combo.addItem("Ингредиент", "ingredient")
        type_combo.addItem("Полуфабрикат", "semi")
        type_combo.setStyleSheet(self._field_qss())
        type_combo.setFixedWidth(140)
        h.addWidget(type_combo)

        comp_combo = QComboBox()
        comp_combo.setStyleSheet(self._field_qss())
        comp_combo.setMinimumWidth(220)
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
        unit_lbl.setFixedWidth(60)
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
            "row": row,
            "type": type_combo,
            "comp": comp_combo,
            "qty": qty_spin,
            "unit": unit_lbl,
        }

        def fill_comp_list(*_a):
            t = type_combo.currentData()
            comp_combo.clear()
            items = self._ingredients if t == "ingredient" else self._semis
            for it in items:
                lbl = it.get("name", "?")
                comp_combo.addItem(lbl, int(it["id"]))
            update_unit()

        def update_unit(*_a):
            t = type_combo.currentData()
            cid = comp_combo.currentData()
            if cid is None:
                unit_lbl.setText("—")
                return
            items = self._ingredients if t == "ingredient" else self._semis
            picked = next((i for i in items if int(i["id"]) == cid), None)
            if picked is None:
                unit_lbl.setText("—")
                return
            unit_key = picked.get("unit") or picked.get("output_unit") or ""
            unit_lbl.setText({
                "kg": "кг", "g": "г", "l": "л", "ml": "мл",
                "piece": "шт", "pack": "уп", "bottle": "бут",
            }.get(unit_key, unit_key))

        type_combo.currentIndexChanged.connect(fill_comp_list)
        comp_combo.currentIndexChanged.connect(update_unit)
        rm_btn.clicked.connect(lambda: self._remove_row(entry))

        # Применяем существующее значение (если редактирование)
        if line:
            if line.get("ingredient"):
                type_combo.setCurrentIndex(0)
                fill_comp_list()
                cid = line.get("ingredient")
                for i in range(comp_combo.count()):
                    if comp_combo.itemData(i) == int(cid):
                        comp_combo.setCurrentIndex(i)
                        break
            elif line.get("nested_semi"):
                type_combo.setCurrentIndex(1)
                fill_comp_list()
                cid = line.get("nested_semi")
                for i in range(comp_combo.count()):
                    if comp_combo.itemData(i) == int(cid):
                        comp_combo.setCurrentIndex(i)
                        break
            qty_spin.setValue(float(line.get("qty_per_output") or 0))
        else:
            fill_comp_list()

        self._rows.append(entry)
        self._rows_layout.addWidget(row)

    def _remove_row(self, entry: dict) -> None:
        try:
            self._rows.remove(entry)
        except ValueError:
            pass
        w = entry.get("row")
        if w is not None:
            w.deleteLater()

    # -------- save --------

    def _collect_payload(self) -> dict | None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return None
        recipe: list[dict] = []
        for entry in self._rows:
            t = entry["type"].currentData()
            cid = entry["comp"].currentData()
            qty = entry["qty"].value()
            if cid is None or qty <= 0:
                continue  # пропускаем пустые строки
            line: dict = {"qty_per_output": f"{qty:.2f}"}
            if t == "ingredient":
                line["ingredient"] = int(cid)
            else:
                line["nested_semi"] = int(cid)
            recipe.append(line)
        if not recipe:
            QMessageBox.warning(
                self, "Ошибка",
                "Рецепт должен содержать хотя бы 1 компонент",
            )
            return None
        thr = self.threshold_spin.value()
        return {
            "name": name,
            "output_unit": self.output_combo.currentData(),
            "yield_percent": f"{self.yield_spin.value():.2f}",
            "low_stock_threshold": f"{thr:.2f}" if thr > 0 else None,
            "sort_order": int(self.sort_spin.value()),
            "is_active": self.active_cb.isChecked(),
            "recipe_lines": recipe,
        }

    def _on_delete(self) -> None:
        name = self._semi.get("name", "?")
        ans = QMessageBox.question(
            self, "Удалить полуфабрикат?",
            f"«{name}» будет удалён.\n"
            "Если есть история — станет неактивен (soft-delete).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        try:
            self._client.request(
                "DELETE", f"/inventory/semi/{self._semi['id']}/",
                idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка удаления", f"[{e.code}] {e.message}")
            return
        self.accept()

    def _save(self) -> None:
        body = self._collect_payload()
        if body is None:
            return
        try:
            if self._semi.get("id"):
                self._client.request(
                    "PATCH", f"/inventory/semi/{self._semi['id']}/",
                    json=body, idempotent=True,
                )
            else:
                self._client.request(
                    "POST", "/inventory/semi/", json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка сохранения",
                f"[{e.code}] {e.message}",
            )
            return
        self.accept()
