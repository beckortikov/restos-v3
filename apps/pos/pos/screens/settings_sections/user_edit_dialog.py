"""Модалка create/edit для User — used from UsersSection (frame 20).

Поля:
- Username (только для create — после нельзя переименовать)
- Полное имя (full_name)
- Роль (cashier / waiter)
- Активен (is_active)
- PIN (4-6 цифр) — обязателен при создании кассира; для официанта необязательно;
  для редактирования — необязателен (если пусто, не меняем).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING

ROLE_CHOICES = [
    ("cashier", "Кассир"),
    ("waiter", "Официант"),
    ("cook", "Повар"),
]


class UserEditDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        user: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._user = user or {}
        self.saved_data: dict | None = None

        self.setWindowTitle("Пользователь")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        outer.setSpacing(SPACING["lg"])

        title = QLabel("Редактировать пользователя" if self._user else "Добавить пользователя")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )
        outer.addWidget(title)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.username_edit = QLineEdit(self._user.get("username", ""))
        self.username_edit.setPlaceholderText("anna")
        self.username_edit.setStyleSheet(self._field_qss())
        if self._user:  # username read-only при edit (логин не меняется)
            self.username_edit.setReadOnly(True)
            self.username_edit.setStyleSheet(
                self._field_qss() + f" QLineEdit {{ background: {COLORS['bg_gray']}; }}"
            )
        form.addRow(self._lbl("Логин"), self.username_edit)

        self.fullname_edit = QLineEdit(self._user.get("full_name", ""))
        self.fullname_edit.setPlaceholderText("Анна Иванова")
        self.fullname_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("Полное имя"), self.fullname_edit)

        self.role_combo = QComboBox()
        for key, label in ROLE_CHOICES:
            self.role_combo.addItem(label, key)
        cur = self._user.get("role", "cashier")
        for i, (k, _) in enumerate(ROLE_CHOICES):
            if k == cur:
                self.role_combo.setCurrentIndex(i)
                break
        self.role_combo.setStyleSheet(self._field_qss())
        self.role_combo.setFixedHeight(40)
        self.role_combo.currentIndexChanged.connect(self._on_role_changed)
        form.addRow(self._lbl("Роль"), self.role_combo)

        # Кухонная станция — только для роли cook. Загружаем все активные.
        self.station_combo = QComboBox()
        self.station_combo.addItem("— Все цеха —", None)
        try:
            stations = self._client.get(
                "/printing/stations/", params={"is_active": "true"},
            )
            station_list = (
                stations.get("data", []) if isinstance(stations, dict)
                else (stations or [])
            )
        except ApiError:
            station_list = []
        for s in station_list:
            self.station_combo.addItem(s.get("name", "?"), int(s["id"]))
        cur_station = self._user.get("kitchen_station")
        if cur_station:
            for i in range(self.station_combo.count()):
                if self.station_combo.itemData(i) == int(cur_station):
                    self.station_combo.setCurrentIndex(i)
                    break
        self.station_combo.setStyleSheet(self._field_qss())
        self.station_combo.setFixedHeight(40)
        self._station_label = self._lbl("Цех (KDS)")
        form.addRow(self._station_label, self.station_combo)
        # Hide if not cook
        self._update_station_visibility(cur)

        self.pin_edit = QLineEdit()
        self.pin_edit.setPlaceholderText(
            "Оставьте пустым, чтобы не менять" if self._user else "4-6 цифр"
        )
        self.pin_edit.setMaxLength(6)
        self.pin_edit.setEchoMode(QLineEdit.Password)
        self.pin_edit.setStyleSheet(self._field_qss())
        form.addRow(self._lbl("PIN"), self.pin_edit)

        outer.addLayout(form)

        self.active_cb = QCheckBox("Активен")
        self.active_cb.setChecked(bool(self._user.get("is_active", True)))
        self.active_cb.setStyleSheet(
            f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 12pt; }}"
        )
        outer.addWidget(self.active_cb)

        note = QLabel(
            "PIN-логин в POS работает для ролей «Кассир» и «Повар».\n"
            "Официанты входят через логин/пароль в waiter PWA."
        )
        note.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        outer.addStretch(1)

        # Footer
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
            f"QLineEdit, QComboBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus {{"
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
        username = self.username_edit.text().strip()
        full_name = self.fullname_edit.text().strip()
        pin = self.pin_edit.text().strip()
        is_create = not self._user

        if not username:
            QMessageBox.warning(self, "Ошибка", "Логин обязателен")
            return
        if not full_name:
            QMessageBox.warning(self, "Ошибка", "Полное имя обязательно")
            return
        if pin and (not pin.isdigit() or not (4 <= len(pin) <= 6)):
            QMessageBox.warning(self, "Ошибка", "PIN должен быть 4-6 цифр")
            return

        role = self.role_combo.currentData()
        body: dict = {
            "full_name": full_name,
            "role": role,
            "is_active": self.active_cb.isChecked(),
        }
        if is_create:
            body["username"] = username
        if pin:
            body["pin"] = pin
        # Кухонная станция — только для cook (для других ролей всегда null).
        if role == "cook":
            body["kitchen_station"] = self.station_combo.currentData()
        else:
            body["kitchen_station"] = None

        try:
            if self._user.get("id"):
                data = self._client.request(
                    "PATCH",
                    f"/users/{self._user['id']}/",
                    json=body,
                    idempotent=True,
                )
            else:
                data = self._client.request(
                    "POST", "/users/", json=body, idempotent=True
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e.message}")
            return
        self.saved_data = data if isinstance(data, dict) else body
        self.accept()

    # -------- helpers --------

    def _on_role_changed(self, _idx: int) -> None:
        role = self.role_combo.currentData()
        self._update_station_visibility(role)

    def _update_station_visibility(self, role: str) -> None:
        is_cook = (role == "cook")
        if hasattr(self, "station_combo"):
            self.station_combo.setVisible(is_cook)
            self._station_label.setVisible(is_cook)
