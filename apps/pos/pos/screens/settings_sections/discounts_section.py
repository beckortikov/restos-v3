"""Frame 22 — Настройки / Скидки и сервис.

Две секции:
1. «Скидки» — список карточек с процент-бейджем + toggle.
2. «Сервисный сбор» — одна карточка с pill-процентом + toggle.

Никакого хардкода — всё из API /discounts/, дефолты сидятся сервером.
"""
from __future__ import annotations

from decimal import Decimal

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
from pos.resources.icons import qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.widgets.toggle_switch import ToggleSwitch

# Цвет бейджа по sort_order (циклически) — пастельные подложки.
_BADGE_PALETTE = [
    {"bg": "#DCFCE7", "fg": COLORS["success_green"]},
    {"bg": "#DBEAFE", "fg": COLORS["primary_blue"]},
    {"bg": "#FEF3C7", "fg": "#D97706"},
    {"bg": "#F3E8FF", "fg": "#7C3AED"},
]


class _ListWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/discounts/")
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            self.success.emit(list(items))
        except ApiError as e:
            self.error.emit(e)


class _ToggleWorker(QObject):
    success = Signal(int, dict)
    error = Signal(int, object)

    def __init__(self, client: ApiClient, item_id: int, is_active: bool) -> None:
        super().__init__()
        self.client = client
        self.item_id = item_id
        self.is_active = is_active

    def run(self) -> None:
        try:
            data = self.client.request(
                "PATCH",
                f"/discounts/{self.item_id}/",
                json={"is_active": self.is_active},
                idempotent=True,
            )
            self.success.emit(self.item_id, data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(self.item_id, e)


class DiscountsSection(QWidget):
    """Frame 22."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"DiscountsSection {{ background: {COLORS['bg_light']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Header
        head = QHBoxLayout()
        title = QLabel("Скидки и сервис")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        head.addWidget(title)
        head.addStretch(1)

        add_btn = QPushButton("  + Добавить скидку")
        add_btn.setFixedHeight(40)
        add_btn.setMinimumWidth(180)
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

        # Holder со скроллом
        self._content_holder = QWidget()
        self._content_layout = QVBoxLayout(self._content_holder)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(SPACING["lg"])
        self._content_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._content_holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)

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

    def _on_loaded(self, items: list) -> None:
        self._items = sorted(
            list(items),
            key=lambda d: (d.get("type", ""), int(d.get("sort_order", 0)), d.get("name", "")),
        )
        self._render()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось загрузить скидки: {exc.message}"
        )
        self._items = []
        self._render()

    def _render(self) -> None:
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        discounts = [d for d in self._items if d.get("type") == "discount"]
        services = [d for d in self._items if d.get("type") == "service"]

        # Section 1: Скидки
        self._content_layout.addWidget(self._section_label("Скидки"))
        if discounts:
            for i, d in enumerate(discounts):
                self._content_layout.addWidget(self._build_discount_card(d, idx=i))
        else:
            self._content_layout.addWidget(self._empty_label("Скидок пока нет"))

        # Section 2: Сервисный сбор
        self._content_layout.addWidget(self._section_label("Сервисный сбор"))
        if services:
            for d in services:
                self._content_layout.addWidget(self._build_service_card(d))
        else:
            self._content_layout.addWidget(self._empty_label("Сервисный сбор не настроен"))

    def _section_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        return l

    def _empty_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setAlignment(Qt.AlignCenter)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12pt; font-style: italic;"
            f" padding: 24px 0; background: {COLORS['bg_white']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['md']}px;"
        )
        return l

    def _build_discount_card(self, d: dict, *, idx: int) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        h = QHBoxLayout(card)
        h.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        h.setSpacing(SPACING["md"])

        palette = _BADGE_PALETTE[idx % len(_BADGE_PALETTE)]

        # Бейдж 48×48 с процентом
        badge = QFrame()
        badge.setFixedSize(48, 48)
        badge.setStyleSheet(
            f"QFrame {{"
            f"  background: {palette['bg']};"
            f"  border: none; border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        bl = QHBoxLayout(badge)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setAlignment(Qt.AlignCenter)
        try:
            value = Decimal(str(d.get("value", "0") or "0"))
        except Exception:
            value = Decimal("0")
        suffix = "%" if d.get("kind") == "percent" else ""
        # форматируем без лишних нулей: 10.00 → "10"
        val_str = f"{value:g}{suffix}"
        val_lbl = QLabel(val_str)
        val_lbl.setStyleSheet(
            f"color: {palette['fg']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        bl.addWidget(val_lbl)
        h.addWidget(badge)

        # Text col
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(d.get("name", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(name)
        desc = QLabel(d.get("description") or "")
        desc.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(desc)
        h.addLayout(text_col, 1)

        toggle = ToggleSwitch(checked=bool(d.get("is_active", True)))
        toggle.toggled_changed.connect(
            lambda checked, did=int(d["id"]): self._on_toggle(did, checked)
        )
        h.addWidget(toggle)
        return card

    def _build_service_card(self, d: dict) -> QWidget:
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

        # Сервисная иконка hand-coins
        icon_box = QFrame()
        icon_box.setFixedSize(48, 48)
        icon_box.setStyleSheet(
            "QFrame { background: #F3E8FF; border: none; border-radius: 12px; }"
        )
        ibl = QHBoxLayout(icon_box)
        ibl.setContentsMargins(0, 0, 0, 0)
        ibl.setAlignment(Qt.AlignCenter)
        icon = QLabel()
        icon.setPixmap(qpixmap("hand-coins", "#7C3AED", 24))
        icon.setStyleSheet("background: transparent; border: none;")
        ibl.addWidget(icon)
        h.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(d.get("name", "Сервисный сбор"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(name)
        desc = QLabel(d.get("description") or "Автоматически добавляется к каждому заказу")
        desc.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(desc)
        h.addLayout(text_col, 1)

        # Pill с процентом
        try:
            value = Decimal(str(d.get("value", "0") or "0"))
        except Exception:
            value = Decimal("0")
        pct_text = f"{value:g}%" if d.get("kind") == "percent" else f"{value} TJS"
        pill_btn = QPushButton(pct_text)
        pill_btn.setFixedHeight(36)
        pill_btn.setMinimumWidth(72)
        pill_btn.setCursor(Qt.PointingHandCursor)
        pill_btn.setToolTip("Изменить процент")
        pill_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        pill_btn.clicked.connect(lambda _c=False, dd=d: self._on_edit(dd))
        h.addWidget(pill_btn)

        toggle = ToggleSwitch(checked=bool(d.get("is_active", True)))
        toggle.toggled_changed.connect(
            lambda checked, did=int(d["id"]): self._on_toggle(did, checked)
        )
        h.addWidget(toggle)
        return card

    # -------- handlers --------

    def _on_add(self) -> None:
        from pos.screens.settings_sections.discount_edit_dialog import DiscountEditDialog

        dlg = DiscountEditDialog(client=self._client, discount=None, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_edit(self, d: dict) -> None:
        from pos.screens.settings_sections.discount_edit_dialog import DiscountEditDialog

        dlg = DiscountEditDialog(client=self._client, discount=d, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.reload()

    def _on_toggle(self, item_id: int, is_active: bool) -> None:
        thread = QThread(self)
        worker = _ToggleWorker(self._client, item_id, is_active)
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

    def _on_toggle_done(self, item_id: int, data: dict) -> None:
        for i, d in enumerate(self._items):
            if int(d["id"]) == int(item_id):
                self._items[i] = {**d, **data}
                break

    def _on_toggle_failed(self, _item_id: int, exc: ApiError) -> None:
        QMessageBox.warning(self, "Ошибка", f"Не удалось обновить: {exc.message}")
        self.reload()
