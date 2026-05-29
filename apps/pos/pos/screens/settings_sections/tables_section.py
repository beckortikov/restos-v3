"""Settings → «Зоны и столы».

Split-layout: слева список зон, справа список столов выбранной зоны.
Шапка: «+ Зона», «+ Стол». Кнопки в каждой строке — Редактировать / Удалить.

API:
- GET/POST/PATCH/DELETE /tables/zones/
- GET/POST/PATCH/DELETE /tables/  (TableViewSet)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
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
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _LoadWorker(QObject):
    success = Signal(list, list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            zr = self.client.get("/tables/zones/")
            zones = zr if isinstance(zr, list) else (zr or {}).get("data", [])
            tr = self.client.get("/tables/")
            tables = tr if isinstance(tr, list) else (tr or {}).get("data", [])
            self.success.emit(list(zones), list(tables))
        except ApiError as e:
            self.error.emit(e)


class _DeleteWorker(QObject):
    success = Signal(str, int)
    error = Signal(str, int, object)

    def __init__(self, client: ApiClient, kind: str, obj_id: int) -> None:
        super().__init__()
        self.client = client
        self.kind = kind  # "zone" | "table"
        self.obj_id = obj_id

    def run(self) -> None:
        path = (
            f"/tables/zones/{self.obj_id}/" if self.kind == "zone"
            else f"/tables/{self.obj_id}/"
        )
        try:
            self.client.request("DELETE", path, idempotent=True)
            self.success.emit(self.kind, self.obj_id)
        except ApiError as e:
            self.error.emit(self.kind, self.obj_id, e)


class TablesSection(QWidget):
    """Управление зонами и столами зала."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._zones: list[dict] = []
        self._tables: list[dict] = []
        self._active_zone_id: int | None = None
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"TablesSection {{ background: {COLORS['bg_light']}; }}"
        )
        self._build()

    # -------- build --------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        head = QHBoxLayout()
        title = QLabel("Зоны и столы")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        head.addWidget(title)
        head.addStretch(1)

        add_zone = self._make_top_btn("+ Зона", primary=False)
        add_zone.clicked.connect(self._on_add_zone)
        head.addWidget(add_zone)

        add_table = self._make_top_btn("+ Стол", primary=True)
        add_table.clicked.connect(self._on_add_table)
        head.addWidget(add_table)
        v.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(SPACING["lg"])

        self._zones_pane = self._build_zones_pane()
        body.addWidget(self._zones_pane)
        self._tables_pane = self._build_tables_pane()
        body.addWidget(self._tables_pane, 1)
        v.addLayout(body, 1)

    def _make_top_btn(self, label: str, *, primary: bool) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(40)
        btn.setMinimumWidth(140)
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

    def _build_zones_pane(self) -> QWidget:
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

        head = QLabel("Зоны")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" padding: 16px; border: none;"
        )
        v.addWidget(head)

        self._zones_holder = QWidget()
        self._zones_holder.setStyleSheet("background: transparent;")
        self._zones_layout = QVBoxLayout(self._zones_holder)
        self._zones_layout.setContentsMargins(8, 0, 8, 12)
        self._zones_layout.setSpacing(4)
        self._zones_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._zones_holder)
        v.addWidget(scroll, 1)
        return pane

    def _build_tables_pane(self) -> QWidget:
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

        self._tables_head = QLabel("Столы")
        self._tables_head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700;"
            f" padding: 16px; border: none;"
        )
        v.addWidget(self._tables_head)

        self._tables_holder = QWidget()
        self._tables_holder.setStyleSheet("background: transparent;")
        self._tables_layout = QVBoxLayout(self._tables_holder)
        self._tables_layout.setContentsMargins(16, 0, 16, 16)
        self._tables_layout.setSpacing(8)
        self._tables_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._tables_holder)
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

    # -------- rendering --------

    def _on_loaded(self, zones: list, tables: list) -> None:
        self._zones = sorted(
            zones, key=lambda z: (int(z.get("sort_order", 0)), z.get("name", "")),
        )
        self._tables = sorted(
            tables, key=lambda t: int(t.get("number", 0)),
        )
        if self._active_zone_id is None and self._zones:
            self._active_zone_id = int(self._zones[0]["id"])
        self._render_zones()
        self._render_tables()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось загрузить зоны/столы: {exc.message}",
        )
        self._zones, self._tables = [], []
        self._render_zones()
        self._render_tables()

    def _render_zones(self) -> None:
        while self._zones_layout.count():
            child = self._zones_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._zones:
            empty = QLabel("Нет зон")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 11pt; padding: 24px 0; border: none;"
            )
            self._zones_layout.addWidget(empty)
            return
        for z in self._zones:
            self._zones_layout.addWidget(self._build_zone_row(z))

    def _build_zone_row(self, zone: dict) -> QWidget:
        zid = int(zone["id"])
        active = zid == self._active_zone_id
        row = QFrame()
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light'] if active else COLORS['bg_white']};"
            f"  border: 1px solid "
            f"{COLORS['accent_orange'] if active else COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"}}"
            f"QFrame:hover {{ border: 1px solid {COLORS['accent_orange']}; }}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(6)

        name = QLabel(zone.get("name", ""))
        name.setStyleSheet(
            f"color: "
            f"{COLORS['accent_orange'] if active else COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: "
            f"{'700' if active else '600'};"
            f" border: none; background: transparent;"
        )
        name.mousePressEvent = lambda _e, zi=zid: self._select_zone(zi)
        h.addWidget(name, 1)

        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(28, 28)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setToolTip("Редактировать")
        edit_btn.setStyleSheet(self._mini_btn_qss())
        edit_btn.clicked.connect(lambda _c=False, z=zone: self._on_edit_zone(z))
        h.addWidget(edit_btn)

        del_btn = QPushButton("×")
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setToolTip("Удалить")
        del_btn.setStyleSheet(self._mini_btn_qss(danger=True))
        del_btn.clicked.connect(lambda _c=False, z=zone: self._on_delete_zone(z))
        h.addWidget(del_btn)
        return row

    def _render_tables(self) -> None:
        while self._tables_layout.count():
            child = self._tables_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        zone_name = next(
            (z["name"] for z in self._zones if int(z["id"]) == self._active_zone_id),
            "Все",
        )
        items = [
            t for t in self._tables
            if self._active_zone_id is None or int(t.get("zone", 0)) == self._active_zone_id
        ]
        self._tables_head.setText(f"Столы — {zone_name} ({len(items)})")

        if not items:
            empty = QLabel("В этой зоне нет столов")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 11pt; font-style: italic;"
                f" padding: 32px 0; border: none;"
            )
            self._tables_layout.addWidget(empty)
            return
        for t in items:
            self._tables_layout.addWidget(self._build_table_row(t))

    def _build_table_row(self, table: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)

        # Номер чип
        num = QLabel(f"№{table.get('number', '?')}")
        num.setFixedWidth(50)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet(
            f"color: {COLORS['accent_orange']};"
            f" background: #FFF7ED;"
            f" border: 1px solid {COLORS['accent_orange']};"
            f" border-radius: 6px;"
            f" font-size: 11pt; font-weight: 700; padding: 4px 0;"
        )
        h.addWidget(num)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(table.get("name", ""))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        info.addWidget(name)

        sub_parts = [
            f"Мест: {table.get('capacity', '?')}",
            f"Статус: {self._status_label(table.get('status'))}",
        ]
        if table.get("waiter_name"):
            sub_parts.append(f"Официант: {table['waiter_name']}")
        sub = QLabel(" • ".join(sub_parts))
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        info.addWidget(sub)
        h.addLayout(info, 1)

        edit_btn = QPushButton("Изм.")
        edit_btn.setFixedHeight(30)
        edit_btn.setMinimumWidth(70)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setStyleSheet(self._row_btn_qss())
        edit_btn.clicked.connect(lambda _c=False, t=table: self._on_edit_table(t))
        h.addWidget(edit_btn)

        del_btn = QPushButton("Удалить")
        del_btn.setFixedHeight(30)
        del_btn.setMinimumWidth(80)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet(self._row_btn_qss(danger=True))
        del_btn.clicked.connect(lambda _c=False, t=table: self._on_delete_table(t))
        h.addWidget(del_btn)
        return row

    @staticmethod
    def _status_label(status: str | None) -> str:
        return {
            "free": "свободен", "occupied": "занят",
            "bill_requested": "счёт", "merged": "объединён",
        }.get(status or "", status or "—")

    def _mini_btn_qss(self, *, danger: bool = False) -> str:
        c_text = COLORS["danger_red"] if danger else COLORS["text_secondary"]
        c_hover_bg = "#FEF2F2" if danger else COLORS["bg_gray"]
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {c_text}; font-size: 13pt; font-weight: 700;"
            f"  border: none; border-radius: 4px;"
            f"}}"
            f"QPushButton:hover {{ background: {c_hover_bg}; }}"
        )

    def _row_btn_qss(self, *, danger: bool = False) -> str:
        if danger:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['danger_red']}; color: white;"
                f"  border: none; border-radius: 6px;"
                f"  padding: 0 12px; font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: #B91C1C; }}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"  padding: 0 12px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    # -------- handlers --------

    def _select_zone(self, zone_id: int) -> None:
        self._active_zone_id = zone_id
        self._render_zones()
        self._render_tables()

    def _on_add_zone(self) -> None:
        from pos.screens.settings_sections.zone_edit_dialog import ZoneEditDialog

        dlg = ZoneEditDialog(client=self._client, zone=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit_zone(self, zone: dict) -> None:
        from pos.screens.settings_sections.zone_edit_dialog import ZoneEditDialog

        dlg = ZoneEditDialog(client=self._client, zone=zone, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete_zone(self, zone: dict) -> None:
        ans = QMessageBox.question(
            self, "Удалить зону?",
            f"Зона «{zone.get('name', '?')}» будет удалена.\n"
            "Удаление возможно только если в ней нет столов.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_delete("zone", int(zone["id"]))

    def _on_add_table(self) -> None:
        if not self._zones:
            QMessageBox.information(
                self, "Нет зон", "Сначала добавьте хотя бы одну зону.",
            )
            return
        from pos.screens.settings_sections.table_edit_dialog import TableEditDialog

        dlg = TableEditDialog(
            client=self._client, zones=self._zones, table=None,
            default_zone_id=self._active_zone_id, parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit_table(self, table: dict) -> None:
        from pos.screens.settings_sections.table_edit_dialog import TableEditDialog

        dlg = TableEditDialog(
            client=self._client, zones=self._zones, table=table, parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_delete_table(self, table: dict) -> None:
        ans = QMessageBox.question(
            self, "Удалить стол?",
            f"Стол «{table.get('name', '?')}» будет удалён.\n"
            "Нельзя удалить занятый стол или с активным заказом.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_delete("table", int(table["id"]))

    def _spawn_delete(self, kind: str, obj_id: int) -> None:
        thread = QThread(self)
        worker = _DeleteWorker(self._client, kind, obj_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _k, _i: self.reload())
        worker.error.connect(self._on_delete_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_delete_error(self, _kind: str, _id: int, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка удаления",
            f"[{exc.code}] {exc.message}",
        )
