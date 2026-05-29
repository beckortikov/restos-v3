"""Создание/редактирование ингредиента — Phase 7D-1."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.resources.icons import qicon


UNIT_CHOICES = [
    ("kg", "Килограмм"),
    ("g", "Грамм"),
    ("l", "Литр"),
    ("ml", "Миллилитр"),
    ("piece", "Штука"),
    ("pack", "Упаковка"),
    ("bottle", "Бутылка"),
]


class IngredientEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        ingredient: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._ing = ingredient or {}
        self.setWindowTitle("Ингредиент")
        self.setModal(True)
        self.setFixedWidth(520)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 16px;"
            f"}}"
        )
        self._build()

    def _build(self) -> None:
        # Main layout
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

        title = QLabel(
            "Редактировать ингредиент" if self._ing else "Новый ингредиент"
        )
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

        # 2. Body (scrollable/padding)
        body = QWidget()
        body.setStyleSheet("border: none;")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 24, 24, 24)
        body_lay.setSpacing(16)

        # Name
        self.name_edit = QLineEdit(self._ing.get("name", ""))
        self.name_edit.setPlaceholderText("Говядина / Мука / Кока-Кола 0.5л")
        self.name_edit.setStyleSheet(self._field_qss())
        self.name_edit.setFixedHeight(44)
        body_lay.addWidget(self._stack("Название", self.name_edit))

        # Unit
        self.unit_combo = QComboBox()
        for v, lbl in UNIT_CHOICES:
            self.unit_combo.addItem(lbl, v)
        cur = self._ing.get("unit") or "g"
        for i in range(self.unit_combo.count()):
            if self.unit_combo.itemData(i) == cur:
                self.unit_combo.setCurrentIndex(i)
                break
        self.unit_combo.setStyleSheet(self._field_qss())
        self.unit_combo.setFixedHeight(44)
        body_lay.addWidget(self._stack("Единица измерения", self.unit_combo))

        # Threshold & Order (side-by-side)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0, 1_000_000)
        self.threshold_spin.setDecimals(2)
        thr = self._ing.get("low_stock_threshold")
        self.threshold_spin.setValue(float(thr) if thr else 0)
        self.threshold_spin.setSpecialValueText("—")  # 0 = «не задан»
        self.threshold_spin.setStyleSheet(self._field_qss())
        self.threshold_spin.setFixedHeight(44)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 999)
        self.sort_spin.setValue(int(self._ing.get("sort_order", 0)))
        self.sort_spin.setStyleSheet(self._field_qss())
        self.sort_spin.setFixedHeight(44)

        row_spins = QWidget()
        row_lay = QHBoxLayout(row_spins)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(12)
        row_lay.addWidget(self._stack("Низкий остаток", self.threshold_spin), 1)
        row_lay.addWidget(self._stack("Порядок сортировки", self.sort_spin), 1)
        body_lay.addWidget(row_spins)

        # Checkboxes (horizontal row)
        self.active_cb = QCheckBox("Активен (виден в техкартах)")
        self.active_cb.setChecked(bool(self._ing.get("is_active", True)))
        self.active_cb.setStyleSheet(self._checkbox_qss())

        self.food_cb = QCheckBox("Продукт (если выкл. — хозтовар)")
        self.food_cb.setChecked(bool(self._ing.get("is_food", True)))
        self.food_cb.setStyleSheet(self._checkbox_qss())

        row_cbs = QWidget()
        cbs_lay = QHBoxLayout(row_cbs)
        cbs_lay.setContentsMargins(0, 4, 0, 4)
        cbs_lay.setSpacing(12)
        cbs_lay.addWidget(self.active_cb)
        cbs_lay.addWidget(self.food_cb)
        body_lay.addWidget(row_cbs)

        body_lay.addStretch(1)
        root.addWidget(body, 1)

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
        foot_lay = QHBoxLayout(footer)
        foot_lay.setContentsMargins(24, 0, 24, 0)
        foot_lay.setSpacing(10)

        # Delete button if editing
        if self._ing.get("id"):
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
            foot_lay.addWidget(del_btn)

        foot_lay.addStretch(1)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(100)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        foot_lay.addWidget(cancel)

        save = QPushButton("Сохранить")
        save.setFixedHeight(44)
        save.setMinimumWidth(120)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(self._save_qss())
        save.clicked.connect(self._save)
        foot_lay.addWidget(save)

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

    def _on_delete(self) -> None:
        name = self._ing.get("name", "?")
        ans = QMessageBox.question(
            self, "Удалить ингредиент?",
            f"«{name}» будет удалён.\n"
            "Если есть история движений — станет неактивен (soft-delete).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        try:
            self._client.request(
                "DELETE", f"/inventory/ingredients/{self._ing['id']}/",
                idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка удаления", f"[{e.code}] {e.message}")
            return
        # Закрываем как Accepted, чтобы пейн перезагрузился
        self.accept()

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        thr = self.threshold_spin.value()
        body = {
            "name": name,
            "unit": self.unit_combo.currentData(),
            "sort_order": int(self.sort_spin.value()),
            "is_active": self.active_cb.isChecked(),
            "is_food": self.food_cb.isChecked(),
            "low_stock_threshold": (
                f"{thr:.2f}" if thr > 0 else None
            ),
        }
        try:
            if self._ing.get("id"):
                self._client.request(
                    "PATCH", f"/inventory/ingredients/{self._ing['id']}/",
                    json=body, idempotent=True,
                )
            else:
                self._client.request(
                    "POST", "/inventory/ingredients/",
                    json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка сохранения",
                f"[{e.code}] {e.message}",
            )
            return
        self.accept()
