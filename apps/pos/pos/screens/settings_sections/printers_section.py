"""Frame 18 — Настройки / Принтеры.

Содержимое:
- Заголовок «Принтеры» + «+ Добавить принтер» (orange)
- Список карточек принтеров: иконка+название / тип+адрес / badge (online/offline)
  / [Тест печати] [Настроить] [Удалить]
- Карточка «Настройки печати» — placeholder под autoprint/copies (Phase 2 сохранение)

Все мутации идут через ApiClient в QThread (через _Worker), чтобы не блокировать UI.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from pos.resources.icons import qicon, qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING

KIND_LABELS = {
    "usb": "USB",
    "tcp": "TCP/IP",
    "serial": "Serial",
    "virtual": "Виртуальный (файл)",
}


class _ListWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/printing/printers/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _StationsListWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/printing/stations/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _StationUpdateWorker(QObject):
    """PATCH (printer / name / is_active) на станцию."""

    success = Signal(int, dict)
    error = Signal(int, object)

    def __init__(
        self, client: ApiClient, station_id: int, body: dict
    ) -> None:
        super().__init__()
        self.client = client
        self.station_id = station_id
        self.body = body

    def run(self) -> None:
        try:
            data = self.client.request(
                "PATCH",
                f"/printing/stations/{self.station_id}/",
                json=self.body,
                idempotent=True,
            )
            self.success.emit(self.station_id, data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(self.station_id, e)


class _StationCreateWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient, body: dict) -> None:
        super().__init__()
        self.client = client
        self.body = body

    def run(self) -> None:
        try:
            data = self.client.request(
                "POST", "/printing/stations/",
                json=self.body, idempotent=True,
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class _StationDeleteWorker(QObject):
    success = Signal(int)
    error = Signal(int, object)

    def __init__(self, client: ApiClient, station_id: int) -> None:
        super().__init__()
        self.client = client
        self.station_id = station_id

    def run(self) -> None:
        try:
            self.client.request(
                "DELETE",
                f"/printing/stations/{self.station_id}/",
                idempotent=True,
            )
            self.success.emit(self.station_id)
        except ApiError as e:
            self.error.emit(self.station_id, e)


class _ActionWorker(QObject):
    """Универсальный worker для test_print / delete."""

    success = Signal(str, int, dict)  # action, item_id, data
    error = Signal(str, int, object)  # action, item_id, ApiError

    def __init__(self, client: ApiClient, action: str, item_id: int) -> None:
        super().__init__()
        self.client = client
        self.action = action
        self.item_id = item_id

    def run(self) -> None:
        try:
            if self.action == "test_print":
                data = self.client.post(
                    f"/printing/printers/{self.item_id}/test_print/",
                    json={},
                    idempotent=True,
                )
            elif self.action == "delete":
                data = self.client.request(
                    "DELETE",
                    f"/printing/printers/{self.item_id}/",
                    idempotent=True,
                )
            else:
                data = {}
            self.success.emit(self.action, self.item_id, data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(self.action, self.item_id, e)


class PrintersSection(QWidget):
    """Frame 18. Используется внутри SettingsScreen QStackedWidget."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._stations: list[dict] = []
        self._threads: list[QThread] = []
        self._build()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"PrintersSection {{ background: {COLORS['bg_light']}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Header
        header = QHBoxLayout()
        title = QLabel("Принтеры")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
        )
        header.addWidget(title)
        header.addStretch(1)

        add_btn = QPushButton("  + Добавить принтер")
        add_btn.setFixedHeight(40)
        add_btn.setMinimumWidth(200)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"  text-align: center;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)
        v.addLayout(header)

        # Scroll-area список
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

        # Empty state placeholder (показывается, если 0 принтеров)
        self._empty_label = QLabel("Принтеров ещё нет — добавьте первый")
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

        # Карточка «Цеха» — динамические станции печати с CRUD.
        v.addWidget(self._build_stations_card())

        # Карточка «Настройки печати» — placeholder. Серверной реализации ещё нет
        # (см. roadmap). Чекбоксы локально включаются/выключаются.
        v.addWidget(self._build_print_settings_card())

    def _build_stations_card(self) -> QWidget:
        """Карточка цехов печати — list + add/edit/delete + printer combobox."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        cv.setSpacing(SPACING["md"])

        head = QHBoxLayout()
        title = QLabel("Цеха / станции печати")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        head.addWidget(title)
        head.addStretch(1)

        self._add_station_btn = QPushButton("  + Добавить цех")
        self._add_station_btn.setFixedHeight(34)
        self._add_station_btn.setMinimumWidth(160)
        self._add_station_btn.setCursor(Qt.PointingHandCursor)
        self._add_station_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        self._add_station_btn.clicked.connect(self._on_add_station)
        head.addWidget(self._add_station_btn)
        cv.addLayout(head)

        hint = QLabel(
            "Свяжите категории меню с цехами в «Меню и категории». "
            "Заказ автоматически распечатается на нужном принтере."
        )
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        hint.setWordWrap(True)
        cv.addWidget(hint)

        self._stations_holder = QWidget()
        self._stations_holder.setStyleSheet("background: transparent;")
        self._stations_layout = QVBoxLayout(self._stations_holder)
        self._stations_layout.setContentsMargins(0, 0, 0, 0)
        self._stations_layout.setSpacing(SPACING["sm"])
        cv.addWidget(self._stations_holder)
        return card

    def _render_stations(self) -> None:
        while self._stations_layout.count():
            child = self._stations_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        if not getattr(self, "_stations", None):
            empty = QLabel("Цехов нет")
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt; font-style: italic;"
                f" border: none; background: transparent; padding: 8px 0;"
            )
            self._stations_layout.addWidget(empty)
            return
        for st in self._stations:
            self._stations_layout.addWidget(self._build_station_row(st))

    def _build_station_row(self, station: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(SPACING["md"], 8, SPACING["md"], 8)
        h.setSpacing(SPACING["md"])

        # Имя станции (+ бейдж system если применимо)
        name_col = QHBoxLayout()
        name_col.setSpacing(6)
        name = QLabel(station.get("name", "?"))
        name.setFixedWidth(170)
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        name_col.addWidget(name)
        if station.get("is_system"):
            sys_badge = QLabel("system")
            sys_badge.setStyleSheet(
                f"color: {COLORS['primary_blue']}; font-size: 9pt; font-weight: 600;"
                f" background: #DBEAFE; border: none;"
                f" padding: 1px 6px; border-radius: 3px;"
            )
            name_col.addWidget(sys_badge)
        h.addLayout(name_col)

        # Combo с принтерами
        combo = QComboBox()
        combo.setFixedHeight(32)
        combo.setMinimumWidth(200)
        combo.setCursor(Qt.PointingHandCursor)
        combo.setStyleSheet(
            f"QComboBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 10px;"
            f"  font-size: 11pt;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
        )
        combo.addItem("— Принтер не выбран —", None)
        for p in self._items:
            combo.addItem(p.get("name", "?"), int(p["id"]))
        cur = station.get("printer")
        for i in range(combo.count()):
            if combo.itemData(i) == cur:
                combo.setCurrentIndex(i)
                break
        combo.currentIndexChanged.connect(
            lambda _idx, sid=int(station["id"]), cb=combo:
            self._on_station_printer_change(sid, cb.currentData())
        )
        h.addWidget(combo, 1)

        # Удалить (только для не-system)
        if not station.get("is_system"):
            del_btn = QPushButton()
            del_btn.setIcon(qicon("trash-2", COLORS["danger_red"], 16))
            del_btn.setIconSize(QSize(16, 16))
            del_btn.setFixedSize(32, 32)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setToolTip("Удалить цех")
            del_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  border: 1px solid #FECACA;"
                f"  border-radius: {RADIUS['sm']}px;"
                f"}}"
                f"QPushButton:hover {{ background: #FEE2E2; }}"
            )
            del_btn.clicked.connect(
                lambda _c=False, st=station: self._on_delete_station(st)
            )
            h.addWidget(del_btn)
        return row

    def _on_station_printer_change(
        self, station_id: int, printer_id: int | None
    ) -> None:
        self._spawn_station_update(station_id, {"printer": printer_id})

    def _spawn_station_update(self, station_id: int, body: dict) -> None:
        thread = QThread(self)
        worker = _StationUpdateWorker(self._client, station_id, body)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_station_updated)
        worker.error.connect(self._on_station_op_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_station_updated(self, station_id: int, data: dict) -> None:
        for i, st in enumerate(self._stations):
            if int(st["id"]) == int(station_id):
                self._stations[i] = {**st, **data}
                break

    def _on_station_op_failed(self, _id: int, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Операция не удалась: {exc.message}"
        )
        self.reload()

    def _on_add_station(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, "Новый цех",
            "Название цеха (например: «Кондитерский»):",
        )
        if not ok or not (name or "").strip():
            return
        body = {
            "name": name.strip(),
            "is_active": True,
            "sort_order": 99,
        }
        thread = QThread(self)
        worker = _StationCreateWorker(self._client, body)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _d: self.reload())
        worker.error.connect(lambda exc: self._on_station_op_failed(0, exc))
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_delete_station(self, station: dict) -> None:
        ans = QMessageBox.question(
            self, "Удалить цех?",
            f"Цех «{station.get('name', '?')}» будет удалён. "
            "Категории, привязанные к нему, потеряют станцию печати.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        thread = QThread(self)
        worker = _StationDeleteWorker(self._client, int(station["id"]))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _id: self.reload())
        worker.error.connect(self._on_station_op_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _build_print_settings_card(self) -> QWidget:
        """Карточка «Настройки печати» по frame 18: 3 чекбокса + dropdown
        «Кол-во копий чека»."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        cv.setSpacing(SPACING["md"])

        title = QLabel("Настройки печати")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        cv.addWidget(title)

        # 3 чекбокса с кастомным indicator (оранжевый квадрат с белой галочкой
        # когда checked, белый с серым бордером когда unchecked) — как в дизайне.
        cb_qss = self._checkbox_qss()

        self.cb_autoprint = QCheckBox("Автопечать чека после оплаты")
        self.cb_autoprint.setChecked(True)
        self.cb_autoprint.setStyleSheet(cb_qss)
        cv.addWidget(self.cb_autoprint)

        self.cb_pre_bill = QCheckBox("Печать пред-чека гостю")
        self.cb_pre_bill.setChecked(False)
        self.cb_pre_bill.setStyleSheet(cb_qss)
        cv.addWidget(self.cb_pre_bill)

        self.cb_kitchen = QCheckBox("Печать на кухню при добавлении блюда")
        self.cb_kitchen.setChecked(True)
        self.cb_kitchen.setStyleSheet(cb_qss)
        cv.addWidget(self.cb_kitchen)

        # Dropdown «Кол-во копий чека»
        copies_row = QHBoxLayout()
        copies_row.setSpacing(SPACING["md"])

        copies_lbl = QLabel("Кол-во копий чека:")
        copies_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt;"
            f" border: none; background: transparent;"
        )
        copies_row.addWidget(copies_lbl)
        copies_row.addStretch(1)

        self.copies_combo = QComboBox()
        for n in range(1, 6):
            self.copies_combo.addItem(str(n), n)
        self.copies_combo.setCurrentIndex(0)
        self.copies_combo.setFixedSize(80, 40)
        self.copies_combo.setCursor(Qt.PointingHandCursor)
        self.copies_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px;"
            f"  font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        )
        copies_row.addWidget(self.copies_combo)
        cv.addLayout(copies_row)

        note = QLabel("Параметры сохраняются локально (Phase 2 — синхронизация).")
        note.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; padding-top: 4px; background: transparent;"
        )
        cv.addWidget(note)
        return card

    def _checkbox_qss(self) -> str:
        """Кастомный indicator: 22×22, выкл — белый с серым бордером,
        вкл — оранжевый с белой галочкой."""
        check_icon = (
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'"
            " viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3'"
            " stroke-linecap='round' stroke-linejoin='round'>"
            "<polyline points='20 6 9 17 4 12'/></svg>\")"
        )
        return (
            f"QCheckBox {{"
            f"  color: {COLORS['text_primary']}; font-size: 12pt;"
            f"  border: none; spacing: 12px; padding: 4px 0;"
            f"  background: transparent;"
            f"}}"
            f"QCheckBox::indicator {{"
            f"  width: 22px; height: 22px; border-radius: 4px;"
            f"  background: {COLORS['bg_white']};"
            f"  border: 2px solid {COLORS['border_light']};"
            f"}}"
            f"QCheckBox::indicator:checked {{"
            f"  background: {COLORS['accent_orange']};"
            f"  border: 2px solid {COLORS['accent_orange']};"
            f"  image: {check_icon};"
            f"}}"
        )

    # -------- public --------

    def reload(self) -> None:
        # Принтеры
        thread = QThread(self)
        worker = _ListWorker(self._client)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_list_loaded)
        worker.error.connect(self._on_list_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

        # Цеха
        rt = QThread(self)
        rw = _StationsListWorker(self._client)
        rw.moveToThread(rt)
        rt.started.connect(rw.run)
        rw.success.connect(self._on_stations_loaded)
        rw.error.connect(self._on_stations_error)
        rw.success.connect(rt.quit)
        rw.error.connect(rt.quit)
        rt.finished.connect(rt.deleteLater)
        rt._worker = rw  # noqa: SLF001
        self._threads.append(rt)
        rt.start()

    def _on_stations_loaded(self, stations: list) -> None:
        self._stations = sorted(
            list(stations),
            key=lambda s: (int(s.get("sort_order", 0)), s.get("name", "")),
        )
        self._render_stations()

    def _on_stations_error(self, _exc: ApiError) -> None:
        self._stations = []
        self._render_stations()

    # -------- list rendering --------

    def _on_list_loaded(self, items: list) -> None:
        self._items = list(items)
        self._render()
        # Stations combobox-опции зависят от списка принтеров — перерисуем.
        self._render_stations()

    def _on_list_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось загрузить список принтеров: {exc.message}"
        )
        self._items = []
        self._render()

    def _render(self) -> None:
        # Очистить
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        self._empty_label.setVisible(not self._items)
        for printer in self._items:
            self._list_layout.addWidget(self._build_card(printer))

    def _build_card(self, printer: dict) -> QWidget:
        """Карточка принтера по frame 18:
        - Top row: левая колонка (название + тип + 'IP: …') / правая (статус-кружок + лейбл)
        - Bottom row: 3 кнопки [Тест печати] [Настроить] [Удалить] (Удалить — red, без fill)
        """
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # ----- Top row: name+type / status -----
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(SPACING["md"])

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        name_row = QHBoxLayout()
        name_row.setSpacing(SPACING["sm"])
        name = QLabel(printer.get("name", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        name_row.addWidget(name)
        if printer.get("is_default"):
            default_badge = QLabel("по умолчанию")
            default_badge.setStyleSheet(
                f"color: {COLORS['primary_blue']}; font-size: 9pt; font-weight: 700;"
                f" background: #DBEAFE; border: none;"
                f" padding: 2px 8px; border-radius: 4px;"
            )
            name_row.addWidget(default_badge)
        name_row.addStretch(1)
        text_col.addLayout(name_row)

        kind_label = KIND_LABELS.get(printer.get("kind", ""), printer.get("kind", ""))
        kind = QLabel(kind_label)
        kind.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(kind)

        addr = printer.get("address") or "—"
        addr_label = f"IP: {addr}" if printer.get("kind") == "tcp" else f"Адрес: {addr}"
        addr_lbl = QLabel(addr_label)
        addr_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(addr_lbl)
        top.addLayout(text_col, 1)

        # Status: цветной кружок 10×10 + текст рядом (не плашка-badge).
        is_active = bool(printer.get("is_active", True))
        status_color = COLORS["success_green"] if is_active else COLORS["danger_red"]
        status_text = "Онлайн" if is_active else "Офлайн"

        status_box = QHBoxLayout()
        status_box.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"background: {status_color}; border-radius: 5px; border: none;"
        )
        status_box.addWidget(dot)

        status_lbl = QLabel(status_text)
        status_lbl.setStyleSheet(
            f"color: {status_color}; font-size: 11pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        status_box.addWidget(status_lbl)
        top.addLayout(status_box)
        v.addLayout(top)

        # ----- Action row: Тест печати / Настроить / Удалить -----
        actions = QHBoxLayout()
        actions.setSpacing(SPACING["md"])

        test_btn = QPushButton("Тест печати")
        test_btn.setFixedHeight(40)
        test_btn.setMinimumWidth(140)
        test_btn.setCursor(Qt.PointingHandCursor)
        test_btn.setStyleSheet(self._secondary_btn_qss())
        test_btn.clicked.connect(
            lambda _c=False, pid=int(printer["id"]): self._on_test(pid)
        )
        actions.addWidget(test_btn)

        edit_btn = QPushButton("Настроить")
        edit_btn.setFixedHeight(40)
        edit_btn.setMinimumWidth(140)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setStyleSheet(self._secondary_btn_qss())
        edit_btn.clicked.connect(lambda _c=False, p=printer: self._on_edit(p))
        actions.addWidget(edit_btn)

        del_btn = QPushButton("Удалить")
        del_btn.setFixedHeight(40)
        del_btn.setMinimumWidth(120)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: #FEE2E2; }}"
        )
        del_btn.clicked.connect(lambda _c=False, p=printer: self._on_delete(p))
        actions.addWidget(del_btn)
        actions.addStretch(1)
        v.addLayout(actions)
        return card

    def _secondary_btn_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 11pt; font-weight: 500;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _make_action_btn(
        self, label: str, *, icon_name: str | None, bg: str, fg: str, border: str
    ) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(36)
        btn.setMinimumWidth(120)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {fg};"
            f"  border: 1px solid {border}; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        if icon_name:
            btn.setIcon(qicon(icon_name, fg, 16))
            btn.setIconSize(QSize(16, 16))
        return btn

    # -------- handlers --------

    def _on_add(self) -> None:
        from pos.screens.settings_sections.printer_edit_dialog import PrinterEditDialog

        dlg = PrinterEditDialog(client=self._client, printer=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit(self, printer: dict) -> None:
        from pos.screens.settings_sections.printer_edit_dialog import PrinterEditDialog

        dlg = PrinterEditDialog(client=self._client, printer=printer, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_test(self, printer_id: int) -> None:
        self._spawn_action("test_print", printer_id)

    def _on_delete(self, printer: dict) -> None:
        ans = QMessageBox.question(
            self,
            "Удалить принтер?",
            f"Принтер «{printer.get('name', '?')}» будет удалён. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._spawn_action("delete", int(printer["id"]))

    def _spawn_action(self, action: str, item_id: int) -> None:
        thread = QThread(self)
        worker = _ActionWorker(self._client, action, item_id)
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
        if action == "test_print":
            QMessageBox.information(
                self, "Тест печати", "Задание печати поставлено в очередь."
            )
        elif action == "delete":
            self.reload()

    def _on_action_failed(self, action: str, _item_id: int, exc: ApiError) -> None:
        if action == "test_print":
            msg = f"Не удалось отправить тестовую печать: {exc.message}"
        elif action == "delete":
            msg = f"Не удалось удалить принтер: {exc.message}"
        else:
            msg = exc.message
        QMessageBox.warning(self, "Ошибка", msg)
