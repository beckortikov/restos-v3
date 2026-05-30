"""Раздел «О системе» в настройках — версия, контакты, ссылки."""
from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING

# Версия приложения. SA-7 — синхронизируется с pos.main.APP_VERSION (один источник).
try:
    from pos.main import APP_VERSION
except Exception:
    APP_VERSION = "0.1.0"
APP_BUILD = "release"
SUPPORT_EMAIL = "support@restos.example"
SUPPORT_PHONE = "+992 900 00 00 00"


class AboutSection(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"AboutSection {{ background: {COLORS['bg_light']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])
        v.setAlignment(Qt.AlignTop)

        title = QLabel("О системе")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        v.addWidget(title)

        # App version card + update button
        v.addWidget(self._info_card("RestOS — Кассир", [
            ("Версия", APP_VERSION),
            ("Сборка", APP_BUILD),
            ("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
            ("PySide6", pyside_version),
            ("Платформа", f"{platform.system()} {platform.release()}"),
        ]))

        # SA-7 — Кнопка ручной проверки обновлений
        update_row = QHBoxLayout()
        update_row.addStretch(1)
        check_btn = QPushButton("Проверить обновления")
        check_btn.setFixedHeight(40)
        check_btn.setMinimumWidth(220)
        check_btn.setCursor(Qt.PointingHandCursor)
        check_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #B85812; }}"
        )
        check_btn.clicked.connect(self._on_check_update)
        update_row.addWidget(check_btn)
        v.addLayout(update_row)

        # Support card
        v.addWidget(self._info_card("Поддержка", [
            ("E-mail", SUPPORT_EMAIL),
            ("Телефон", SUPPORT_PHONE),
            ("Документация", "docs.restos.example (Phase 5+)"),
        ]))

        # License / legal note
        legal = QLabel(
            "© 2026 RestOS. Все права защищены. "
            "Использование сторонних библиотек — см. NOTICE."
        )
        legal.setWordWrap(True)
        legal.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
            f" border: none; background: transparent;"
            f" padding-top: 8px;"
        )
        v.addWidget(legal)

    def _info_card(self, title: str, rows: list[tuple[str, str]]) -> QFrame:
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

        for label, value in rows:
            v.addWidget(self._kv_row(label, value))
        return card

    def _kv_row(self, label: str, value: str) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(SPACING["md"])

        l = QLabel(label)
        l.setFixedWidth(160)
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
        h.addWidget(v, 1)
        return row

    def _on_check_update(self) -> None:
        """SA-7 — открывает UpdateDialog, ручной chek + download + install."""
        from pos.screens.update_dialog import UpdateDialog
        dlg = UpdateDialog(APP_VERSION, parent=self)
        dlg.exec()

    def reload(self) -> None:
        """Не нужно — статичная секция."""
        pass
