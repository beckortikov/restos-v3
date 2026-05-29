"""Frame 21 — Настройки / Способы оплаты.

Список способов оплаты с iOS-toggle для каждого + кнопка «+ Добавить».
Никакого хардкода — список из API /payment_providers/, дефолты сидятся
сервером для каждого ресторана.
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
from pos.resources.icons import qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.widgets.toggle_switch import ToggleSwitch


# Стилизация по типу провайдера: пастельный bg + цветная иконка.
KIND_STYLE: dict[str, dict] = {
    "cash": {
        "icon": "banknote", "bg": "#DCFCE7", "fg": COLORS["success_green"],
    },
    "card": {
        "icon": "credit-card", "bg": "#DBEAFE", "fg": COLORS["primary_blue"],
    },
    "qr": {
        "icon": "qr-code", "bg": "#F3E8FF", "fg": "#7C3AED",
    },
    "wallet": {
        "icon": "smartphone", "bg": "#FEF3C7", "fg": "#D97706",
    },
    "transfer": {
        "icon": "credit-card", "bg": "#DBEAFE", "fg": COLORS["primary_blue"],
    },
}
KIND_LABELS = {
    "cash": "Наличные", "card": "Банковская карта", "qr": "QR-оплата",
    "wallet": "Мобильный кошелёк", "transfer": "Перевод",
}


class _ListWorker(QObject):
    success = Signal(list)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/payment_providers/")
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
                f"/payment_providers/{self.item_id}/",
                json={"is_active": self.is_active},
                idempotent=True,
            )
            self.success.emit(self.item_id, data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(self.item_id, e)


class PaymentsSection(QWidget):
    """Frame 21. Используется внутри SettingsScreen QStackedWidget."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._threads: list[QThread] = []
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"PaymentsSection {{ background: {COLORS['bg_light']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])

        # Header
        head = QHBoxLayout()
        title = QLabel("Способы оплаты")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        head.addWidget(title)
        head.addStretch(1)

        add_btn = QPushButton("  + Добавить")
        add_btn.setFixedHeight(40)
        add_btn.setMinimumWidth(140)
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
        scroll.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }}")
        scroll.setWidget(self._list_holder)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(scroll, 1)

        self._empty_label = QLabel("Способов оплаты ещё нет — добавьте первый")
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
            key=lambda p: (int(p.get("sort_order", 0)), p.get("name", "")),
        )
        self._render()

    def _on_load_error(self, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось загрузить способы: {exc.message}"
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
        for p in self._items:
            self._list_layout.addWidget(self._build_card(p))

    def _build_card(self, p: dict) -> QWidget:
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

        kind = p.get("kind", "card")
        style = KIND_STYLE.get(kind, KIND_STYLE["card"])

        # iconBox 48×48 с пастельным фоном
        icon_box = QFrame()
        icon_box.setFixedSize(48, 48)
        icon_box.setStyleSheet(
            f"QFrame {{"
            f"  background: {style['bg']};"
            f"  border: none; border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        ibl = QHBoxLayout(icon_box)
        ibl.setContentsMargins(0, 0, 0, 0)
        ibl.setAlignment(Qt.AlignCenter)
        icon = QLabel()
        icon.setPixmap(qpixmap(style["icon"], style["fg"], 24))
        icon.setStyleSheet("background: transparent; border: none;")
        ibl.addWidget(icon)
        h.addWidget(icon_box)

        # text col
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        name = QLabel(p.get("name", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(name)

        desc_parts: list[str] = []
        if p.get("description"):
            desc_parts.append(p["description"])
        try:
            from decimal import Decimal
            comm = Decimal(str(p.get("commission_pct") or "0"))
            if comm > 0:
                desc_parts.append(f"Комиссия: {comm}%")
        except Exception:
            pass
        desc = QLabel(" • ".join(desc_parts) if desc_parts else KIND_LABELS.get(kind, ""))
        desc.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        text_col.addWidget(desc)
        h.addLayout(text_col, 1)

        # Toggle
        toggle = ToggleSwitch(checked=bool(p.get("is_active", True)))
        toggle.toggled_changed.connect(
            lambda checked, pid=int(p["id"]): self._on_toggle(pid, checked)
        )
        h.addWidget(toggle)
        return card

    # -------- handlers --------

    def _on_add(self) -> None:
        from pos.screens.settings_sections.payment_edit_dialog import PaymentEditDialog

        dlg = PaymentEditDialog(client=self._client, provider=None, parent=self)
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
        # обновить локально
        for i, p in enumerate(self._items):
            if int(p["id"]) == int(item_id):
                self._items[i] = {**p, **data}
                break

    def _on_toggle_failed(self, _item_id: int, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось обновить: {exc.message}"
        )
        self.reload()  # откат UI к серверу
