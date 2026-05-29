"""KitchenScreen — KDS-канбан для роли cook (или cashier для контроля выдачи).

Frame: новый экран Phase 2 (нет в pos_cashier.pen — это Cook role, отдельный
дизайн пока не сделан, делаем минималистичный канбан под бизнес-логику).

Layout:
- Topbar: «Кухня», имя повара, online indicator
- 3 колонки:
   - Новые        (status=new) → кнопка «Принять»
   - Готовится    (status=cooking) → кнопка «Готово»
   - Готово       (status=ready) → кнопка «Выдано»
- Карточка в каждой колонке: блюдо, стол/тип, qty, заметка, время «N мин назад»
"""
from datetime import datetime
from datetime import timezone as tz

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.state import State


COLUMNS = [
    ("new", "Новые", COLORS["accent_orange"], "Принять", "start_cooking"),
    ("cooking", "Готовится", COLORS["primary_blue"], "Готово", "mark_ready"),
    ("ready", "Готово", COLORS["success_green"], "Выдано", "mark_served"),
]


class KitchenScreen(QWidget):
    """Сигналы:
        logout_requested()
    """

    logout_requested = Signal()

    def __init__(self, state: State, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._items: list[dict] = []
        self._cook_name: str = ""
        # Снимок предыдущих NEW-id для определения новых поступлений
        # (звуковой alert при появлении новой позиции).
        self._prev_new_ids: set[int] = set()
        self._sound_enabled: bool = True
        self._build()
        # SSE-обновление: kitchen.status_changed → reload.
        if hasattr(self.state, "sse_event"):
            try:
                self.state.sse_event.connect(self._on_sse_event)
            except Exception:
                pass
        # Автообновление каждые 10 сек как fallback (на случай если SSE упал).
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(10_000)
        self._poll_timer.timeout.connect(self.reload)

    # -------- public --------

    def set_cook(self, name: str) -> None:
        self._cook_name = name or ""
        if hasattr(self, "_cook_lbl"):
            self._cook_lbl.setText(self._cook_name)

    def reload(self) -> None:
        try:
            resp = self.state.client.get("/kitchen/items/")
            if isinstance(resp, dict) and "data" in resp:
                self._items = resp["data"]
            elif isinstance(resp, list):
                self._items = resp
            else:
                self._items = []
        except ApiError:
            self._items = []
        self._render()

    def start_polling(self) -> None:
        self.reload()
        self._poll_timer.start()

    def stop_polling(self) -> None:
        self._poll_timer.stop()

    # -------- build --------

    def _build(self) -> None:
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"KitchenScreen {{ background-color: {COLORS['bg_light']}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())
        root.addWidget(self._build_columns(), 1)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(SPACING["md"])

        title = QLabel("Кухня")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        h.addWidget(title)
        h.addStretch(1)

        self._cook_lbl = QLabel("")
        self._cook_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        h.addWidget(self._cook_lbl)

        # Sound on/off toggle
        self._sound_btn = QPushButton("🔔")
        self._sound_btn.setFixedSize(36, 36)
        self._sound_btn.setCheckable(True)
        self._sound_btn.setChecked(True)
        self._sound_btn.setCursor(Qt.PointingHandCursor)
        self._sound_btn.setToolTip("Звуковой alert при новой позиции")
        self._sound_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 14pt; padding: 0;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            f"QPushButton:checked {{"
            f"  background: #DCFCE7; border-color: {COLORS['success_green']};"
            f"}}"
        )
        self._sound_btn.toggled.connect(self._on_sound_toggled)
        h.addWidget(self._sound_btn)

        # Online dot
        self._online_lbl = QLabel("● Online")
        self._online_lbl.setStyleSheet(
            f"color: {COLORS['success_green']}; font-size: 10pt;"
        )
        h.addWidget(self._online_lbl)

        # Logout
        logout_btn = QPushButton("Выйти")
        logout_btn.setFixedHeight(36)
        logout_btn.setMinimumWidth(100)
        logout_btn.setCursor(Qt.PointingHandCursor)
        logout_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        logout_btn.clicked.connect(self.logout_requested.emit)
        h.addWidget(logout_btn)
        return bar

    def _build_columns(self) -> QWidget:
        wrapper = QWidget()
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        h.setSpacing(SPACING["md"])

        self._column_layouts: dict[str, QVBoxLayout] = {}
        self._column_counters: dict[str, QLabel] = {}

        for status, label, color, _btn_label, _action in COLUMNS:
            col = QFrame()
            col.setStyleSheet(
                f"QFrame {{"
                f"  background: {COLORS['bg_white']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: {RADIUS['md']}px;"
                f"}}"
            )
            cv = QVBoxLayout(col)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(0)

            # Заголовок колонки
            head = QFrame()
            head.setFixedHeight(48)
            head.setStyleSheet(
                f"background: {color}; border: none;"
                f" border-top-left-radius: {RADIUS['md']}px;"
                f" border-top-right-radius: {RADIUS['md']}px;"
            )
            hh = QHBoxLayout(head)
            hh.setContentsMargins(16, 0, 16, 0)
            head_label = QLabel(label)
            head_label.setStyleSheet(
                f"color: {COLORS['text_white']};"
                f" font-size: 14pt; font-weight: 700;"
                f" background: transparent; border: none;"
            )
            hh.addWidget(head_label)
            counter = QLabel("(0)")
            counter.setStyleSheet(
                f"color: {COLORS['text_white']}; font-size: 14pt;"
                f" font-weight: 700; background: transparent; border: none;"
            )
            hh.addStretch(1)
            hh.addWidget(counter)
            cv.addWidget(head)
            self._column_counters[status] = counter

            # Body — scrollable list of cards
            holder = QWidget()
            holder.setStyleSheet("background: transparent;")
            body_layout = QVBoxLayout(holder)
            body_layout.setContentsMargins(8, 8, 8, 8)
            body_layout.setSpacing(SPACING["sm"])
            body_layout.setAlignment(Qt.AlignTop)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet(
                f"QScrollArea {{ background: transparent; border: none; }}"
            )
            scroll.setWidget(holder)
            cv.addWidget(scroll, 1)
            self._column_layouts[status] = body_layout

            h.addWidget(col, 1)
        return wrapper

    # -------- render --------

    def _render(self) -> None:
        # Очистить колонки
        for layout in self._column_layouts.values():
            while layout.count():
                child = layout.takeAt(0)
                w = child.widget()
                if w:
                    w.deleteLater()

        by_status: dict[str, list[dict]] = {s: [] for s, *_ in COLUMNS}
        for it in self._items:
            st = it.get("kitchen_status")
            if st in by_status:
                by_status[st].append(it)

        # Sound alert: появилась новая позиция в колонке NEW
        new_ids = {int(i["id"]) for i in by_status.get("new", [])}
        new_arrived = new_ids - self._prev_new_ids
        if new_arrived and self._prev_new_ids and self._sound_enabled:
            self._play_alert()
        self._prev_new_ids = new_ids

        for status, _label, color, btn_label, action in COLUMNS:
            items = by_status[status]
            self._column_counters[status].setText(f"({len(items)})")
            layout = self._column_layouts[status]
            if not items:
                empty = QLabel("Пусто")
                empty.setAlignment(Qt.AlignCenter)
                empty.setStyleSheet(
                    f"color: {COLORS['text_secondary']};"
                    f" font-size: 11pt; font-style: italic;"
                    f" padding: 30px 0;"
                )
                layout.addWidget(empty)
                continue
            for it in items:
                layout.addWidget(self._build_card(it, color, btn_label, action))

    def _build_card(
        self, item: dict, accent: str, btn_label: str, action: str,
    ) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-left: 4px solid {accent};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(4)

        # 1-я строка: блюдо ×qty
        name = QLabel(
            f"{item.get('name_at_order', '?')}  ×{item.get('qty', 1)}"
        )
        name.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 13pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(name)

        # 2-я строка: стол + категория
        order_type = item.get("order_type") or "hall"
        if order_type == "takeaway":
            place = "С собой"
        elif order_type == "delivery":
            place = "Доставка"
        else:
            place = item.get("table_name") or "—"
        cat = item.get("category_name") or ""
        sub = QLabel(f"{place}  ·  {cat}".strip(" ·"))
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; border: none; background: transparent;"
        )
        v.addWidget(sub)

        # Заметка (если есть)
        note = (item.get("note") or "").strip()
        if note:
            note_lbl = QLabel(f"✎ {note}")
            note_lbl.setWordWrap(True)
            note_lbl.setStyleSheet(
                f"color: {COLORS['accent_orange']};"
                f" font-size: 10pt; font-weight: 600;"
                f" border: none; background: transparent;"
            )
            v.addWidget(note_lbl)

        # Время
        ago = self._fmt_age(item)
        if ago:
            time_lbl = QLabel(ago)
            time_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 9pt; font-style: italic;"
                f" border: none; background: transparent;"
            )
            v.addWidget(time_lbl)

        # Action button
        btn = QPushButton(btn_label)
        btn.setFixedHeight(36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {accent}; color: {COLORS['text_white']};"
            f"  border: none; border-radius: 6px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )
        btn.clicked.connect(
            lambda _c=False, iid=int(item["id"]), a=action: self._do_action(iid, a)
        )
        v.addWidget(btn)
        return card

    @staticmethod
    def _fmt_age(item: dict) -> str:
        """Сколько прошло с created_at / start_cooking_at / ready_at."""
        st = item.get("kitchen_status")
        ref = None
        if st == "new":
            ref = item.get("created_at")
        elif st == "cooking":
            ref = item.get("started_cooking_at") or item.get("created_at")
        elif st == "ready":
            ref = item.get("ready_at") or item.get("created_at")
        if not ref:
            return ""
        try:
            t = datetime.fromisoformat(str(ref).replace("Z", "+00:00"))
            now = datetime.now(tz.utc)
            delta = (now - t).total_seconds()
        except Exception:
            return ""
        if delta < 60:
            return "только что"
        if delta < 3600:
            return f"{int(delta // 60)} мин назад"
        return f"{int(delta // 3600)} ч назад"

    # -------- handlers --------

    def _do_action(self, item_id: int, action: str) -> None:
        try:
            self.state.client.post(
                f"/kitchen/items/{item_id}/{action}/", json={},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"{e.message}\n[{e.code}]",
            )
            return
        self.reload()

    def _on_sse_event(self, event_type: str, _payload: dict) -> None:
        """SSE: при kitchen.status_changed — обновляем список."""
        if event_type == "kitchen.status_changed":
            self.reload()

    def _on_sound_toggled(self, checked: bool) -> None:
        self._sound_enabled = bool(checked)
        # Меняем иконку: 🔔 включено / 🔕 выключено
        self._sound_btn.setText("🔔" if checked else "🔕")

    def _play_alert(self) -> None:
        """Системный beep при появлении новой позиции на кухне."""
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.beep()
        except Exception:
            pass
