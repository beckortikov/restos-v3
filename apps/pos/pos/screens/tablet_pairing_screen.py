"""Хелпер-диалог «Подключение планшета» (post-MVP, без фрейма в pos_cashier.pen).

Показывает QR с pairing-URL waiter PWA и тот же URL текстом. Аутентификации
не выдаёт: PWA откроется на PIN-экране официанта, дальше всё по обычной
waiter-PIN авторизации.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.lib.qr import render_qr_svg
from pos.resources.tokens import COLORS, RADIUS, SPACING


class TabletPairingDialog(QDialog):
    """Модальный диалог: QR + URL + кнопка Закрыть.

    URL передаётся явно (вызывающий код берёт его из pos.config.get_pair_url()).
    """

    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Подключение планшета")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._url = url
        self._build()

    def _build(self) -> None:
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS['bg_white']};"
            f"           border-radius: {RADIUS['lg']}px; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(
            SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"]
        )
        root.setSpacing(SPACING["md"])
        root.setAlignment(Qt.AlignCenter)

        title = QLabel("Подключение планшета")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 700;"
            f" border: none;"
        )

        hint = QLabel("Наведите камеру планшета на QR-код")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12pt; border: none;"
        )

        self._qr_widget = QSvgWidget()
        self._qr_widget.load(render_qr_svg(self._url))
        self._qr_widget.setFixedSize(280, 280)

        url_label = QLabel(self._url)
        url_label.setAlignment(Qt.AlignCenter)
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_label.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt;"
            f" font-family: monospace; border: none;"
        )

        close_btn = QPushButton("Закрыть")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedHeight(40)
        close_btn.setMinimumWidth(160)
        close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {COLORS['primary_blue']};"
            f"  color: {COLORS['text_white']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"  font-size: 14pt; font-weight: 600;"
            f"  padding: 0 24px;"
            f"}}"
        )
        close_btn.clicked.connect(self.accept)

        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(self._qr_widget, 0, Qt.AlignHCenter)
        root.addWidget(url_label)
        root.addSpacing(SPACING["sm"])
        root.addWidget(close_btn, 0, Qt.AlignHCenter)

    @property
    def url(self) -> str:
        return self._url
