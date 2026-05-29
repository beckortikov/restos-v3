"""Диалог выбора модификаторов при добавлении блюда в корзину.

Открывается из MenuScreen, если у блюда есть `modifier_groups`. Каждая группа
рендерится как секция:
- single-select (max_select=1) → радио-кнопки
- multi-select (max_select>1) → чекбоксы

Required-группы помечены звёздочкой; ОК блокируется пока не выбран минимум
из каждой required-группы. Цена обновляется в реальном времени (price + Σ
price_delta выбранных опций).
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING


class ModifierPickerDialog(QDialog):
    """Возвращает (modifier_ids, modifiers_snapshot) через свойства после Accept."""

    def __init__(self, menu_item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._menu_item = menu_item
        self._groups = list(menu_item.get("modifier_groups") or [])
        # group_id -> list of QAbstractButton (radio или checkbox)
        self._buttons_by_group: dict[int, list] = {}
        # button -> (modifier_dict, group_dict)
        self._meta: dict = {}

        self.setWindowTitle("Выбор опций")
        self.setModal(True)
        self.setMinimumSize(440, 520)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()
        self._update_state()

    # ---- public ----

    @property
    def chosen_modifier_ids(self) -> list[int]:
        ids: list[int] = []
        for g in self._groups:
            for btn in self._buttons_by_group.get(int(g["id"]), []):
                if btn.isChecked():
                    mod, _g = self._meta[id(btn)]
                    ids.append(int(mod["id"]))
        return ids

    @property
    def chosen_modifiers_snapshot(self) -> list[dict]:
        out: list[dict] = []
        for g in self._groups:
            for btn in self._buttons_by_group.get(int(g["id"]), []):
                if btn.isChecked():
                    mod, _g = self._meta[id(btn)]
                    out.append({
                        "id": int(mod["id"]),
                        "name": mod.get("name", ""),
                        "price_delta": str(mod.get("price_delta") or "0"),
                    })
        return out

    # ---- build ----

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        title = QLabel(self._menu_item.get("name", "Блюдо"))
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 800;"
        )
        v.addWidget(title)

        # Группы — внутри scroll-area (на случай длинного списка).
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        gv = QVBoxLayout(holder)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(SPACING["lg"])
        gv.setAlignment(Qt.AlignTop)

        for g in self._groups:
            gv.addWidget(self._build_group(g))

        if not self._groups:
            empty = QLabel("Опции не настроены")
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-style: italic;"
            )
            gv.addWidget(empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

        # Footer — total + buttons
        self._total_lbl = QLabel("")
        self._total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 14pt; font-weight: 800;"
        )
        v.addWidget(self._total_lbl)

        btns = QHBoxLayout()
        btns.setSpacing(SPACING["md"])

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addStretch(1)

        self._ok_btn = QPushButton("Добавить")
        self._ok_btn.setFixedHeight(44)
        self._ok_btn.setMinimumWidth(160)
        self._ok_btn.setCursor(Qt.PointingHandCursor)
        self._ok_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 24px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #EA5E0C; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._ok_btn.clicked.connect(self.accept)
        btns.addWidget(self._ok_btn)
        v.addLayout(btns)

    def _build_group(self, group: dict) -> QWidget:
        gid = int(group["id"])
        is_required = bool(group.get("is_required"))
        max_sel = int(group.get("max_select") or 1)
        single = max_sel <= 1

        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 12px 14px;"
            f"}}"
        )
        gv = QVBoxLayout(frame)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(6)

        title_text = group.get("name", "")
        if is_required:
            title_text += " *"
        elif group.get("min_select") or 0 > 0:
            title_text += f" (мин. {group['min_select']})"
        if max_sel > 1:
            title_text += f"  — до {max_sel}"
        head = QLabel(title_text)
        head.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700; border: none;"
            f" background: transparent;"
        )
        gv.addWidget(head)

        button_group = QButtonGroup(frame) if single else None
        if button_group is not None:
            button_group.setExclusive(True)

        buttons: list = []
        for m in group.get("modifiers") or []:
            if not m.get("is_active", True):
                continue
            label = m.get("name", "")
            try:
                d = Decimal(str(m.get("price_delta") or "0"))
            except Exception:
                d = Decimal("0")
            if d != 0:
                sign = "+" if d > 0 else "−"
                label += f"  ({sign}{abs(d)})"
            btn = QRadioButton(label) if single else QCheckBox(label)
            btn.setStyleSheet(
                f"QRadioButton, QCheckBox {{"
                f"  color: {COLORS['text_primary']};"
                f"  font-size: 11pt; padding: 4px 0;"
                f"  background: transparent;"
                f"}}"
            )
            btn.toggled.connect(self._update_state)
            if button_group is not None:
                button_group.addButton(btn)
            self._meta[id(btn)] = (m, group)
            buttons.append(btn)
            gv.addWidget(btn)

        self._buttons_by_group[gid] = buttons
        return frame

    def _update_state(self) -> None:
        # Проверяем валидность: required и min_select для каждой группы.
        ok = True
        for g in self._groups:
            min_s = int(g.get("min_select") or 0)
            if g.get("is_required") and min_s < 1:
                min_s = 1
            max_s = int(g.get("max_select") or 1)
            chosen = sum(
                1 for b in self._buttons_by_group.get(int(g["id"]), [])
                if b.isChecked()
            )
            if chosen < min_s or chosen > max_s:
                ok = False
                break
        self._ok_btn.setEnabled(ok)

        # Total
        base = Decimal(str(self._menu_item.get("price") or "0"))
        delta = Decimal("0")
        for snap in self.chosen_modifiers_snapshot:
            delta += Decimal(str(snap["price_delta"]))
        total = base + delta
        self._total_lbl.setText(f"Итого за единицу: {total:.2f}")
