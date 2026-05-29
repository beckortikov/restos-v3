"""Модалка create/edit для Category — used from MenuSection (frame 19)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
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


class CategoryEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        category: dict | None = None,
        stations: list[dict] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._cat = category or {}
        # Список цехов передаёт MenuSection (он уже знает их). Если не передан —
        # лениво грузим сами через GET /printing/stations/.
        self._stations: list[dict] = stations if stations is not None else self._fetch_stations()
        self.saved_data: dict | None = None

        self.setWindowTitle("Категория")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _fetch_stations(self) -> list[dict]:
        try:
            data = self._client.get("/printing/stations/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            return [s for s in items if s.get("is_active", True)]
        except ApiError:
            return []

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        title = QLabel("Редактировать категорию" if self._cat else "Добавить категорию")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.name_edit = QLineEdit(self._cat.get("name", ""))
        self.name_edit.setPlaceholderText("Салаты / Супы / Горячее")
        self.name_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Название"), self.name_edit)

        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 999)
        self.sort_spin.setValue(int(self._cat.get("sort_order", 0)))
        self.sort_spin.setStyleSheet(self._field_qss())
        self.sort_spin.setFixedHeight(40)
        form.addRow(self._lbl("Порядок"), self.sort_spin)

        # Цех печати — ключевое для правильной маршрутизации заказов на кухню.
        self.station_combo = QComboBox()
        self.station_combo.addItem("— Без цеха (только гостевой чек) —", None)
        for st in sorted(
            self._stations,
            key=lambda s: (int(s.get("sort_order", 0)), s.get("name", "")),
        ):
            label = st.get("name", "?")
            if st.get("is_system"):
                label = f"{label} (system)"
            self.station_combo.addItem(label, int(st["id"]))
        cur = self._cat.get("print_station")
        for i in range(self.station_combo.count()):
            if self.station_combo.itemData(i) == cur:
                self.station_combo.setCurrentIndex(i)
                break
        self.station_combo.setStyleSheet(self._field_qss())
        self.station_combo.setFixedHeight(40)
        form.addRow(self._lbl("Цех печати"), self.station_combo)

        outer.addLayout(form)
        outer.addStretch(1)

        btns = QHBoxLayout()
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
        outer.addLayout(btns)

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QSpinBox:focus {{"
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

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        body = {
            "name": name,
            "sort_order": int(self.sort_spin.value()),
            "print_station": self.station_combo.currentData(),  # int | None
        }
        try:
            if self._cat.get("id"):
                data = self._client.request(
                    "PATCH",
                    f"/menu/categories/{self._cat['id']}/",
                    json=body,
                    idempotent=True,
                )
            else:
                data = self._client.request(
                    "POST", "/menu/categories/", json=body, idempotent=True
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e.message}")
            return
        self.saved_data = data if isinstance(data, dict) else body
        self.accept()
