"""Frame 20 — Настройки / Пользователи.

Содержимое:
- Header «Пользователи» + «+ Добавить пользователя» (orange)
- Список карточек пользователей: аватар-инициал / Полное имя+username /
  badge роли (Кассир/Официант) / [Сменить PIN] [Настроить] [Удалить]
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING

ROLE_LABELS = {"cashier": "Кассир", "waiter": "Официант"}
ROLE_BG = {"cashier": "#FED7AA", "waiter": "#DBEAFE"}
ROLE_FG = {"cashier": "#9A3412", "waiter": "#1E40AF"}


class _ListWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/users/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _ActionWorker(QObject):
    success = Signal(str, int, dict)
    error = Signal(str, int, object)

    def __init__(
        self,
        client: ApiClient,
        action: str,
        item_id: int,
        body: dict | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.action = action  # "delete" | "set_pin"
        self.item_id = item_id
        self.body = body or {}

    def run(self) -> None:
        try:
            if self.action == "delete":
                data = self.client.request(
                    "DELETE", f"/users/{self.item_id}/", idempotent=True
                )
            elif self.action == "set_pin":
                data = self.client.post(
                    f"/users/{self.item_id}/set_pin/",
                    json=self.body,
                    idempotent=True,
                )
            else:
                data = {}
            self.success.emit(self.action, self.item_id, data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(self.action, self.item_id, e)


class UsersSection(QWidget):
    """Frame 20. Внутри SettingsScreen QStackedWidget."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._threads: list[QThread] = []
        self._build()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"UsersSection {{ background: {COLORS['bg_light']}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Header
        head = QHBoxLayout()
        title = QLabel("Пользователи")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
        )
        head.addWidget(title)
        head.addStretch(1)

        add_btn = QPushButton("  + Добавить пользователя")
        add_btn.setFixedHeight(40)
        add_btn.setMinimumWidth(220)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        add_btn.clicked.connect(self._on_add)
        head.addWidget(add_btn)
        v.addLayout(head)

        # Scroll list
        self._list_holder = QWidget()
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(SPACING["md"])
        self._list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {COLORS['bg_light']}; border: none; }}")
        scroll.setWidget(self._list_holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)

        self._empty_label = QLabel("Пользователей ещё нет — добавьте первого")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 13pt; padding: 60px 0;"
            f" background: {COLORS['bg_white']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['md']}px;"
        )
        self._empty_label.setVisible(False)
        v.addWidget(self._empty_label)

    # -------- public --------

    def reload(self) -> None:
        thread = QThread(self)
        worker = _ListWorker(self._client)
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

    # -------- rendering --------

    def _on_loaded(self, items: list) -> None:
        self._items = sorted(
            list(items),
            key=lambda u: (u.get("role", ""), u.get("full_name", "")),
        )
        self._render()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось загрузить пользователей: {exc.message}"
        )
        self._items = []
        self._render()

    def _render(self) -> None:
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        self._empty_label.setVisible(not self._items)
        for user in self._items:
            self._list_layout.addWidget(self._build_card(user))

    def _build_card(self, user: dict) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        h = QHBoxLayout(card)
        h.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        h.setSpacing(SPACING["md"])

        # Аватар-кружок с инициалом
        full = user.get("full_name", "?").strip()
        initial = full[:1].upper() if full else "?"
        role = user.get("role", "")
        avatar = QLabel(initial)
        avatar.setFixedSize(44, 44)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {ROLE_BG.get(role, COLORS['bg_gray'])};"
            f" color: {ROLE_FG.get(role, COLORS['text_primary'])};"
            f" border: none;"
            f" border-radius: 22px;"
            f" font-size: 16pt; font-weight: 700;"
        )
        h.addWidget(avatar)

        # Текст
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(SPACING["sm"])
        name = QLabel(full or user.get("username", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        name_row.addWidget(name)

        if not user.get("is_active", True):
            inactive = QLabel("неактивен")
            inactive.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 9pt; font-weight: 600;"
                f" background: {COLORS['bg_gray']}; border: none;"
                f" padding: 2px 8px; border-radius: 4px;"
            )
            name_row.addWidget(inactive)

        if not user.get("has_pin") and role == "cashier":
            no_pin = QLabel("PIN не задан")
            no_pin.setStyleSheet(
                f"color: {COLORS['danger_red']}; font-size: 9pt; font-weight: 600;"
                f" background: #FEE2E2; border: none;"
                f" padding: 2px 8px; border-radius: 4px;"
            )
            name_row.addWidget(no_pin)

        name_row.addStretch(1)
        text_col.addLayout(name_row)

        sub = QLabel(f"@{user.get('username', '')}")
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(sub)
        h.addLayout(text_col, 1)

        # Role badge
        role_badge = QLabel(ROLE_LABELS.get(role, role))
        role_badge.setAlignment(Qt.AlignCenter)
        role_badge.setStyleSheet(
            f"background-color: {ROLE_BG.get(role, COLORS['bg_gray'])};"
            f" color: {ROLE_FG.get(role, COLORS['text_primary'])};"
            f" border: none; border-radius: 6px;"
            f" padding: 4px 12px;"
            f" font-size: 10pt; font-weight: 700;"
        )
        h.addWidget(role_badge)

        # Действия
        pin_btn = QPushButton("Сменить PIN")
        pin_btn.setFixedHeight(36)
        pin_btn.setMinimumWidth(120)
        pin_btn.setCursor(Qt.PointingHandCursor)
        pin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        pin_btn.clicked.connect(lambda _c=False, u=user: self._on_set_pin(u))
        h.addWidget(pin_btn)

        edit = QPushButton()
        edit.setIcon(qicon("edit-2", COLORS["text_secondary"], 18))
        edit.setIconSize(QSize(18, 18))
        edit.setFixedSize(36, 36)
        edit.setCursor(Qt.PointingHandCursor)
        edit.setToolTip("Настроить")
        edit.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        edit.clicked.connect(lambda _c=False, u=user: self._on_edit(u))
        h.addWidget(edit)

        delete = QPushButton()
        delete.setIcon(qicon("trash-2", COLORS["danger_red"], 18))
        delete.setIconSize(QSize(18, 18))
        delete.setFixedSize(36, 36)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip("Удалить")
        delete.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid #FECACA;"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
            f"QPushButton:hover {{ background: #FEE2E2; }}"
        )
        delete.clicked.connect(lambda _c=False, u=user: self._on_delete(u))
        h.addWidget(delete)
        return card

    # -------- handlers --------

    def _on_add(self) -> None:
        from pos.screens.settings_sections.user_edit_dialog import UserEditDialog

        dlg = UserEditDialog(client=self._client, user=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit(self, user: dict) -> None:
        from pos.screens.settings_sections.user_edit_dialog import UserEditDialog

        dlg = UserEditDialog(client=self._client, user=user, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_set_pin(self, user: dict) -> None:
        pin, ok = QInputDialog.getText(
            self,
            "Новый PIN",
            f"Введите новый PIN для «{user.get('full_name', '?')}» (4-6 цифр):",
            QLineEdit.Password,
        )
        if not ok:
            return
        pin = (pin or "").strip()
        if not pin.isdigit() or not (4 <= len(pin) <= 6):
            QMessageBox.warning(self, "Ошибка", "PIN должен быть 4-6 цифр")
            return
        self._spawn_action("set_pin", int(user["id"]), {"pin": pin})

    def _on_delete(self, user: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить пользователя?",
            f"Пользователь «{user.get('full_name', '?')}» будет удалён.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_action("delete", int(user["id"]))

    def _spawn_action(self, action: str, item_id: int, body: dict | None = None) -> None:
        thread = QThread(self)
        worker = _ActionWorker(self._client, action, item_id, body or {})
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_action_done)
        worker.error.connect(self._on_action_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_action_done(self, action: str, _item_id: int, _data: dict) -> None:
        if action == "set_pin":
            QMessageBox.information(self, "PIN изменён", "PIN успешно обновлён.")
            self.reload()
        elif action == "delete":
            self.reload()

    def _on_action_failed(self, action: str, _item_id: int, exc: ApiError) -> None:
        if action == "delete" and exc.code == "USER_SELF_DELETE":
            msg = "Нельзя удалить самого себя."
        elif action == "delete":
            msg = f"Не удалось удалить: {exc.message}"
        elif action == "set_pin":
            msg = f"Не удалось изменить PIN: {exc.message}"
        else:
            msg = exc.message
        QMessageBox.warning(self, "Ошибка", msg)
