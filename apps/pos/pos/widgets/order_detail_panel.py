"""Правая панель 360px по design frame "3. POS — Столы + Заказ" (id=nh6qW).

Показывает детали заказа на выбранном столе: header, список позиций, итог,
кнопки «Оплатить» / «Отменить». MVP-cut от полного дизайна:
- groupTabs (разделение заказа по группам) — Phase 4
- check-иконки (kitchen printed) — Phase 2
- скидка / обслуживание — Phase 4
- кнопки «Добавить блюдо» / «На кухню» / «Пре-чек» / «Разделить» / «Перенести» — waiter / Phase 4-5
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.resources.icons import qicon
from pos.resources.tokens import COLORS, RADIUS, SPACING

PANEL_WIDTH = 360


class OrderDetailPanel(QFrame):
    """Сигналы:
        pay_requested(order_id) — открыть Payment screen (экран 5)
        cancel_requested(order_id) — отменить заказ (через ApiClient наверху)
    """

    pay_requested = Signal(int)
    cancel_requested = Signal(int)
    add_items_requested = Signal(int)
    # Действия по существующей броне на свободном столе. Передаём
    # reservation_id + action ∈ {"confirm", "seat", "no_show", "cancel"}.
    reservation_action_requested = Signal(int, str)
    pre_bill_requested = Signal(int)
    cancel_item_requested = Signal(int, dict)  # (order_id, item dict)
    # Multi-group: «Добавить группу» на занятый стол (открывает MenuScreen
    # на этом столе → создание ещё одного параллельного заказа).
    add_group_requested = Signal(int)  # (table_id)
    # Switch active group tab (table_id, order_id) — каскад, чтобы
    # TablesScreen знал, какую группу пользователь сейчас смотрит.
    group_switched = Signal(int, int)
    # POST резервации делает TablesScreen (у которого есть ApiClient).
    # Панель собирает поля и шлёт сигнал с body.
    reserve_submit_requested = Signal(int, dict)  # (table_id, body)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("orderDetailPanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(
            f"#orderDetailPanel {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        self._order_id: int | None = None
        self._table_id: int | None = None
        # Список заказов на текущем столе (multi-group); используется для
        # перерисовки группы-табов при смене активной группы.
        self._table_orders: list[dict] = []
        self._build()
        self.show_empty()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 1. Header (orange bg)
        self._header = QFrame()
        self._header.setObjectName("odpHeader")
        self._header.setStyleSheet(
            f"#odpHeader {{ background-color: {COLORS['accent_orange']}; }}"
        )
        self._header_layout = QVBoxLayout(self._header)
        self._header_layout.setContentsMargins(16, 10, 16, 10)
        self._header_layout.setSpacing(4)

        self._header_title = QLabel("")
        self._header_title.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 18pt; font-weight: 700;"
        )
        self._header_subtitle = QLabel("")
        self._header_subtitle.setStyleSheet(
            f"color: rgba(255,255,255,0.85); font-size: 14pt; font-weight: 500;"
        )
        self._header_layout.addWidget(self._header_title)
        self._header_layout.addWidget(self._header_subtitle)

        v.addWidget(self._header)

        # 1.5. Group tabs strip — показывается только когда на столе ≥2 групп
        # или когда есть кнопка «➕ Добавить группу» (на занятом столе).
        self._group_bar = QFrame()
        self._group_bar.setObjectName("odpGroupBar")
        self._group_bar.setStyleSheet(
            f"#odpGroupBar {{ background: {COLORS['bg_gray']};"
            f" border-bottom: 1px solid {COLORS['border_light']}; }}"
        )
        self._group_bar_layout = QHBoxLayout(self._group_bar)
        self._group_bar_layout.setContentsMargins(8, 6, 8, 6)
        self._group_bar_layout.setSpacing(4)
        self._group_bar.hide()  # по умолчанию скрыт
        v.addWidget(self._group_bar)

        # 2. Order list scrollable
        self._list_container = QWidget()
        self._list_container.setStyleSheet(f"background: {COLORS['bg_white']};")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(16, 12, 16, 12)
        self._list_layout.setSpacing(8)
        self._list_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_white']}; border: none; }}"
        )
        scroll.setWidget(self._list_container)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)

        # 3. Buttons area (footer)
        self._btn_area = QFrame()
        self._btn_area.setObjectName("odpBtnArea")
        self._btn_area.setStyleSheet(
            f"#odpBtnArea {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        b = QVBoxLayout(self._btn_area)
        b.setContentsMargins(16, 12, 16, 16)
        b.setSpacing(10)

        self._add_btn = QPushButton("Добавить блюдо")
        self._add_btn.setFixedHeight(48)
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setFocusPolicy(Qt.NoFocus)
        self._add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none;"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 16pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #EA580C; }}"
            f"QPushButton:disabled {{ background: {COLORS['border_light']}; "
            f"  color: {COLORS['text_secondary']}; }}"
        )
        self._add_btn.clicked.connect(self._on_add_items)

        self._prebill_btn = QPushButton("ПРЕ-ЧЕК")
        self._prebill_btn.setFixedHeight(40)
        self._prebill_btn.setCursor(Qt.PointingHandCursor)
        self._prebill_btn.setFocusPolicy(Qt.NoFocus)
        self._prebill_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 14pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:disabled {{ color: {COLORS['border_light']}; "
            f"  border-color: {COLORS['border_light']}; }}"
        )
        self._prebill_btn.clicked.connect(self._on_prebill)

        self._pay_btn = QPushButton("ОПЛАТА  →")
        self._pay_btn.setFixedHeight(56)
        self._pay_btn.setCursor(Qt.PointingHandCursor)
        self._pay_btn.setFocusPolicy(Qt.NoFocus)
        self._pay_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 18pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background-color: {COLORS['accent_orange_pressed']}; }}"
            f"QPushButton:disabled {{ background-color: {COLORS['border_light']}; "
            f"  color: {COLORS['text_secondary']}; }}"
        )
        self._pay_btn.clicked.connect(self._on_pay)

        self._cancel_btn = QPushButton("Отменить заказ")
        self._cancel_btn.setFixedHeight(40)
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.setFocusPolicy(Qt.NoFocus)
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  border: 1px solid {COLORS['danger_red']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #FEE2E2; }}"
            f"QPushButton:disabled {{ color: {COLORS['border_light']}; "
            f"  border-color: {COLORS['border_light']}; }}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)

        b.addWidget(self._add_btn)
        b.addWidget(self._prebill_btn)
        b.addWidget(self._pay_btn)
        b.addWidget(self._cancel_btn)
        v.addWidget(self._btn_area)

    # ------- public API -------

    def show_empty(self) -> None:
        """Показать пустое состояние (стол не выбран или свободен)."""
        self._order_id = None
        self._table_id = None
        self._table_orders = []
        self._group_bar.hide()
        self._header_title.setText("Выберите стол")
        self._header_subtitle.setText("Слева на карте зала")
        self._clear_list()
        empty = QLabel("Здесь появятся позиции\nвыбранного заказа")
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; padding: 40px 0;"
        )
        self._list_layout.addWidget(empty)
        self._pay_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._prebill_btn.setEnabled(False)

    def show_free_table(self, table: dict) -> None:
        """Свободный стол: показать большую кнопку «Открыть стол» в правой
        панели вместо моментального перехода в MenuScreen. Тап — это
        выбор стола, явный action — это кнопка.

        Если на столе есть активная бронь (next_reservation) — рендерим
        info-карточку с именем/временем/гостями + кнопки управления.
        """
        self._order_id = None
        self._table_id = int(table.get("id") or 0)
        self._table_orders = []
        self._group_bar.hide()
        self._header_title.setText(table.get("name") or f"Стол {table.get('number')}")
        reservation = table.get("next_reservation")
        self._header_subtitle.setText("Зарезервирован" if reservation else "Свободен")
        self._clear_list()

        # Info card о брони, если есть
        if reservation:
            self._list_layout.addWidget(self._build_reservation_card(reservation))
        else:
            info = QLabel("Стол свободен")
            info.setAlignment(Qt.AlignCenter)
            info.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12pt;"
                f" padding: 20px 0 8px 0;"
            )
            self._list_layout.addWidget(info)

        # Кнопка «Открыть стол» убрана: клик по карточке свободного стола
        # сразу открывает inline-меню в TablesScreen — отдельный action не нужен.
        # Здесь оставлена только «Бронирование» (резерв стола до прихода гостя).

        # Кнопка «Бронирование» — outline, основной action для свободного стола.
        reserve_btn = QPushButton("Бронирование")
        reserve_btn.setFixedHeight(40)
        reserve_btn.setCursor(Qt.PointingHandCursor)
        reserve_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['primary_blue']};"
            f"  border: 1.5px solid {COLORS['primary_blue']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:pressed {{ background: #EFF6FF; }}"
        )
        reserve_btn.clicked.connect(
            lambda: self.show_reservation_form(table)
        )
        self._list_layout.addWidget(reserve_btn)

        self._pay_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._prebill_btn.setEnabled(False)

    def _render_group_bar(self) -> None:
        """Перерисовать таб-стрип групп. Показывается только когда:
        - на столе ≥2 активных групп, ИЛИ
        - стол занят (для кнопки «➕ Добавить группу»).
        Скрывается для свободного и пустого состояний."""
        # Очистить
        while self._group_bar_layout.count():
            child = self._group_bar_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._table_orders or self._table_id is None:
            self._group_bar.hide()
            return
        # Если групп 1 и кнопки «+» не нужно — скрываем стрип
        # (для compactness). Но мы хотим, чтобы можно было всегда добавить
        # вторую группу — поэтому показываем «+» даже при одной.
        for i, og in enumerate(self._table_orders, start=1):
            tab = self._build_group_tab(i, og)
            self._group_bar_layout.addWidget(tab)
        # «➕ Добавить группу»
        plus = QPushButton("➕ Группу")
        plus.setFixedHeight(36)
        plus.setMinimumWidth(110)
        plus.setCursor(Qt.PointingHandCursor)
        plus.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['accent_orange']};"
            f"  border: 1.5px dashed {COLORS['accent_orange']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px;"
            f"  font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background: #FFF7ED; }}"
        )
        plus.clicked.connect(self._on_add_group)
        self._group_bar_layout.addWidget(plus)
        self._group_bar_layout.addStretch(1)
        self._group_bar.show()

    def _build_group_tab(self, idx: int, order: dict) -> QPushButton:
        active = (int(order.get("id") or 0) == (self._order_id or 0))
        guests = int(order.get("guests_count") or 0)
        text = f"Гр.{idx} · {guests}"
        btn = QPushButton(text)
        btn.setFixedHeight(36)
        btn.setMinimumWidth(80)
        btn.setCursor(Qt.PointingHandCursor)
        if active:
            qss = (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 14px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"}}"
            )
        else:
            qss = (
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 14px;"
                f"  font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ border-color: {COLORS['accent_orange']}; }}"
            )
        btn.setStyleSheet(qss)
        oid = int(order.get("id") or 0)
        btn.clicked.connect(
            lambda _c=False, o=oid: self.group_switched.emit(self._table_id or 0, o)
        )
        return btn

    def show_reservation_form(self, table: dict) -> None:
        """Inline-форма бронирования прямо в правой панели (не модалка).

        Компактные поля — узкая панель 360px, не должно «распирать» layout.
        После «Сохранить» → emit `reserve_submit_requested(table_id, body)`,
        TablesScreen делает POST и зовёт `back_to_free_table_after_reserve`.
        """
        from datetime import datetime, timedelta

        from PySide6.QtWidgets import QButtonGroup, QLineEdit

        self._order_id = None
        self._table_id = int(table.get("id") or 0)
        self._group_bar.hide()
        self._header_title.setText(table.get("name") or f"Стол {table.get('number')}")
        self._header_subtitle.setText("Бронирование")
        self._clear_list()

        # Внутреннее состояние формы
        self._res_party: int = 2
        self._res_duration: int = 120
        self._res_at: datetime = (datetime.now() + timedelta(minutes=30)).replace(
            second=0, microsecond=0,
        )
        # Округляем до 15 мин
        m = self._res_at.minute
        delta = (15 - (m % 15)) % 15
        if delta:
            self._res_at = self._res_at + timedelta(minutes=delta)

        # Имя гостя
        self._list_layout.addWidget(self._compact_lbl("Гость"))
        self._res_name = QLineEdit()
        self._res_name.setPlaceholderText("Имя")
        self._res_name.setFixedHeight(36)
        self._res_name.setStyleSheet(self._compact_field_qss())
        self._res_name.textChanged.connect(self._update_res_save_state)
        self._list_layout.addWidget(self._res_name)

        # Телефон
        self._list_layout.addWidget(self._compact_lbl("Телефон"))
        self._res_phone = QLineEdit()
        self._res_phone.setPlaceholderText("+992 …")
        self._res_phone.setFixedHeight(36)
        self._res_phone.setStyleSheet(self._compact_field_qss())
        self._list_layout.addWidget(self._res_phone)

        # Гостей: компактный stepper
        guests_row = QFrame()
        gh = QHBoxLayout(guests_row)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.setSpacing(8)
        gh.addWidget(self._compact_lbl("Гостей"))
        gh.addStretch(1)
        minus = self._compact_step_btn("−", lambda: self._res_change_party(-1))
        gh.addWidget(minus)
        self._res_guests_lbl = QLabel(str(self._res_party))
        self._res_guests_lbl.setAlignment(Qt.AlignCenter)
        self._res_guests_lbl.setFixedWidth(40)
        self._res_guests_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 14pt; font-weight: 700;"
        )
        gh.addWidget(self._res_guests_lbl)
        plus = self._compact_step_btn("+", lambda: self._res_change_party(+1))
        gh.addWidget(plus)
        self._list_layout.addWidget(guests_row)

        # Дата и время — QDateTimeEdit + chip-пресеты.
        from PySide6.QtCore import QDate as _QD, QDateTime as _QDT, QTime as _QT
        from PySide6.QtWidgets import QDateTimeEdit as _QDTE

        self._list_layout.addWidget(self._compact_lbl("Дата и время"))
        self._res_dt_edit = _QDTE()
        self._res_dt_edit.setDisplayFormat("dd.MM.yyyy  HH:mm")
        self._res_dt_edit.setCalendarPopup(True)
        self._res_dt_edit.setFixedHeight(36)
        self._res_dt_edit.setDateTime(_QDT(
            _QD(self._res_at.year, self._res_at.month, self._res_at.day),
            _QT(self._res_at.hour, self._res_at.minute),
        ))
        self._res_dt_edit.setStyleSheet(
            f"QDateTimeEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 4px 8px; font-size: 12pt; font-weight: 600;"
            f"  color: {COLORS['accent_orange']};"
            f"}}"
            f"QDateTimeEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        self._res_dt_edit.dateTimeChanged.connect(self._on_res_dt_changed)
        self._list_layout.addWidget(self._res_dt_edit)

        # Пресеты «+1ч / +2ч / +3ч / Сег 19 / Завтра 19»
        presets = QFrame()
        presets.setStyleSheet("background: transparent;")
        ph = QHBoxLayout(presets)
        ph.setContentsMargins(0, 4, 0, 0)
        ph.setSpacing(4)
        for label, delta_min in (("+1ч", 60), ("+2ч", 120), ("+3ч", 180)):
            b = self._compact_step_btn(
                label, lambda m=delta_min: self._res_set_in_minutes(m),
            )
            ph.addWidget(b, 1)
        for label, hour, tomorrow in (
            ("Сег 19", 19, False), ("Завтра 19", 19, True),
        ):
            b = self._compact_step_btn(
                label,
                lambda h=hour, tm=tomorrow: self._res_set_hour(h, tomorrow=tm),
            )
            ph.addWidget(b, 1)
        self._list_layout.addWidget(presets)

        # Длительность — chip-buttons 60/90/120/180.
        self._list_layout.addWidget(self._compact_lbl("Длительность"))
        dur_row = QFrame()
        dur_row.setStyleSheet("background: transparent;")
        dh = QHBoxLayout(dur_row)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(4)
        self._res_dur_buttons: dict[int, QPushButton] = {}
        for minutes, lbl in ((60, "1ч"), (90, "1.5ч"), (120, "2ч"), (180, "3ч")):
            b = QPushButton(lbl)
            b.setFixedHeight(32)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                self._res_dur_btn_qss(active=(minutes == self._res_duration))
            )
            b.clicked.connect(lambda _c=False, m=minutes: self._res_set_duration(m))
            self._res_dur_buttons[minutes] = b
            dh.addWidget(b, 1)
        self._list_layout.addWidget(dur_row)

        # Комментарий — свободный текст («у окна», «день рождения», и т.д.).
        self._list_layout.addWidget(self._compact_lbl("Комментарий"))
        from PySide6.QtWidgets import QTextEdit

        self._res_notes = QTextEdit()
        self._res_notes.setPlaceholderText(
            "Например: «к 19:00 у окна», «день рождения»…"
        )
        self._res_notes.setFixedHeight(72)
        self._res_notes.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 6px 10px; font-size: 11pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
            f"QTextEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        self._list_layout.addWidget(self._res_notes)

        # Footer-кнопки
        footer = QFrame()
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(0, 8, 0, 0)
        fh.setSpacing(6)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:pressed {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel_btn.clicked.connect(lambda: self.show_free_table(table))
        fh.addWidget(cancel_btn, 1)

        self._res_save_btn = QPushButton("Сохранить")
        self._res_save_btn.setFixedHeight(40)
        self._res_save_btn.setEnabled(False)
        self._res_save_btn.setCursor(Qt.PointingHandCursor)
        self._res_save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background: {COLORS['accent_orange_pressed']}; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._res_save_btn.clicked.connect(self._on_res_save)
        fh.addWidget(self._res_save_btn, 1)
        self._list_layout.addWidget(footer)

        # Кнопки футера панели — отключаем пока в форме
        self._pay_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._prebill_btn.setEnabled(False)

    # ---- compact form helpers ----

    def _compact_lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; font-weight: 700;"
            f" margin-top: 2px;"
        )
        return l

    def _compact_field_qss(self) -> str:
        return (
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 10px; font-size: 11pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )

    def _compact_step_btn(self, text: str, handler) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(38, 36)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_gray']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 13pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background: {COLORS['border_light']}; }}"
        )
        b.clicked.connect(handler)
        return b

    # ---- form mutators ----

    def _build_reservation_card(self, r: dict) -> QFrame:
        """Карточка инфо об активной броне на свободном столе.

        Показывает: имя, время (HH:MM), party_size, телефон, заметку.
        Кнопки в зависимости от status:
        - pending  → Подтвердить · Усадить · Не пришли · Отменить
        - confirmed → Усадить · Не пришли · Отменить
        - seated → (нечего делать — стол перейдёт в occupied)
        """
        from datetime import datetime

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: #FFF7ED;"
            f"  border: 1px solid {COLORS['accent_orange']};"
            f"  border-radius: {RADIUS['sm']}px; padding: 10px; }}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Заголовок
        title = QLabel("🕐 Бронь")
        title.setStyleSheet(
            f"color: {COLORS['accent_orange']};"
            f" font-size: 12pt; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        v.addWidget(title)

        # Имя
        name = (r.get("customer_name") or "").strip() or "—"
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        v.addWidget(name_lbl)

        # Время + гости + телефон
        iso = r.get("scheduled_at") or ""
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
            date_str = dt.strftime("%d.%m")
        except (ValueError, TypeError):
            time_str = (iso or "")[:16].replace("T", " ")
            date_str = ""
        party = r.get("party_size") or 0
        meta_text = f"<b>{time_str}</b>"
        if date_str:
            meta_text += f" · {date_str}"
        if party:
            meta_text += f" · ×{party}"
        phone = (r.get("customer_phone") or "").strip()
        if phone:
            meta_text += f"<br/>{phone}"
        notes = (r.get("notes") or "").strip()
        if notes:
            meta_text += f"<br/><i>{notes}</i>"
        meta_lbl = QLabel(meta_text)
        meta_lbl.setWordWrap(True)
        meta_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" background: transparent; border: none;"
        )
        v.addWidget(meta_lbl)

        # Кнопки действий
        status = r.get("status", "")
        rid = int(r.get("id") or 0)
        actions: list[tuple[str, str, str]] = []  # (label, action, kind)
        if status == "pending":
            actions.append(("Подтвердить", "confirm", "primary"))
        if status in ("pending", "confirmed"):
            actions.append(("Усадить", "seat", "primary"))
            actions.append(("Не пришли", "no_show", "outline"))
            actions.append(("Отменить", "cancel", "danger"))

        if actions:
            grid = QFrame()
            grid.setStyleSheet("background: transparent;")
            gh = QVBoxLayout(grid)
            gh.setContentsMargins(0, 4, 0, 0)
            gh.setSpacing(4)
            # Pair into rows of 2
            row_layout: QHBoxLayout | None = None
            for i, (label, act, kind) in enumerate(actions):
                if i % 2 == 0:
                    row = QFrame()
                    row.setStyleSheet("background: transparent;")
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(4)
                    gh.addWidget(row)
                btn = QPushButton(label)
                btn.setFixedHeight(32)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(self._res_action_btn_qss(kind))
                btn.clicked.connect(
                    lambda _c=False, a=act: self.reservation_action_requested.emit(
                        rid, a,
                    )
                )
                row_layout.addWidget(btn, 1)
            v.addWidget(grid)

        return card

    def _res_action_btn_qss(self, kind: str) -> str:
        if kind == "primary":
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  font-size: 10pt; font-weight: 700;"
                f"}}"
                f"QPushButton:pressed {{ background: {COLORS['accent_orange_pressed']}; }}"
            )
        if kind == "danger":
            return (
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['danger_red']};"
                f"  border: 1px solid {COLORS['danger_red']};"
                f"  border-radius: {RADIUS['sm']}px;"
                f"  font-size: 10pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: #FEE2E2; }}"
            )
        # outline
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 10pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _res_change_party(self, delta: int) -> None:
        self._res_party = max(1, min(50, self._res_party + delta))
        self._res_guests_lbl.setText(str(self._res_party))

    def _on_res_dt_changed(self, qdt) -> None:
        """Sync QDateTimeEdit → self._res_at."""
        from datetime import datetime
        py = qdt.toPython() if hasattr(qdt, "toPython") else None
        if py is None:
            py = datetime(
                qdt.date().year(), qdt.date().month(), qdt.date().day(),
                qdt.time().hour(), qdt.time().minute(),
            )
        self._res_at = py.replace(second=0, microsecond=0)

    def _res_apply_dt(self) -> None:
        """Push self._res_at → QDateTimeEdit (без рекурсии-сигнала)."""
        from PySide6.QtCore import QDate, QDateTime, QTime
        if not hasattr(self, "_res_dt_edit"):
            return
        self._res_dt_edit.blockSignals(True)
        self._res_dt_edit.setDateTime(QDateTime(
            QDate(self._res_at.year, self._res_at.month, self._res_at.day),
            QTime(self._res_at.hour, self._res_at.minute),
        ))
        self._res_dt_edit.blockSignals(False)

    def _res_set_in_minutes(self, minutes: int) -> None:
        from datetime import datetime, timedelta
        base = datetime.now().replace(second=0, microsecond=0)
        self._res_at = base + timedelta(minutes=minutes)
        # round to 15-min
        m = self._res_at.minute
        delta = (15 - (m % 15)) % 15
        if delta:
            self._res_at = self._res_at + timedelta(minutes=delta)
        self._res_apply_dt()

    def _res_set_hour(self, hour: int, *, tomorrow: bool = False) -> None:
        from datetime import date, datetime, time, timedelta
        target_date = date.today() + (timedelta(days=1) if tomorrow else timedelta())
        self._res_at = datetime.combine(target_date, time(hour, 0))
        self._res_apply_dt()

    def _res_set_duration(self, minutes: int) -> None:
        self._res_duration = int(minutes)
        for m, btn in self._res_dur_buttons.items():
            btn.setChecked(m == minutes)
            btn.setStyleSheet(self._res_dur_btn_qss(active=(m == minutes)))

    def _res_dur_btn_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  font-size: 11pt; font-weight: 700;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _update_res_save_state(self) -> None:
        ok = bool(self._res_name.text().strip())
        self._res_save_btn.setEnabled(ok)

    def _on_res_save(self) -> None:
        if not self._res_save_btn.isEnabled() or self._table_id is None:
            return
        body = {
            "table": int(self._table_id),
            "customer_name": self._res_name.text().strip(),
            "customer_phone": self._res_phone.text().strip(),
            "party_size": int(self._res_party),
            "duration_min": int(self._res_duration),
            "scheduled_at": self._res_at.isoformat(),
            "notes": self._res_notes.toPlainText().strip(),
        }
        self._res_save_btn.setEnabled(False)
        self._res_save_btn.setText("…")
        self.reserve_submit_requested.emit(int(self._table_id), body)

    def _on_add_group(self) -> None:
        if self._table_id:
            self.add_group_requested.emit(self._table_id)

    def show_order(self, table: dict, order: dict) -> None:
        """Показать заказ выбранного стола.

        Если на столе несколько групп — рендерит таб-стрип сверху со всеми
        активными группами + кнопкой «➕ Добавить группу». Кликая по табу,
        пользователь переключает между группами.
        """
        self._order_id = int(order["id"])
        self._table_id = int(table.get("id") or 0)
        self._table_orders = list(table.get("active_orders") or [])
        # Если в active_orders нет — используем переданный заказ как
        # одиночный (legacy совместимость).
        if not self._table_orders:
            self._table_orders = [{
                "id": order["id"],
                "guests_count": order.get("guests_count", 0),
                "total": order.get("total", "0.00"),
                "waiter_name": order.get("waiter_name"),
                "status": order.get("status", "new"),
            }]
        self._render_group_bar()

        table_name = table.get("name") or f"Стол {table.get('number')}"
        guests = int(order.get("guests_count") or 0)
        # Если групп несколько — показываем «Стол 5 · Гр.1»
        if len(self._table_orders) >= 2:
            idx = next(
                (i for i, og in enumerate(self._table_orders, start=1)
                 if int(og["id"]) == self._order_id),
                1,
            )
            self._header_title.setText(f"{table_name}  ·  Гр.{idx}")
        else:
            self._header_title.setText(table_name)
        guest_word = self._guests_word(guests)
        self._header_subtitle.setText(
            f"{guests} {guest_word}" if guests else "—"
        )

        self._clear_list()
        items = order.get("items") or []
        active = [it for it in items if not it.get("cancelled_at")]
        # Активные заказы (new/bill_requested) — позиции можно отменять.
        is_active = order.get("status") in {"new", "bill_requested"}
        for it in active:
            self._list_layout.addWidget(
                self._build_item_row(it, can_cancel=is_active)
            )

        self._list_layout.addWidget(self._build_separator())
        self._list_layout.addWidget(self._build_total_row(order))

        # is_active уже посчитан выше для item-cancel; используем его для кнопок.
        # Дозаказ можно только пока статус new (как и backend в add_items_to_order).
        is_new = order.get("status") == "new"
        self._pay_btn.setEnabled(is_active)
        self._cancel_btn.setEnabled(is_active)
        self._add_btn.setEnabled(is_new)
        self._prebill_btn.setEnabled(is_active)


    # ------- helpers -------

    def _clear_list(self) -> None:
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _build_item_row(self, item: dict, *, can_cancel: bool = False) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["sm"])

        name = item.get("name_at_order") or "?"
        qty = int(item.get("qty") or 1)
        title_text = f"{name} ×{qty}" if qty > 1 else name
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt;"
        )
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        sub = item.get("subtotal") or "0.00"
        amount = QLabel(str(sub))
        amount.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 600;"
        )
        amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h.addWidget(title, 1)
        h.addWidget(amount)

        if can_cancel:
            # Маленький светло-красный круг (под высоту строки) с красным крестиком.
            x_btn = QPushButton()
            x_btn.setIcon(qicon("x", COLORS["danger_red"], 10))
            x_btn.setIconSize(QSize(10, 10))
            x_btn.setFixedSize(18, 18)
            x_btn.setCursor(Qt.PointingHandCursor)
            x_btn.setToolTip("Отменить позицию")
            x_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: #FEE2E2;"  # light red
                f"  border: none;"
                f"  border-radius: 9px;"  # 18/2 — perfect circle
                f"}}"
                f"QPushButton:hover {{ background: #FECACA; }}"
                f"QPushButton:pressed {{ background: #FCA5A5; }}"
            )
            x_btn.clicked.connect(
                lambda _c=False, it=item: self._on_cancel_item(it)
            )
            h.addWidget(x_btn)
        return row

    def _build_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border_light']}; border: none;")
        return sep

    def _build_total_row(self, order: dict) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 4, 0, 0)
        h.setSpacing(SPACING["sm"])

        lbl = QLabel("ИТОГО")
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16pt; font-weight: 700;"
        )

        total = order.get("total") or "0.00"
        currency = order.get("currency") or "TJS"
        amount = QLabel(f"{total} {currency}")
        amount.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 22pt; font-weight: 800;"
        )
        amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h.addWidget(lbl)
        h.addStretch(1)
        h.addWidget(amount)
        return row

    @staticmethod
    def _guests_word(n: int) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return "гость"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "гостя"
        return "гостей"

    def _on_pay(self) -> None:
        if self._order_id:
            self.pay_requested.emit(self._order_id)

    def _on_cancel(self) -> None:
        if self._order_id:
            self.cancel_requested.emit(self._order_id)

    def _on_add_items(self) -> None:
        if self._order_id:
            self.add_items_requested.emit(self._order_id)

    def _on_prebill(self) -> None:
        if self._order_id:
            self.pre_bill_requested.emit(self._order_id)

    def _on_cancel_item(self, item: dict) -> None:
        if self._order_id:
            self.cancel_item_requested.emit(self._order_id, item)
