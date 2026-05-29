"""Create/edit стола."""
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


class TableEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        zones: list[dict],
        table: dict | None = None,
        default_zone_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._zones = zones
        self._table = table or {}
        self._default_zone = default_zone_id
        self._waiters: list[dict] = []
        # Кэш «занятых номеров» для текущей зоны (для inline-валидации).
        self._taken_numbers: set[int] = set()

        self.setWindowTitle("Стол")
        self.setModal(True)
        self.setFixedWidth(480)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()
        self._load_waiters()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        outer.setSpacing(SPACING["lg"])

        title = QLabel(
            "Редактировать стол" if self._table else "Новый стол"
        )
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.name_edit = QLineEdit(self._table.get("name", ""))
        self.name_edit.setPlaceholderText("Стол у окна")
        self.name_edit.setStyleSheet(self._field_qss())
        self.name_edit.setFixedHeight(40)
        form.addRow(self._lbl("Название"), self.name_edit)

        self.number_spin = QSpinBox()
        self.number_spin.setRange(1, 9999)
        self.number_spin.setValue(int(self._table.get("number", 1) or 1))
        self.number_spin.setStyleSheet(self._field_qss())
        self.number_spin.setFixedHeight(40)
        self.number_spin.valueChanged.connect(self._on_number_changed)
        # Inline-предупреждение под номером.
        self._number_warning = QLabel("")
        self._number_warning.setStyleSheet(
            f"color: {COLORS['danger_red']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        self._number_warning.setVisible(False)
        num_wrap = QWidget()
        num_v = QVBoxLayout(num_wrap)
        num_v.setContentsMargins(0, 0, 0, 0)
        num_v.setSpacing(2)
        num_v.addWidget(self.number_spin)
        num_v.addWidget(self._number_warning)
        form.addRow(self._lbl("Номер"), num_wrap)

        self.capacity_spin = QSpinBox()
        self.capacity_spin.setRange(1, 99)
        self.capacity_spin.setValue(int(self._table.get("capacity", 2) or 2))
        self.capacity_spin.setStyleSheet(self._field_qss())
        self.capacity_spin.setFixedHeight(40)
        form.addRow(self._lbl("Вместимость"), self.capacity_spin)

        self.zone_combo = QComboBox()
        for z in self._zones:
            self.zone_combo.addItem(z["name"], int(z["id"]))
        cur_zone = self._table.get("zone") or self._default_zone
        if cur_zone is not None:
            for i in range(self.zone_combo.count()):
                if self.zone_combo.itemData(i) == int(cur_zone):
                    self.zone_combo.setCurrentIndex(i)
                    break
        self.zone_combo.setStyleSheet(self._field_qss())
        self.zone_combo.setFixedHeight(40)
        self.zone_combo.currentIndexChanged.connect(self._on_zone_changed)
        form.addRow(self._lbl("Зона"), self.zone_combo)
        # Подсказка: «Свободные: 1, 3, 5» (зелёным).
        self._number_hint = QLabel("")
        self._number_hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        form.addRow("", self._number_hint)
        # Загрузим занятые номера для текущей зоны при старте.
        self._refresh_taken_numbers()

        self.waiter_combo = QComboBox()
        self.waiter_combo.addItem("Не назначен", None)
        self.waiter_combo.setStyleSheet(self._field_qss())
        self.waiter_combo.setFixedHeight(40)
        form.addRow(self._lbl("Официант"), self.waiter_combo)

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

    def _load_waiters(self) -> None:
        """Загружаем список официантов ресторана (sync, диалог модальный)."""
        try:
            data = self._client.get("/users/", params={"role": "waiter"})
        except ApiError:
            return
        users = data if isinstance(data, list) else (data or {}).get("data", [])
        self._waiters = [u for u in users if u.get("role") == "waiter"]
        current = self._table.get("waiter")
        for u in self._waiters:
            self.waiter_combo.addItem(
                u.get("full_name") or u.get("username", "?"),
                int(u["id"]),
            )
        if current:
            for i in range(self.waiter_combo.count()):
                if self.waiter_combo.itemData(i) == int(current):
                    self.waiter_combo.setCurrentIndex(i)
                    break

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QSpinBox, QComboBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{"
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

    def _on_zone_changed(self, _idx: int) -> None:
        """При смене зоны — обновить занятые номера + auto-fill следующий свободный."""
        self._refresh_taken_numbers(auto_fill=True)

    def _on_number_changed(self, value: int) -> None:
        """Inline-проверка: если набранный номер занят — показываем warning."""
        # Исключаем себя при редактировании.
        own_number = int(self._table.get("number") or 0) if self._table.get("id") else None
        if value in self._taken_numbers and value != own_number:
            zname = self.zone_combo.currentText() or "выбранной зоне"
            self._number_warning.setText(
                f"⚠ Стол №{value} уже есть в «{zname}»"
            )
            self._number_warning.setVisible(True)
        else:
            self._number_warning.clear()
            self._number_warning.setVisible(False)

    def _refresh_taken_numbers(self, *, auto_fill: bool = False) -> None:
        """Тянем /tables/next_number/?zone=X → set занятых + (опционально) ставим
        номер в next-free.

        auto_fill=True при смене зоны для new (но НЕ для edit — там номер уже есть).
        """
        zone_id = self.zone_combo.currentData()
        if zone_id is None:
            return
        try:
            data = self._client.get(
                "/tables/next_number/", params={"zone": int(zone_id)},
            )
        except ApiError:
            return
        # `data` уже распакован http_client'ом (это содержимое `data` поля).
        payload = data if isinstance(data, dict) else {}
        taken = payload.get("taken") or []
        next_free = payload.get("next") or 1
        self._taken_numbers = {int(n) for n in taken}
        # Hint строкой: первые 5 занятых + next-free.
        if self._taken_numbers:
            sample = sorted(self._taken_numbers)[:5]
            extra = f", … (+{len(self._taken_numbers) - 5})" if len(self._taken_numbers) > 5 else ""
            self._number_hint.setText(
                f"Занято: {', '.join(str(n) for n in sample)}{extra}. Свободный: {next_free}"
            )
        else:
            self._number_hint.setText(f"Свободный: {next_free}")
        # Auto-fill только для нового стола И только при смене зоны.
        if auto_fill and not self._table.get("id"):
            self.number_spin.blockSignals(True)
            self.number_spin.setValue(int(next_free))
            self.number_spin.blockSignals(False)
        # Re-check текущее значение
        self._on_number_changed(int(self.number_spin.value()))

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        if self.zone_combo.currentData() is None:
            QMessageBox.warning(self, "Ошибка", "Выберите зону")
            return
        # Inline-проверка занятого номера (бэк всё равно проверит).
        own_number = int(self._table.get("number") or 0) if self._table.get("id") else None
        num = int(self.number_spin.value())
        if num in self._taken_numbers and num != own_number:
            zname = self.zone_combo.currentText() or "выбранной зоне"
            QMessageBox.warning(
                self, "Конфликт номера",
                f"Стол №{num} уже есть в «{zname}». Выберите другой номер.",
            )
            return
        body = {
            "name": name,
            "number": num,
            "capacity": int(self.capacity_spin.value()),
            "zone": int(self.zone_combo.currentData()),
        }
        wid = self.waiter_combo.currentData()
        body["waiter"] = int(wid) if wid else None
        try:
            if self._table.get("id"):
                self._client.request(
                    "PATCH", f"/tables/{self._table['id']}/",
                    json=body, idempotent=True,
                )
            else:
                self._client.request(
                    "POST", "/tables/", json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка сохранения",
                f"[{e.code}] {e.message}",
            )
            return
        self.accept()
