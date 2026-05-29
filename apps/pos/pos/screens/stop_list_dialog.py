"""Стоп-лист — frame 14 в design/pos_cashier.pen.

В дизайне это модалка добавления одного блюда. На практике кассиру нужно
видеть весь список и одним кликом включать/выключать. Делаем дашборд:
поиск + табличка всех блюд с toggle (зелёный = доступно, серый = в стопе).

При снятии блюда со стоп-листа (доступно → в стоп) запрашивается причина
и опц. дата возврата (когда блюдо снова появится). При возврате (стоп →
доступно) — сразу через restore endpoint, без вопросов.
"""
from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
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
from pos.resources.icons import qicon, qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _ToggleWorker(QObject):
    success = Signal(int, dict)
    error = Signal(int, object)

    def __init__(
        self,
        client: ApiClient,
        item_id: int,
        action: str,
        body: dict | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.item_id = item_id
        self.action = action  # "stop_list" | "restore"
        self.body = body or {}

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/menu/items/{self.item_id}/{self.action}/",
                json=self.body,
            )
            payload = data.get("data") if isinstance(data, dict) and "data" in data else data
            self.success.emit(self.item_id, payload if isinstance(payload, dict) else {})
        except ApiError as e:
            self.error.emit(self.item_id, e)


class StopListDialog(QDialog):
    """Один экран — все блюда с переключателем доступности."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._filter: str = ""
        self._row_widgets: dict[int, QWidget] = {}
        self._threads: list[QThread] = []

        self.setWindowTitle("Стоп-лист")
        self.setModal(True)
        self.setFixedWidth(560)
        self.setMinimumHeight(640)
        self._build()
        self.reload()

    # -------- build --------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)
        layout.setSpacing(SPACING["sm"])

        icon = QLabel()
        icon.setPixmap(qpixmap("alert-triangle", COLORS["danger_red"], 22))
        layout.addWidget(icon)

        title = QLabel("Стоп-лист")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        layout.addWidget(title)
        layout.addStretch(1)

        close_btn = QPushButton()
        close_btn.setFlat(True)
        close_btn.setFixedSize(32, 32)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close_btn.setIconSize(QSize(18, 18))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; border-radius: 4px; }}"
        )
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        return h

    def _build_body(self) -> QWidget:
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        v = QVBoxLayout(body)
        v.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # Search
        search = QLineEdit()
        search.setPlaceholderText("Поиск по меню…")
        search.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 10px 14px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
        )
        search.textChanged.connect(self._on_search)
        v.addWidget(search)

        # List scroll
        self._list_holder = QWidget()
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_white']}; border: none; }}"
        )
        scroll.setWidget(self._list_holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)
        return body

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])

        self._counter = QLabel("")
        self._counter.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        h.addWidget(self._counter)
        h.addStretch(1)

        ok_btn = QPushButton("Готово")
        ok_btn.setFixedHeight(40)
        ok_btn.setMinimumWidth(120)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 24px; font-size: 12pt; font-weight: 700;"
            f"}}"
        )
        ok_btn.clicked.connect(self.accept)
        h.addWidget(ok_btn)
        return f

    # -------- data --------

    def reload(self) -> None:
        try:
            data = self._client.get("/menu/items/") or []
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить меню: {e.message}")
            data = []
        self._items = sorted(
            data, key=lambda i: (i.get("category", 0), i.get("sort_order", 0), i.get("name", ""))
        )
        self._render()

    def _on_search(self, text: str) -> None:
        self._filter = (text or "").strip().lower()
        self._render()

    def _render(self) -> None:
        # Очистить текущий layout
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        self._row_widgets.clear()

        unavailable = 0
        for item in self._items:
            name = (item.get("name") or "").lower()
            if self._filter and self._filter not in name:
                continue
            row = self._build_row(item)
            self._list_layout.addWidget(row)
            self._row_widgets[int(item["id"])] = row
            if not item.get("is_available"):
                unavailable += 1

        total = len(self._items)
        self._counter.setText(f"В стоп-листе: {unavailable} из {total}")

    def _build_row(self, item: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(SPACING["md"])

        emoji = item.get("emoji") or ""
        if emoji:
            elbl = QLabel(emoji)
            elbl.setStyleSheet("font-size: 16pt; border: none; background: transparent;")
            h.addWidget(elbl)

        text_col = QVBoxLayout()
        name = QLabel(item.get("name", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        price = QLabel(f"{item.get('price', '0.00')} TJS")
        price.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(name)
        text_col.addWidget(price)
        # Если в стопе — показываем причину + дату возврата отдельной строкой
        if not item.get("is_available"):
            reason = (item.get("stop_reason") or "").strip()
            until = item.get("stop_until")
            if reason or until:
                tail = ""
                if reason:
                    tail += reason
                if until:
                    tail += f"  ·  до {until}"
                stop_lbl = QLabel(tail)
                stop_lbl.setWordWrap(True)
                stop_lbl.setStyleSheet(
                    f"color: {COLORS['danger_red']}; font-size: 9pt;"
                    f" font-style: italic; border: none; background: transparent;"
                )
                text_col.addWidget(stop_lbl)
        h.addLayout(text_col, 1)

        is_avail = bool(item.get("is_available", True))
        toggle = QPushButton("В меню" if is_avail else "В стопе")
        toggle.setFixedHeight(32)
        toggle.setMinimumWidth(110)
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setProperty("item_id", int(item["id"]))
        if is_avail:
            toggle.setStyleSheet(
                f"QPushButton {{"
                f"  background: #DCFCE7;"
                f"  color: {COLORS['success_green']};"
                f"  border: 1px solid {COLORS['success_green']};"
                f"  border-radius: 6px; padding: 0 12px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover:enabled {{ background: #BBF7D0; }}"
            )
        else:
            toggle.setStyleSheet(
                f"QPushButton {{"
                f"  background: #FEE2E2;"
                f"  color: {COLORS['danger_red']};"
                f"  border: 1px solid {COLORS['danger_red']};"
                f"  border-radius: 6px; padding: 0 12px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover:enabled {{ background: #FECACA; }}"
            )
        toggle.clicked.connect(lambda _checked=False, mid=int(item["id"]): self._toggle(mid))
        h.addWidget(toggle)

        # Phase 8D — попап настроек блюда (учитывать техкарту / продавать в минус)
        gear = QPushButton("⚙")
        gear.setFixedSize(32, 32)
        gear.setCursor(Qt.PointingHandCursor)
        gear.setToolTip("Настройки склада для блюда")
        gear.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: {COLORS['text_secondary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px; font-size: 14pt;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        gear.clicked.connect(lambda _c=False, it=item: self._open_settings(it))
        h.addWidget(gear)
        return row

    def _open_settings(self, item: dict) -> None:
        from pos.screens.stop_item_settings_dialog import StopItemSettingsDialog
        d = StopItemSettingsDialog(self._client, item=item, parent=self)
        if d.exec() == d.DialogCode.Accepted:
            self.reload()

    # -------- handlers --------

    def _toggle(self, item_id: int) -> None:
        # Найти текущее состояние
        item = next(
            (i for i in self._items if int(i["id"]) == int(item_id)), None
        )
        if item is None:
            return
        is_avail = bool(item.get("is_available", True))
        if is_avail:
            # Снимаем со стоп-листа: спросить причину/дату
            from pos.screens.stop_reason_dialog import StopReasonDialog

            d = StopReasonDialog(item_name=item.get("name", "?"), parent=self)
            if d.exec() != d.DialogCode.Accepted:
                return
            self._run_action(item_id, "stop_list", body={
                "reason": d.reason,
                "until": d.until_iso,
            })
        else:
            # Возвращаем в продажу — без вопросов
            self._run_action(item_id, "restore", body={})

    def _run_action(self, item_id: int, action: str, body: dict) -> None:
        thread = QThread(self)
        worker = _ToggleWorker(self._client, item_id, action, body)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_toggle_done)
        worker.error.connect(self._on_toggle_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_toggle_done(self, item_id: int, item: dict) -> None:
        # обновить локальный item и пере-рендерить
        for i, it in enumerate(self._items):
            if int(it["id"]) == int(item_id):
                self._items[i] = item
                break
        self._render()

    def _on_toggle_failed(self, _item_id: int, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось обновить блюдо: {exc.message}"
        )
