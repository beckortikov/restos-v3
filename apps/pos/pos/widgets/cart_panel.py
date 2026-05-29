"""Корзина для MenuScreen — собирает выбранные блюда + total + submit-кнопка."""
from decimal import Decimal

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


class CartPanel(QFrame):
    """Сигналы:
        submit_requested() — main собирает items и шлёт POST /orders/ или /add_items/
        cancelled() — закрыть menu без отправки

    Public:
        add_item(menu_item: dict) — добавить блюдо или инкремент qty
        remove_item(menu_item_id) — удалить блюдо целиком
        change_qty(menu_item_id, delta) — изменить количество (delta=±1)
        clear()
        get_items() → list[{menu_item_id, qty}] для отправки
    """

    submit_requested = Signal()
    cancelled = Signal()
    # menu_item_id, current_note — главный экран открывает NotePickerDialog
    note_edit_requested = Signal(int, str)
    # «Бронирование» — пока корзина пуста и доступна для hall-стола.
    # MenuScreen ловит, возвращает на TablesScreen и показывает форму брони.
    reservation_requested = Signal()

    PANEL_WIDTH = 360

    def __init__(
        self,
        title: str = "Новый заказ",
        submit_label: str = "Отправить →",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("cartPanel")
        self.setFixedWidth(CartPanel.PANEL_WIDTH)
        self.setStyleSheet(
            f"#cartPanel {{"
            f"  background-color: {COLORS['bg_white']};"
            f"  border-left: 1px solid {COLORS['border_light']};"
            f"}}"
        )
        # (menu_item_id, note, modifier_ids_tuple) -> {item, qty, note,
        # modifier_ids: [int], modifiers: [{id, name, price_delta}]}.
        # Третий элемент ключа — отсортированный tuple modifier_ids — гарантирует
        # что одно и то же блюдо с разным набором модификаторов = разные строки.
        self._items: dict[tuple[int, str, tuple[int, ...]], dict] = {}
        self._title_text = title
        self._submit_label = submit_label
        # Показывать ли «Бронирование» при пустой корзине (только для hall).
        self._reservation_enabled: bool = False

        self._build()
        self._render_list()

    def set_reservation_enabled(self, enabled: bool) -> None:
        """Включить/выключить отображение «Бронирование» при пустой корзине."""
        self._reservation_enabled = bool(enabled)
        self._render_list()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("cartHeader")
        header.setStyleSheet(
            f"#cartHeader {{ background-color: {COLORS['accent_orange']}; }}"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        self._title = QLabel(self._title_text)
        self._title.setStyleSheet(
            f"color: {COLORS['text_white']}; font-size: 14pt; font-weight: 700;"
        )
        h.addWidget(self._title)
        h.addStretch(1)
        self._count_lbl = QLabel("0 поз.")
        self._count_lbl.setStyleSheet(
            f"color: rgba(255,255,255,0.85); font-size: 11pt;"
        )
        h.addWidget(self._count_lbl)
        v.addWidget(header)

        # List scrollable
        self._list_holder = QWidget()
        self._list_holder.setStyleSheet(f"background: {COLORS['bg_white']};")
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(4)
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

        # Total + buttons
        footer = QFrame()
        footer.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(16, 12, 16, 16)
        fv.setSpacing(SPACING["sm"])

        total_row = QHBoxLayout()
        total_row.setContentsMargins(0, 0, 0, 0)
        total_row.addWidget(QLabel("ИТОГО"))
        total_row.addStretch(1)
        self._total_lbl = QLabel("0.00 TJS")
        self._total_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 800;"
        )
        total_row.addWidget(self._total_lbl)
        for child in [total_row.itemAt(i).widget() for i in range(total_row.count())]:
            if isinstance(child, QLabel) and child.text() == "ИТОГО":
                child.setStyleSheet(
                    f"color: {COLORS['text_primary']};"
                    f" font-size: 13pt; font-weight: 700;"
                )
        fv.addLayout(total_row)

        self._submit_btn = QPushButton(self._submit_label)
        self._submit_btn.setFixedHeight(56)
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setEnabled(False)
        self._submit_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 13pt; font-weight: 700;"
            f"}}"
            f"QPushButton:pressed {{ background-color: {COLORS['accent_orange_pressed']}; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._submit_btn.clicked.connect(self.submit_requested.emit)
        fv.addWidget(self._submit_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel_btn.clicked.connect(self.cancelled.emit)
        fv.addWidget(cancel_btn)

        v.addWidget(footer)

    # -------- public API --------

    def add_item(
        self,
        menu_item: dict,
        note: str = "",
        modifier_ids: list[int] | None = None,
        modifiers: list[dict] | None = None,
    ) -> None:
        """Добавить блюдо в корзину.

        - note: текст комментария (snapshot шаблона `MenuItemNote.label`).
        - modifier_ids: ID выбранных модификаторов.
        - modifiers: snapshot выбранных опций
          [{"id", "name", "price_delta"}] — для отображения в карточке и
          подсчёта total. Если None — будет восстановлен по modifier_ids
          из menu_item["modifier_groups"] (для backward-compat).
        """
        mid = int(menu_item["id"])
        mids = sorted(int(x) for x in (modifier_ids or []))
        mod_tuple = tuple(mids)
        key = (mid, note or "", mod_tuple)
        if modifiers is None and mids:
            # Восстановить snapshot по menu_item.modifier_groups
            modifiers = []
            for g in menu_item.get("modifier_groups") or []:
                for m in g.get("modifiers") or []:
                    if int(m["id"]) in mids:
                        modifiers.append({
                            "id": int(m["id"]),
                            "name": m.get("name", ""),
                            "price_delta": str(m.get("price_delta") or "0"),
                        })
        if key in self._items:
            self._items[key]["qty"] += 1
        else:
            self._items[key] = {
                "item": menu_item, "qty": 1, "note": note or "",
                "modifier_ids": mids,
                "modifiers": list(modifiers or []),
            }
        self._render_list()

    def change_qty(
        self, menu_item_id: int, delta: int, note: str = "",
        modifier_ids: list[int] | None = None,
    ) -> None:
        mid = int(menu_item_id)
        mod_tuple = tuple(sorted(int(x) for x in (modifier_ids or [])))
        key = (mid, note or "", mod_tuple)
        if key not in self._items:
            return
        new_qty = self._items[key]["qty"] + delta
        if new_qty <= 0:
            del self._items[key]
        else:
            self._items[key]["qty"] = new_qty
        self._render_list()

    def remove_item(
        self, menu_item_id: int, note: str = "",
        modifier_ids: list[int] | None = None,
    ) -> None:
        mod_tuple = tuple(sorted(int(x) for x in (modifier_ids or [])))
        self._items.pop((int(menu_item_id), note or "", mod_tuple), None)
        self._render_list()

    def set_item_note(
        self, menu_item_id: int, old_note: str, new_note: str,
        modifier_ids: list[int] | None = None,
    ) -> None:
        """Изменить note у уже добавленной позиции, сохраняя её модификаторы.

        Если позиция с new_note + теми же modifier_ids уже была — qty объединяется.
        """
        mid = int(menu_item_id)
        mod_tuple = tuple(sorted(int(x) for x in (modifier_ids or [])))
        old_key = (mid, old_note or "", mod_tuple)
        new_key = (mid, new_note or "", mod_tuple)
        if old_key == new_key or old_key not in self._items:
            return
        entry = self._items.pop(old_key)
        entry["note"] = new_note or ""
        if new_key in self._items:
            self._items[new_key]["qty"] += entry["qty"]
        else:
            self._items[new_key] = entry
        self._render_list()

    def clear(self) -> None:
        self._items.clear()
        self._render_list()

    def get_items(self) -> list[dict]:
        out: list[dict] = []
        for key, data in self._items.items():
            entry: dict = {
                "menu_item_id": key[0],
                "qty": data["qty"],
                "note": data.get("note") or "",
            }
            mids = list(data.get("modifier_ids") or [])
            if mids:
                entry["modifier_ids"] = mids
            out.append(entry)
        return out

    def is_empty(self) -> bool:
        return not self._items

    def set_title(self, title: str) -> None:
        self._title_text = title
        self._title.setText(title)

    def set_submit_label(self, label: str) -> None:
        self._submit_label = label
        self._submit_btn.setText(label)

    # -------- internal --------

    def _render_list(self) -> None:
        # Очистить
        while self._list_layout.count():
            child = self._list_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if not self._items:
            empty = QLabel("Корзина пуста")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 11pt; padding: 24px 0;"
            )
            self._list_layout.addWidget(empty)
            # При пустой корзине и hall-столе показываем «Бронирование» —
            # кассир может передумать и забронировать вместо открытия заказа.
            if self._reservation_enabled:
                reserve_btn = QPushButton("Бронирование")
                reserve_btn.setFixedHeight(44)
                reserve_btn.setCursor(Qt.PointingHandCursor)
                reserve_btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {COLORS['bg_white']};"
                    f"  color: {COLORS['primary_blue']};"
                    f"  border: 1.5px solid {COLORS['primary_blue']};"
                    f"  border-radius: {RADIUS['sm']}px;"
                    f"  padding: 0 16px; font-size: 12pt; font-weight: 600;"
                    f"}}"
                    f"QPushButton:hover {{ background: #EFF6FF; }}"
                )
                reserve_btn.clicked.connect(self.reservation_requested.emit)
                wrap = QFrame()
                wv = QVBoxLayout(wrap)
                wv.setContentsMargins(12, 0, 12, 0)
                wv.addWidget(reserve_btn)
                self._list_layout.addWidget(wrap)
        else:
            for key, data in self._items.items():
                mid, note, _mods = key
                self._list_layout.addWidget(
                    self._build_row(mid, data, note=note)
                )

        # Update count + total — учитываем модификаторы.
        def _row_total(d: dict) -> Decimal:
            base = Decimal(str(d["item"].get("price", "0")))
            mods_delta = sum(
                (Decimal(str(m.get("price_delta") or "0"))
                 for m in d.get("modifiers") or []),
                Decimal("0"),
            )
            return (base + mods_delta) * d["qty"]

        total = sum((_row_total(d) for d in self._items.values()), Decimal("0"))
        count = sum(d["qty"] for d in self._items.values())
        self._count_lbl.setText(f"{count} поз.")
        self._total_lbl.setText(f"{total:.2f} TJS")
        self._submit_btn.setEnabled(bool(self._items))

    def _build_row(self, mid: int, data: dict, note: str = "") -> QWidget:
        item = data["item"]
        qty = data["qty"]

        row = QFrame()
        row.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        v = QVBoxLayout(row)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)

        # Top row — название + qty controls + сумма
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        name = QLabel(item.get("name", ""))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; border: none;"
            f" background: transparent;"
        )
        name.setWordWrap(True)
        h.addWidget(name, 1)

        minus = QPushButton()
        minus.setFixedSize(28, 28)
        minus.setIcon(qicon("x", COLORS["text_secondary"], 14))
        minus.setIconSize(QSize(14, 14))
        minus.setCursor(Qt.PointingHandCursor)
        minus.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 4px;"
            f"}}"
        )
        mids_for_signals = list(data.get("modifier_ids") or [])
        minus.clicked.connect(
            lambda _checked=False, m=mid, n=note, ms=mids_for_signals:
            self.change_qty(m, -1, n, ms)
        )
        h.addWidget(minus)

        qty_lbl = QLabel(f"×{qty}")
        qty_lbl.setAlignment(Qt.AlignCenter)
        qty_lbl.setMinimumWidth(28)
        qty_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 700; border: none;"
            f" background: transparent;"
        )
        h.addWidget(qty_lbl)

        plus = QPushButton()
        plus.setFixedSize(28, 28)
        plus.setIcon(qicon("plus", COLORS["accent_orange"], 14))
        plus.setIconSize(QSize(14, 14))
        plus.setCursor(Qt.PointingHandCursor)
        plus.setStyleSheet(minus.styleSheet())
        plus.clicked.connect(
            lambda _checked=False, m=mid, n=note, ms=mids_for_signals:
            self.change_qty(m, 1, n, ms)
        )
        h.addWidget(plus)

        mods_delta = sum(
            (Decimal(str(m.get("price_delta") or "0"))
             for m in data.get("modifiers") or []),
            Decimal("0"),
        )
        sub = (Decimal(str(item.get("price", "0"))) + mods_delta) * qty
        sub_lbl = QLabel(f"{sub:.2f}")
        sub_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sub_lbl.setMinimumWidth(56)
        sub_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 700; border: none;"
            f" background: transparent;"
        )
        h.addWidget(sub_lbl)
        v.addLayout(h)

        # Модификаторы — серые подписи под названием блюда
        for m in data.get("modifiers") or []:
            try:
                d = Decimal(str(m.get("price_delta") or "0"))
            except Exception:
                d = Decimal("0")
            if d == 0:
                txt = f"  • {m.get('name', '')}"
            else:
                sign = "+" if d > 0 else "−"
                txt = f"  • {m.get('name', '')} ({sign}{abs(d)})"
            mod_lbl = QLabel(txt)
            mod_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                f" font-size: 9pt; border: none; background: transparent;"
            )
            v.addWidget(mod_lbl)

        # Bottom row — note (clickable, italic если пусто)
        note_btn = QPushButton(
            f"  ✎ {note}" if note else "  ✎ Добавить комментарий"
        )
        note_btn.setFlat(True)
        note_btn.setCursor(Qt.PointingHandCursor)
        note_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['accent_orange'] if note else COLORS['text_secondary']};"
            f"  border: none;"
            f"  font-size: 10pt;"
            f"  font-style: {'normal' if note else 'italic'};"
            f"  font-weight: {600 if note else 400};"
            f"  text-align: left;"
            f"  padding: 2px 0;"
            f"}}"
            f"QPushButton:hover {{ color: {COLORS['accent_orange']}; }}"
        )
        note_btn.clicked.connect(
            lambda _c=False, m=mid, n=note, ms=mids_for_signals:
            self.note_edit_requested.emit(m, n)
        )
        v.addWidget(note_btn)
        return row
