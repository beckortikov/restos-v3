"""Список групп модификаторов с CRUD-кнопками. Открывается из MenuSection.

Каждая строка: name, чип количества опций, чип «обязательная», edit/delete.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _LoadWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/menu/modifier-groups/")
            groups = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(groups))
        except ApiError as e:
            self.error.emit(e)


class _DeleteWorker(QObject):
    success = Signal(int)
    error = Signal(int, object)

    def __init__(self, client: ApiClient, group_id: int) -> None:
        super().__init__()
        self.client = client
        self.group_id = group_id

    def run(self) -> None:
        try:
            self.client.request(
                "DELETE", f"/menu/modifier-groups/{self.group_id}/",
                idempotent=True,
            )
            self.success.emit(self.group_id)
        except ApiError as e:
            self.error.emit(self.group_id, e)


class ModifierGroupsDialog(QDialog):
    def __init__(
        self, client: ApiClient, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._groups: list[dict] = []
        self._threads: list[QThread] = []

        self.setWindowTitle("Модификаторы блюд")
        self.setModal(True)
        self.setMinimumSize(640, 560)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()
        self.reload()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["md"])

        head = QHBoxLayout()
        title = QLabel("Группы модификаторов")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 800;"
        )
        head.addWidget(title)
        head.addStretch(1)

        add_btn = QPushButton("+ Группа")
        add_btn.setFixedHeight(40)
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

        self._list_holder = QWidget()
        self._list_holder.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(SPACING["sm"])
        self._list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._list_holder)
        v.addWidget(scroll, 1)

        close = QPushButton("Закрыть")
        close.setFixedHeight(40)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        close.clicked.connect(self.accept)
        v.addWidget(close, alignment=Qt.AlignRight)

    # ---- load/render ----

    def reload(self) -> None:
        thread = QThread(self)
        worker = _LoadWorker(self._client)
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

    def _on_loaded(self, groups: list) -> None:
        self._groups = list(groups)
        self._render()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить группы: {exc.message}",
        )

    def _render(self) -> None:
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._groups:
            empty = QLabel("Нет групп. Нажмите «+ Группа» чтобы создать.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 11pt; padding: 32px 0; font-style: italic;"
            )
            self._list_layout.addWidget(empty)
            return

        for g in self._groups:
            self._list_layout.addWidget(self._build_row(g))

    def _build_row(self, group: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(8)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        name = QLabel(group.get("name", ""))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700; border: none;"
            f" background: transparent;"
        )
        col.addWidget(name)

        details = []
        cnt = len(group.get("modifiers") or [])
        details.append(f"Опций: {cnt}")
        if group.get("is_required"):
            details.append("обязательная")
        details.append(
            f"мин/макс {group.get('min_select', 0)}/{group.get('max_select', 1)}"
        )
        if not group.get("is_active", True):
            details.append("отключена")
        sub = QLabel(" • ".join(details))
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; border: none; background: transparent;"
        )
        col.addWidget(sub)
        h.addLayout(col, 1)

        edit = QPushButton("Изм.")
        edit.setFixedHeight(32)
        edit.setMinimumWidth(72)
        edit.setCursor(Qt.PointingHandCursor)
        edit.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px; padding: 0 12px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        edit.clicked.connect(lambda _c=False, g=group: self._on_edit(g))
        h.addWidget(edit)

        delete = QPushButton("Удалить")
        delete.setFixedHeight(32)
        delete.setMinimumWidth(80)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 6px; padding: 0 12px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: #B91C1C; }}"
        )
        delete.clicked.connect(lambda _c=False, g=group: self._on_delete(g))
        h.addWidget(delete)

        return row

    # ---- handlers ----

    def _on_add(self) -> None:
        from pos.screens.settings_sections.modifier_group_edit_dialog import (
            ModifierGroupEditDialog,
        )

        dlg = ModifierGroupEditDialog(self._client, group=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit(self, group: dict) -> None:
        from pos.screens.settings_sections.modifier_group_edit_dialog import (
            ModifierGroupEditDialog,
        )

        dlg = ModifierGroupEditDialog(self._client, group=group, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete(self, group: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить группу?",
            f"Группа «{group.get('name', '?')}» и её опции будут удалены.\n"
            "Удаление возможно только если группа не привязана к блюдам.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return

        thread = QThread(self)
        worker = _DeleteWorker(self._client, int(group["id"]))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_delete_success)
        worker.error.connect(self._on_delete_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_delete_success(self, _gid: int) -> None:
        self.reload()

    def _on_delete_error(self, _gid: int, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка удаления",
            f"[{exc.code}] {exc.message}",
        )
