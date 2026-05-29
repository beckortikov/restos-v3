"""Раздел «Общие» в настройках — параметры ресторана.

Read-only карточка с данными ресторана (имя, адрес, телефон, валюта,
тайм-зона, PIN lock timeout). Редактирование — Phase 2 через owner-dashboard.
В POS-кассе кассир их не меняет.

Источник: GET /auth/me/ — там и user, и restaurant (см. apps/users/views.py).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _MeWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            data = self.client.get("/auth/me/")
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class GeneralSection(QWidget):
    """Read-only restaurant + user info."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._threads: list[QThread] = []
        self._data: dict = {}
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"GeneralSection {{ background: {COLORS['bg_light']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])
        v.setAlignment(Qt.AlignTop)

        title = QLabel("Общие")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(title)

        # Карточка ресторана
        self._resto_card = self._info_card("Ресторан")
        v.addWidget(self._resto_card)

        # Карточка «Печать чеков» — редактируемая (receipt_copies)
        self._print_card = self._build_print_settings_card()
        v.addWidget(self._print_card)

        # Карточка «Кухня» — toggle kitchen_enabled
        self._kitchen_card = self._build_kitchen_settings_card()
        v.addWidget(self._kitchen_card)

        # Карточка «Склад» — tech_cards_enabled + supply_allow_negative (Phase 8B)
        self._stock_card = self._build_stock_settings_card()
        v.addWidget(self._stock_card)

        # Карточка «Подтверждение менеджера» — порог суммы для override
        self._override_card = self._build_override_settings_card()
        v.addWidget(self._override_card)

        # Карточка «Чек» — кастомизация header_extra/footer + cash drawer
        self._receipt_card = self._build_receipt_customization_card()
        v.addWidget(self._receipt_card)

        # Карточка кассира (текущий вход)
        self._user_card = self._info_card("Текущий пользователь")
        v.addWidget(self._user_card)

        note = QLabel(
            "Изменение параметров ресторана — через owner-dashboard (Phase 2). "
            "В кассе они read-only."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(note)

    def _build_print_settings_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        head = QLabel("Печать чеков")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(SPACING["md"])
        lbl = QLabel("Кол-во копий чека")
        lbl.setFixedWidth(220)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        row.addWidget(lbl)

        self._copies_spin = QSpinBox()
        self._copies_spin.setMinimum(1)
        self._copies_spin.setMaximum(5)
        self._copies_spin.setValue(1)
        self._copies_spin.setFixedHeight(36)
        self._copies_spin.setMinimumWidth(120)
        self._copies_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 10px; font-size: 12pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
        )
        row.addWidget(self._copies_spin)
        row.addStretch(1)

        self._save_btn = QPushButton("Сохранить")
        self._save_btn.setFixedHeight(36)
        self._save_btn.setMinimumWidth(140)
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #DC6803; }}"
        )
        self._save_btn.clicked.connect(self._on_save_print_settings)
        row.addWidget(self._save_btn)
        v.addLayout(row)

        hint = QLabel(
            "1 — только гостю; 2 — гость + кассир; 3+ — для бухгалтерии. "
            "Применяется к будущим заказам."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(hint)
        return card

    def _build_kitchen_settings_card(self) -> QFrame:
        from PySide6.QtWidgets import QCheckBox

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        head = QLabel("Кухня (KDS)")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(SPACING["md"])
        self._kitchen_chk = QCheckBox("Использовать KDS-канбан для поваров")
        self._kitchen_chk.setStyleSheet(
            f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
        )
        row.addWidget(self._kitchen_chk)
        row.addStretch(1)

        save_btn = QPushButton("Сохранить")
        save_btn.setFixedHeight(36)
        save_btn.setMinimumWidth(140)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #DC6803; }}"
        )
        save_btn.clicked.connect(self._on_save_kitchen_settings)
        row.addWidget(save_btn)
        v.addLayout(row)

        hint = QLabel(
            "Если выключено — позиции заказа создаются сразу как «Готово» "
            "(маленькое кафе без отдельного повара). Если включено — повара "
            "видят канбан и сами проводят позиции по статусам."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(hint)
        return card

    def _build_stock_settings_card(self) -> QFrame:
        from PySide6.QtWidgets import QCheckBox

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        head = QLabel("Склад")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(head)

        self._techcards_chk = QCheckBox("Учитывать склад автоматически (автосписание по техкартам)")
        self._techcards_chk.setStyleSheet(
            f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
        )
        v.addWidget(self._techcards_chk)

        self._supply_neg_chk = QCheckBox("Разрешать выдачу хозтоваров даже при нулевом остатке")
        self._supply_neg_chk.setStyleSheet(
            f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
        )
        v.addWidget(self._supply_neg_chk)

        row = QHBoxLayout()
        row.addStretch(1)
        save_btn = QPushButton("Сохранить")
        save_btn.setFixedHeight(36)
        save_btn.setMinimumWidth(140)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #DC6803; }}"
        )
        save_btn.clicked.connect(self._on_save_stock_settings)
        row.addWidget(save_btn)
        v.addLayout(row)

        hint = QLabel(
            "Когда учёт склада выключен — при закрытии заказа ингредиенты "
            "НЕ списываются автоматически. Используйте, если только начали "
            "вести склад и техкарты ещё не заведены."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(hint)
        return card

    def _on_save_stock_settings(self) -> None:
        body = {
            "tech_cards_enabled": bool(self._techcards_chk.isChecked()),
            "supply_allow_negative": bool(self._supply_neg_chk.isChecked()),
        }
        try:
            self._client.request("PATCH", "/restaurant/", json=body)
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось сохранить:\n{e.message}\n[{e.code}]",
            )
            return
        QMessageBox.information(self, "Сохранено", "Настройки склада обновлены")
        self.reload()

    def _on_save_kitchen_settings(self) -> None:
        enabled = bool(self._kitchen_chk.isChecked())
        try:
            self._client.request(
                "PATCH", "/restaurant/", json={"kitchen_enabled": enabled},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось сохранить:\n{e.message}\n[{e.code}]",
            )
            return
        QMessageBox.information(
            self, "Сохранено",
            f"KDS-канбан {'включён' if enabled else 'выключен'}",
        )
        self.reload()

    def _build_override_settings_card(self) -> QFrame:
        from PySide6.QtWidgets import QLineEdit

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        head = QLabel("Подтверждение менеджера (override)")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(SPACING["md"])
        lbl = QLabel("Порог суммы (TJS)")
        lbl.setFixedWidth(220)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        row.addWidget(lbl)

        self._override_input = QLineEdit()
        self._override_input.setPlaceholderText("0.00 = без override")
        self._override_input.setFixedHeight(36)
        self._override_input.setMinimumWidth(140)
        self._override_input.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 12pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
        )
        row.addWidget(self._override_input)
        row.addStretch(1)

        save_btn = QPushButton("Сохранить")
        save_btn.setFixedHeight(36)
        save_btn.setMinimumWidth(140)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #DC6803; }}"
        )
        save_btn.clicked.connect(self._on_save_override_settings)
        row.addWidget(save_btn)
        v.addLayout(row)

        hint = QLabel(
            "Отмена заказа на сумму >= порога потребует ввода PIN-а менеджера. "
            "0 = всегда без override (только manager-роль может отменять напрямую)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(hint)
        return card

    def _on_save_override_settings(self) -> None:
        from decimal import Decimal, InvalidOperation

        raw = (self._override_input.text() or "0").strip().replace(",", ".")
        try:
            v = Decimal(raw)
            if v < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            QMessageBox.warning(
                self, "Ошибка", "Введите неотрицательное число (например, 1000.00).",
            )
            return
        try:
            self._client.request(
                "PATCH", "/restaurant/",
                json={"manager_override_threshold_tjs": str(v)},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось сохранить:\n{e.message}\n[{e.code}]",
            )
            return
        QMessageBox.information(
            self, "Сохранено",
            f"Порог manager-override: {v} TJS",
        )
        self.reload()

    def _build_receipt_customization_card(self) -> QFrame:
        from PySide6.QtWidgets import QCheckBox, QTextEdit

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        head = QLabel("Кастомизация чека")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(head)

        # Header extra
        h_lbl = QLabel("Доп. строки шапки (после name/address/phone)")
        h_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(h_lbl)
        self._header_extra_input = QTextEdit()
        self._header_extra_input.setPlaceholderText(
            "ИНН 123456789\nЛицензия №42 от 01.01.2026"
        )
        self._header_extra_input.setFixedHeight(60)
        self._header_extra_input.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 6px 10px; font-size: 11pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
        )
        v.addWidget(self._header_extra_input)

        # Footer
        f_lbl = QLabel("Подвал чека")
        f_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        v.addWidget(f_lbl)
        self._footer_input = QTextEdit()
        self._footer_input.setPlaceholderText(
            "Спасибо за визит!\nWi-Fi: GUEST / 12345"
        )
        self._footer_input.setFixedHeight(60)
        self._footer_input.setStyleSheet(self._header_extra_input.styleSheet())
        v.addWidget(self._footer_input)

        # Cash drawer toggle
        self._cash_drawer_chk = QCheckBox(
            "Открывать денежный ящик автоматически после печати чека"
        )
        self._cash_drawer_chk.setStyleSheet(
            f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
        )
        v.addWidget(self._cash_drawer_chk)

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Сохранить")
        save_btn.setFixedHeight(36)
        save_btn.setMinimumWidth(140)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #DC6803; }}"
        )
        save_btn.clicked.connect(self._on_save_receipt_settings)
        save_row.addWidget(save_btn)
        v.addLayout(save_row)
        return card

    def _on_save_receipt_settings(self) -> None:
        body = {
            "receipt_header_extra": self._header_extra_input.toPlainText().strip(),
            "receipt_footer": self._footer_input.toPlainText().strip() or "Спасибо за визит!",
            "auto_open_cash_drawer": self._cash_drawer_chk.isChecked(),
        }
        try:
            self._client.request("PATCH", "/restaurant/", json=body)
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось сохранить:\n{e.message}\n[{e.code}]",
            )
            return
        QMessageBox.information(
            self, "Сохранено", "Настройки чека обновлены",
        )
        self.reload()

    def _on_save_print_settings(self) -> None:
        copies = int(self._copies_spin.value())
        try:
            self._client.request(
                "PATCH", "/restaurant/", json={"receipt_copies": copies},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось сохранить:\n{e.message}\n[{e.code}]",
            )
            return
        QMessageBox.information(
            self, "Сохранено",
            f"Кол-во копий чека: {copies}",
        )
        self.reload()

    def _info_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        head = QLabel(title)
        head.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(head)

        body = QFrame()
        body.setStyleSheet("background: transparent; border: none;")
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(0, 0, 0, 0)
        body_v.setSpacing(SPACING["sm"])
        v.addWidget(body)

        # Сохраним layout чтобы наполнить позже
        card._body = body_v  # type: ignore[attr-defined]
        return card

    def _kv_row(self, label: str, value: str) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        l = QLabel(label)
        l.setFixedWidth(180)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
            f" border: none; background: transparent;"
        )
        h.addWidget(l)

        v = QLabel(value or "—")
        v.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 500;"
            f" border: none; background: transparent;"
        )
        v.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        v.setWordWrap(True)
        h.addWidget(v, 1)
        return row

    # -------- public --------

    def reload(self) -> None:
        thread = QThread(self)
        worker = _MeWorker(self._client)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_loaded)
        worker.error.connect(self._on_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_loaded(self, data: dict) -> None:
        self._data = data or {}
        self._render()

    def _on_error(self, _exc: ApiError) -> None:
        self._data = {}
        self._render()

    def _render(self) -> None:
        # Очистить body карточек
        for card in (self._resto_card, self._user_card):
            body = getattr(card, "_body")
            while body.count():
                child = body.takeAt(0)
                w = child.widget()
                if w:
                    w.deleteLater()

        resto = self._data.get("restaurant") or {}
        resto_body = self._resto_card._body  # type: ignore[attr-defined]
        resto_body.addWidget(self._kv_row("Название", resto.get("name", "—")))
        resto_body.addWidget(self._kv_row("Адрес", resto.get("address", "—")))
        resto_body.addWidget(self._kv_row("Телефон", resto.get("phone", "—")))
        resto_body.addWidget(self._kv_row("Валюта", resto.get("currency", "—")))
        resto_body.addWidget(self._kv_row("Часовой пояс", resto.get("timezone", "—")))
        resto_body.addWidget(
            self._kv_row(
                "PIN lock timeout",
                f"{resto.get('pin_lock_timeout_min', '—')} мин",
            )
        )

        # Заполняем редактируемые поля
        if hasattr(self, "_copies_spin"):
            try:
                self._copies_spin.setValue(int(resto.get("receipt_copies") or 1))
            except (TypeError, ValueError):
                self._copies_spin.setValue(1)
        if hasattr(self, "_kitchen_chk"):
            self._kitchen_chk.setChecked(bool(resto.get("kitchen_enabled", True)))
        if hasattr(self, "_override_input"):
            self._override_input.setText(
                str(resto.get("manager_override_threshold_tjs") or "0")
            )
        if hasattr(self, "_header_extra_input"):
            self._header_extra_input.setPlainText(
                resto.get("receipt_header_extra") or ""
            )
        if hasattr(self, "_footer_input"):
            self._footer_input.setPlainText(
                resto.get("receipt_footer") or "Спасибо за визит!"
            )
        if hasattr(self, "_cash_drawer_chk"):
            self._cash_drawer_chk.setChecked(
                bool(resto.get("auto_open_cash_drawer", False))
            )
        if hasattr(self, "_techcards_chk"):
            self._techcards_chk.setChecked(
                bool(resto.get("tech_cards_enabled", True))
            )
        if hasattr(self, "_supply_neg_chk"):
            self._supply_neg_chk.setChecked(
                bool(resto.get("supply_allow_negative", False))
            )

        user = self._data.get("user") or {}
        user_body = self._user_card._body  # type: ignore[attr-defined]
        user_body.addWidget(self._kv_row("Логин", user.get("username", "—")))
        user_body.addWidget(self._kv_row("Полное имя", user.get("full_name", "—")))
        role_label = {"cashier": "Кассир", "waiter": "Официант"}.get(
            user.get("role", ""), user.get("role", "—")
        )
        user_body.addWidget(self._kv_row("Роль", role_label))
