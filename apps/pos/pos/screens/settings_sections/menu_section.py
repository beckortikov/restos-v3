"""Frame 19 — Настройки / Меню и категории.

Layout:
- Header: «Меню и категории» + [+ Категория] [+ Блюдо]
- Body: split — слева список категорий (узкий), справа список блюд выбранной категории.

Все мутации через ApiClient в QThread (_LoadWorker / _ActionWorker).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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


class _LoadWorker(QObject):
    """Грузит и категории, и блюда параллельно (одним workerом — два GET)."""

    success = Signal(list, list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            cats_raw = self.client.get("/menu/categories/")
            cats = cats_raw if isinstance(cats_raw, list) else (cats_raw or {}).get("data", [])
            items_raw = self.client.get("/menu/items/")
            items = items_raw if isinstance(items_raw, list) else (items_raw or {}).get("data", [])
            self.success.emit(list(cats), list(items))
        except ApiError as e:
            self.error.emit(e)


class _ImportXlsxWorker(QObject):
    """Загружает XLSX-файл на /menu/items/import_xlsx/."""

    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, filename: str, content: bytes) -> None:
        super().__init__()
        self.client = client
        self.filename = filename
        self.content = content

    def run(self) -> None:
        try:
            data = self.client.post_file(
                "/menu/items/import_xlsx/",
                field="file",
                filename=self.filename,
                content=self.content,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class _ActionWorker(QObject):
    success = Signal(str, int, dict)
    error = Signal(str, int, object)

    def __init__(self, client: ApiClient, action: str, kind: str, item_id: int) -> None:
        super().__init__()
        self.client = client
        self.action = action  # "delete" | "toggle"
        self.kind = kind  # "category" | "item"
        self.item_id = item_id

    def run(self) -> None:
        try:
            base = "categories" if self.kind == "category" else "items"
            if self.action == "delete":
                data = self.client.request(
                    "DELETE", f"/menu/{base}/{self.item_id}/", idempotent=True
                )
            elif self.action == "toggle":
                data = self.client.post(
                    f"/menu/items/{self.item_id}/toggle_available/",
                    json={},
                    idempotent=True,
                )
            else:
                data = {}
            self.success.emit(self.action, self.item_id, data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(self.action, self.item_id, e)


class MenuSection(QWidget):
    """Frame 19. Внутри SettingsScreen QStackedWidget."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._categories: list[dict] = []
        self._items: list[dict] = []
        self._active_cat_id: int | None = None
        self._threads: list[QThread] = []
        self._build()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"MenuSection {{ background: {COLORS['bg_light']}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Header
        head = QHBoxLayout()
        title = QLabel("Меню и категории")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
        )
        head.addWidget(title)
        head.addStretch(1)

        tpl_btn = self._make_top_btn("⬇ Шаблон XLSX", primary=False)
        tpl_btn.clicked.connect(self._on_download_template)
        head.addWidget(tpl_btn)

        import_btn = self._make_top_btn("⬆ Импорт XLSX", primary=False)
        import_btn.clicked.connect(self._on_import_xlsx)
        head.addWidget(import_btn)

        mods_btn = self._make_top_btn("Модификаторы", primary=False)
        mods_btn.clicked.connect(self._on_modifier_groups)
        head.addWidget(mods_btn)

        add_cat = self._make_top_btn("+ Категория", primary=False)
        add_cat.clicked.connect(self._on_add_category)
        head.addWidget(add_cat)

        add_item = self._make_top_btn("+ Блюдо", primary=True)
        add_item.clicked.connect(self._on_add_item)
        head.addWidget(add_item)
        v.addLayout(head)

        # Body — split
        body = QHBoxLayout()
        body.setSpacing(SPACING["lg"])

        # Categories pane (260)
        self._cats_pane = self._build_cats_pane()
        body.addWidget(self._cats_pane)

        # Items pane (rest)
        self._items_pane = self._build_items_pane()
        body.addWidget(self._items_pane, 1)

        v.addLayout(body, 1)

    def _make_top_btn(self, label: str, *, primary: bool) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(40)
        btn.setMinimumWidth(160)
        btn.setCursor(Qt.PointingHandCursor)
        if primary:
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #EA5E0C; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 18px; font-size: 12pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
        return btn

    def _build_cats_pane(self) -> QWidget:
        pane = QFrame()
        pane.setFixedWidth(260)
        pane.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QLabel("Категории")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" padding: 16px; border: none;"
        )
        v.addWidget(head)

        self._cats_holder = QWidget()
        self._cats_holder.setStyleSheet("background: transparent;")
        self._cats_layout = QVBoxLayout(self._cats_holder)
        self._cats_layout.setContentsMargins(8, 0, 8, 12)
        self._cats_layout.setSpacing(4)
        self._cats_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._cats_holder)
        v.addWidget(scroll, 1)
        return pane

    def _build_items_pane(self) -> QWidget:
        pane = QFrame()
        pane.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._items_head = QLabel("Блюда")
        self._items_head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" padding: 16px; border: none;"
        )
        v.addWidget(self._items_head)

        self._items_holder = QWidget()
        self._items_holder.setStyleSheet("background: transparent;")
        self._items_layout = QVBoxLayout(self._items_holder)
        self._items_layout.setContentsMargins(16, 0, 16, 16)
        self._items_layout.setSpacing(8)
        self._items_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._items_holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)
        return pane

    # -------- public --------

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

    # -------- list rendering --------

    def _on_loaded(self, cats: list, items: list) -> None:
        self._categories = sorted(
            list(cats),
            key=lambda c: (int(c.get("sort_order", 0)), c.get("name", "")),
        )
        self._items = sorted(
            list(items),
            key=lambda i: (
                int(i.get("category", 0)),
                int(i.get("sort_order", 0)),
                i.get("name", ""),
            ),
        )
        if self._active_cat_id is None and self._categories:
            self._active_cat_id = int(self._categories[0]["id"])
        self._render_cats()
        self._render_items()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить меню: {exc.message}")
        self._categories = []
        self._items = []
        self._render_cats()
        self._render_items()

    def _render_cats(self) -> None:
        while self._cats_layout.count():
            child = self._cats_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._categories:
            empty = QLabel("Нет категорий")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
                f" padding: 24px 0; border: none;"
            )
            self._cats_layout.addWidget(empty)
            return

        for cat in self._categories:
            self._cats_layout.addWidget(self._build_cat_row(cat))

    def _build_cat_row(self, cat: dict) -> QWidget:
        row = QFrame()
        is_active = (self._active_cat_id == int(cat["id"]))
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_gray'] if is_active else 'transparent'};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  border: none;"
            f"}}"
            f"QFrame:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 8, 8)
        h.setSpacing(SPACING["sm"])

        name_btn = QPushButton(cat.get("name", "?"))
        name_btn.setCursor(Qt.PointingHandCursor)
        name_btn.setFlat(True)
        name_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; border: none;"
            f"  color: {COLORS['accent_orange'] if is_active else COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"  font-weight: {700 if is_active else 500};"
            f"  text-align: left; padding: 0;"
            f"}}"
        )
        name_btn.clicked.connect(
            lambda _c=False, cid=int(cat["id"]): self._select_category(cid)
        )
        h.addWidget(name_btn, 1)

        edit = self._mini_btn("edit-2", COLORS["text_secondary"])
        edit.setToolTip("Редактировать")
        edit.clicked.connect(lambda _c=False, cc=cat: self._on_edit_category(cc))
        h.addWidget(edit)

        delete = self._mini_btn("trash-2", COLORS["danger_red"])
        delete.setToolTip("Удалить")
        delete.clicked.connect(lambda _c=False, cc=cat: self._on_delete_category(cc))
        h.addWidget(delete)
        return row

    def _mini_btn(self, icon_name: str, color: str) -> QPushButton:
        btn = QPushButton()
        btn.setIcon(qicon(icon_name, color, 16))
        btn.setIconSize(QSize(16, 16))
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 4px; }"
            f"QPushButton:hover {{ background: {COLORS['border_light']}; }}"
        )
        return btn

    def _select_category(self, cid: int) -> None:
        if self._active_cat_id == cid:
            return
        self._active_cat_id = cid
        self._render_cats()
        self._render_items()

    def _render_items(self) -> None:
        while self._items_layout.count():
            child = self._items_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        cur_cat_name = ""
        if self._active_cat_id is not None:
            for c in self._categories:
                if int(c["id"]) == self._active_cat_id:
                    cur_cat_name = c.get("name", "")
                    break
        self._items_head.setText(
            f"Блюда — {cur_cat_name}" if cur_cat_name else "Блюда"
        )

        filtered = [
            i for i in self._items
            if self._active_cat_id is not None
            and int(i.get("category", 0)) == self._active_cat_id
        ]
        if not filtered:
            empty = QLabel("В этой категории нет блюд")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt;"
                f" padding: 60px 0; border: none;"
            )
            self._items_layout.addWidget(empty)
            return

        for item in filtered:
            self._items_layout.addWidget(self._build_item_row(item))

    def _build_item_row(self, item: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(SPACING["md"])

        emoji = item.get("emoji") or "🍽"
        elbl = QLabel(emoji)
        elbl.setStyleSheet(
            "font-size: 18pt; border: none; background: transparent;"
        )
        elbl.setFixedWidth(32)
        h.addWidget(elbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(item.get("name", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(name)
        sub = QLabel(f"{item.get('price', '0.00')} TJS")
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(sub)
        h.addLayout(text_col, 1)

        # Toggle is_available
        is_avail = bool(item.get("is_available", True))
        toggle = QPushButton("В меню" if is_avail else "В стопе")
        toggle.setFixedHeight(28)
        toggle.setMinimumWidth(90)
        toggle.setCursor(Qt.PointingHandCursor)
        if is_avail:
            toggle.setStyleSheet(
                f"QPushButton {{"
                f"  background: #DCFCE7; color: {COLORS['success_green']};"
                f"  border: 1px solid {COLORS['success_green']};"
                f"  border-radius: 6px; padding: 0 10px;"
                f"  font-size: 10pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #BBF7D0; }}"
            )
        else:
            toggle.setStyleSheet(
                f"QPushButton {{"
                f"  background: #FEE2E2; color: {COLORS['danger_red']};"
                f"  border: 1px solid {COLORS['danger_red']};"
                f"  border-radius: 6px; padding: 0 10px;"
                f"  font-size: 10pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #FECACA; }}"
            )
        toggle.clicked.connect(
            lambda _c=False, iid=int(item["id"]): self._spawn_action("toggle", "item", iid)
        )
        h.addWidget(toggle)

        edit = self._mini_btn("edit-2", COLORS["text_secondary"])
        edit.setToolTip("Редактировать")
        edit.clicked.connect(lambda _c=False, it=item: self._on_edit_item(it))
        h.addWidget(edit)

        delete = self._mini_btn("trash-2", COLORS["danger_red"])
        delete.setToolTip("Удалить")
        delete.clicked.connect(lambda _c=False, it=item: self._on_delete_item(it))
        h.addWidget(delete)
        return row

    # -------- handlers --------

    def _on_modifier_groups(self) -> None:
        from pos.screens.settings_sections.modifier_groups_dialog import (
            ModifierGroupsDialog,
        )

        dlg = ModifierGroupsDialog(self._client, parent=self)
        dlg.exec()

    def _on_download_template(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить шаблон меню", "menu_template.xlsx", "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            content = self._client.get_raw("/menu/items/template/")
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        with open(path, "wb") as f:
            f.write(content)
        QMessageBox.information(self, "Готово", f"Шаблон сохранён: {path}")

    def _on_import_xlsx(self) -> None:
        path, _flt = QFileDialog.getOpenFileName(
            self,
            "Импорт меню из XLSX",
            "",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                content = f.read()
        except OSError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать файл: {e}")
            return
        filename = path.rsplit("/", 1)[-1]

        thread = QThread(self)
        worker = _ImportXlsxWorker(self._client, filename, content)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_import_success)
        worker.error.connect(self._on_import_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_import_success(self, summary: dict) -> None:
        created = summary.get("created", 0)
        updated = summary.get("updated", 0)
        errors = summary.get("errors") or []
        msg = f"Создано: {created}\nОбновлено: {updated}"
        if errors:
            shown = "\n".join(str(e) for e in errors[:5])
            more = f"\n…ещё {len(errors) - 5}" if len(errors) > 5 else ""
            msg += f"\n\nОшибок: {len(errors)}\n{shown}{more}"
        QMessageBox.information(self, "Импорт завершён", msg)
        self.reload()

    def _on_import_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка импорта",
            f"[{exc.code}] {exc.message}",
        )

    def _on_add_category(self) -> None:
        from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

        dlg = CategoryEditDialog(client=self._client, category=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit_category(self, cat: dict) -> None:
        from pos.screens.settings_sections.category_edit_dialog import CategoryEditDialog

        dlg = CategoryEditDialog(client=self._client, category=cat, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete_category(self, cat: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить категорию?",
            f"Категория «{cat.get('name', '?')}» будет удалена.\n"
            "Удаление возможно только если в ней нет блюд.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_action("delete", "category", int(cat["id"]))

    def _on_add_item(self) -> None:
        if not self._categories:
            QMessageBox.information(
                self, "Нет категорий",
                "Сначала добавьте хотя бы одну категорию.",
            )
            return
        from pos.screens.settings_sections.item_edit_dialog import ItemEditDialog

        dlg = ItemEditDialog(
            client=self._client,
            categories=self._categories,
            item=None,
            default_category_id=self._active_cat_id,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit_item(self, item: dict) -> None:
        from pos.screens.settings_sections.item_edit_dialog import ItemEditDialog

        dlg = ItemEditDialog(
            client=self._client,
            categories=self._categories,
            item=item,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete_item(self, item: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить блюдо?",
            f"Блюдо «{item.get('name', '?')}» будет удалено. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_action("delete", "item", int(item["id"]))

    def _spawn_action(self, action: str, kind: str, item_id: int) -> None:
        thread = QThread(self)
        worker = _ActionWorker(self._client, action, kind, item_id)
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

    def _on_action_done(self, _action: str, _item_id: int, _data: dict) -> None:
        self.reload()

    def _on_action_failed(self, action: str, _item_id: int, exc: ApiError) -> None:
        if action == "delete" and exc.http_status == 409:
            msg = "Удаление невозможно: используется в заказах или категория не пуста."
        elif action == "delete":
            msg = f"Не удалось удалить: {exc.message}"
        else:
            msg = f"Не удалось обновить: {exc.message}"
        QMessageBox.warning(self, "Ошибка", msg)
