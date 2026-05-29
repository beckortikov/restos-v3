"""Phase 8D — попап «Настройки склада для блюда».

Открывается из StopListDialog по ⚙. Два чекбокса:
- Учитывать техкарту (auto_consume) — POST /menu/items/{id}/toggle_tech_card/
- Продавать в минус (allow_oversell) — POST /menu/items/{id}/allow_oversell/

Сохранение немедленное (toggle по клику). «Закрыть» завершает диалог.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _ToggleEndpointWorker(QObject):
    success = Signal(str, dict)
    error = Signal(str, object)

    def __init__(
        self,
        client: ApiClient,
        item_id: int,
        endpoint: str,
        enabled: bool,
    ) -> None:
        super().__init__()
        self.client = client
        self.item_id = item_id
        self.endpoint = endpoint  # "toggle_tech_card" | "allow_oversell"
        self.enabled = enabled

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/menu/items/{self.item_id}/{self.endpoint}/",
                json={"enabled": self.enabled},
            )
            payload = data.get("data") if isinstance(data, dict) and "data" in data else data
            self.success.emit(
                self.endpoint, payload if isinstance(payload, dict) else {},
            )
        except ApiError as e:
            self.error.emit(self.endpoint, e)


from pos.resources.icons import qicon


class StopItemSettingsDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        item: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._item = dict(item)
        self._threads: list[QThread] = []

        self.setWindowTitle("Настройки блюда")
        self.setModal(True)
        self.setFixedWidth(460)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 16px;"
            f"}}"
        )
        self._build()

    def _build(self) -> None:
        # Main layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header (56px)
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-top-left-radius: 15px;"
            f"  border-top-right-radius: 15px;"
            f"}}"
        )
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(20, 0, 20, 0)

        head_title_layout = QHBoxLayout()
        head_title_layout.setSpacing(8)
        settings_icon = QLabel()
        settings_icon.setPixmap(qicon("settings", COLORS["accent_orange"], 20).pixmap(20, 20))
        settings_icon.setStyleSheet("border: none; background: transparent;")
        head_title_layout.addWidget(settings_icon)

        title = QLabel("Настройки блюда")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 13pt; font-weight: 700; border: none;"
        )
        head_title_layout.addWidget(title)
        head_lay.addLayout(head_title_layout)
        head_lay.addStretch(1)

        close_btn = QPushButton()
        close_btn.setFixedSize(30, 30)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 18))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: #F1F5F9; border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.reject)
        head_lay.addWidget(close_btn)
        root.addWidget(header)

        # 2. Body
        body = QWidget()
        body.setStyleSheet("border: none; background: transparent;")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(20, 20, 20, 20)
        body_lay.setSpacing(16)

        # Dish details box (aPlb3) - Light gray card
        dish_card = QFrame()
        dish_card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-radius: 8px;"
            f"  border: none;"
            f"}}"
        )
        dish_card_lay = QHBoxLayout(dish_card)
        dish_card_lay.setContentsMargins(12, 12, 12, 12)
        dish_card_lay.setSpacing(12)

        dish_icon = QLabel()
        dish_icon.setPixmap(qicon("utensils", COLORS["accent_orange"], 24).pixmap(24, 24))
        dish_icon.setStyleSheet("border: none; background: transparent;")
        dish_card_lay.addWidget(dish_icon)

        dish_text_lay = QVBoxLayout()
        dish_text_lay.setSpacing(2)
        dish_name = QLabel(self._item.get("name", "?"))
        dish_name.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 11pt; font-weight: 700; background: transparent;"
        )
        dish_name.setWordWrap(True)
        dish_text_lay.addWidget(dish_name)

        dish_meta = QLabel("Позиция из меню")
        dish_meta.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 9pt; background: transparent;"
        )
        dish_text_lay.addWidget(dish_meta)
        dish_card_lay.addLayout(dish_text_lay, 1)
        body_lay.addWidget(dish_card)

        # Sub-hint
        hint = QLabel("Эти настройки управляют тем, как блюдо взаимодействует со складом.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9.5pt; font-style: italic;"
        )
        body_lay.addWidget(hint)

        # Box 2 (SQzPD) - Checkbox "Учитывать техкарту" Wrapper Card
        tc_card = QFrame()
        tc_card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"}}"
        )
        tc_lay = QVBoxLayout(tc_card)
        tc_lay.setContentsMargins(14, 14, 14, 14)
        tc_lay.setSpacing(8)

        self._chk_tc = QCheckBox("Учитывать техкарту (списывать со склада)")
        self._chk_tc.setChecked(bool(self._item.get("auto_consume", True)))
        self._chk_tc.setStyleSheet(self._chk_qss())
        self._chk_tc.toggled.connect(self._on_tc_toggled)
        tc_lay.addWidget(self._chk_tc)

        tc_hint = QLabel(
            "Если выключено — блюдо не списывает ингредиенты при закрытии заказа "
            "и не уходит в авто-стоп при нехватке сырья.",
        )
        tc_hint.setWordWrap(True)
        tc_hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none; background: transparent; padding-left: 28px;"
        )
        tc_lay.addWidget(tc_hint)
        body_lay.addWidget(tc_card)

        # Box 3 (E3RVbl) - Checkbox "Продавать в минус" Wrapper Card
        os_card = QFrame()
        os_card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"}}"
        )
        os_lay = QVBoxLayout(os_card)
        os_lay.setContentsMargins(14, 14, 14, 14)
        os_lay.setSpacing(8)

        self._chk_os = QCheckBox("Продавать в минус (override авто-стопа)")
        self._chk_os.setChecked(bool(self._item.get("allow_oversell", False)))
        self._chk_os.setStyleSheet(self._chk_qss())
        self._chk_os.toggled.connect(self._on_os_toggled)
        os_lay.addWidget(self._chk_os)

        os_hint = QLabel(
            "Разрешает заказывать блюдо даже когда ингредиентов на складе нет. "
            "Используйте, если уверены, что повар сейчас приготовит из свежей заготовки.",
        )
        os_hint.setWordWrap(True)
        os_hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none; background: transparent; padding-left: 28px;"
        )
        os_lay.addWidget(os_hint)
        body_lay.addWidget(os_card)

        # Box 4 (LHbIz) - Amber Warning Card
        warn_card = QFrame()
        warn_card.setStyleSheet(
            f"QFrame {{"
            f"  background: #FEF3C720;"
            f"  border: 1px solid #FBBF24;"
            f"  border-left: 4px solid #FBBF24;"
            f"  border-radius: 8px;"
            f"}}"
        )
        warn_lay = QHBoxLayout(warn_card)
        warn_lay.setContentsMargins(12, 12, 12, 12)
        warn_lay.setSpacing(10)

        warn_icon = QLabel()
        warn_icon.setPixmap(qicon("alert-triangle", COLORS["warning_yellow"], 20).pixmap(20, 20))
        warn_icon.setStyleSheet("border: none; background: transparent;")
        warn_lay.addWidget(warn_icon)

        warn_text = QLabel(
            "Внимание! Разрешение продажи в минус может временно приводить к расхождениям "
            "и отрицательным остаткам сырья на складе."
        )
        warn_text.setWordWrap(True)
        warn_text.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 9pt; border: none; background: transparent;"
        )
        warn_lay.addWidget(warn_text, 1)
        body_lay.addWidget(warn_card)

        body_lay.addStretch(1)
        root.addWidget(body, 1)

        # 3. Footer (60px)
        footer = QFrame()
        footer.setFixedHeight(60)
        footer.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  border-bottom-left-radius: 15px;"
            f"  border-bottom-right-radius: 15px;"
            f"}}"
        )
        foot_lay = QHBoxLayout(footer)
        foot_lay.setContentsMargins(20, 0, 20, 0)
        foot_lay.addStretch(1)

        close = QPushButton("Готово")
        close.setFixedHeight(40)
        close.setMinimumWidth(120)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 8px;"
            f"  padding: 0 24px; font-size: 10.5pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        close.clicked.connect(self.accept)
        foot_lay.addWidget(close)
        root.addWidget(footer)

    def _chk_qss(self) -> str:
        return (
            f"QCheckBox {{"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 10.5pt; font-weight: 700;"
            f"  spacing: 10px;"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; }}"
            f"QCheckBox::indicator:unchecked {{"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: 4px; background: {COLORS['bg_white']};"
            f"}}"
            f"QCheckBox::indicator:checked {{"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"  border-radius: 4px; background: {COLORS['accent_orange']};"
            f"}}"
        )

    # -------- handlers --------

    def _on_tc_toggled(self, checked: bool) -> None:
        self._spawn("toggle_tech_card", checked)

    def _on_os_toggled(self, checked: bool) -> None:
        self._spawn("allow_oversell", checked)

    def _spawn(self, endpoint: str, enabled: bool) -> None:
        thread = QThread(self)
        worker = _ToggleEndpointWorker(
            self._client, int(self._item["id"]), endpoint, enabled,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_done)
        worker.error.connect(self._on_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_done(self, _endpoint: str, item: dict) -> None:
        if item:
            self._item.update(item)

    def _on_failed(self, endpoint: str, exc: ApiError) -> None:
        QMessageBox.warning(
            self, "Ошибка",
            f"Не удалось обновить «{endpoint}»: [{exc.code}] {exc.message}",
        )
        # Откатить чекбокс
        if endpoint == "toggle_tech_card":
            self._chk_tc.blockSignals(True)
            self._chk_tc.setChecked(bool(self._item.get("auto_consume", True)))
            self._chk_tc.blockSignals(False)
        elif endpoint == "allow_oversell":
            self._chk_os.blockSignals(True)
            self._chk_os.setChecked(bool(self._item.get("allow_oversell", False)))
            self._chk_os.blockSignals(False)
