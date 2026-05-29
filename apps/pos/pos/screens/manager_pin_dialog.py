"""Манагер-PIN оверлей — модалка для подтверждения «опасных» действий.

Использование (паттерн):

    from pos.screens.manager_pin_dialog import ManagerPinDialog

    def cancel_order(order_id):
        try:
            client.post(f"/orders/{order_id}/cancel/", json={"reason": "..."})
        except ApiError as e:
            if e.code == "MANAGER_OVERRIDE_REQUIRED":
                dlg = ManagerPinDialog(parent=self)
                if dlg.exec() == dlg.DialogCode.Accepted:
                    pin = dlg.pin
                    client.post(
                        f"/orders/{order_id}/cancel/",
                        json={"reason": "..."},
                        extra_headers={"X-Manager-Pin": pin},
                    )

UI: компактный numpad + строка PIN'а + cancel/submit.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.resources.tokens import COLORS, RADIUS, SPACING


class ManagerPinDialog(QDialog):
    """После accept(): `dialog.pin` содержит введённый PIN."""

    def __init__(
        self,
        message: str = "Это действие требует подтверждения менеджера",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pin: str = ""
        self.setWindowTitle("PIN менеджера")
        self.setModal(True)
        self.setFixedSize(360, 460)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS['bg_white']}; }}"
        )
        self._build(message)

    def _build(self, message: str) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # Заголовок
        title = QLabel("🔐  PIN менеджера")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt;"
        )
        v.addWidget(msg)

        # Поле PIN — кружочки
        self._pin_display = QLabel("")
        self._pin_display.setAlignment(Qt.AlignCenter)
        self._pin_display.setFixedHeight(48)
        self._pin_display.setStyleSheet(
            f"QLabel {{"
            f"  background: {COLORS['bg_gray']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 24pt; font-weight: 700;"
            f"  color: {COLORS['text_primary']};"
            f"  letter-spacing: 8px;"
            f"}}"
        )
        v.addWidget(self._pin_display)

        # Numpad
        v.addWidget(self._build_numpad())

        # Footer
        footer = QHBoxLayout()
        footer.setSpacing(SPACING["md"])
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(44)
        cancel_btn.setMinimumWidth(140)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn, 1)
        v.addLayout(footer)

    def _build_numpad(self) -> QWidget:
        from PySide6.QtWidgets import QGridLayout

        grid_widget = QFrame()
        g = QGridLayout(grid_widget)
        g.setSpacing(8)
        g.setContentsMargins(0, 0, 0, 0)

        layout = [
            ("1", 0, 0), ("2", 0, 1), ("3", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("7", 2, 0), ("8", 2, 1), ("9", 2, 2),
            ("←", 3, 0), ("0", 3, 1), ("✓", 3, 2),
        ]
        for label, row, col in layout:
            btn = QPushButton(label)
            btn.setFixedHeight(54)
            btn.setCursor(Qt.PointingHandCursor)
            if label == "✓":
                style = (
                    f"QPushButton {{"
                    f"  background: {COLORS['accent_orange']};"
                    f"  color: {COLORS['text_white']};"
                    f"  border: none; border-radius: {RADIUS['sm']}px;"
                    f"  font-size: 18pt; font-weight: 700;"
                    f"}}"
                    f"QPushButton:pressed {{ background: {COLORS['accent_orange_pressed']}; }}"
                    f"QPushButton:disabled {{ background: {COLORS['border_light']}; }}"
                )
            elif label == "←":
                style = (
                    f"QPushButton {{"
                    f"  background: {COLORS['bg_gray']};"
                    f"  color: {COLORS['text_primary']};"
                    f"  border: none; border-radius: {RADIUS['sm']}px;"
                    f"  font-size: 18pt; font-weight: 700;"
                    f"}}"
                    f"QPushButton:pressed {{ background: {COLORS['border_light']}; }}"
                )
            else:
                style = (
                    f"QPushButton {{"
                    f"  background: {COLORS['bg_white']};"
                    f"  color: {COLORS['text_primary']};"
                    f"  border: 1px solid {COLORS['border_light']};"
                    f"  border-radius: {RADIUS['sm']}px;"
                    f"  font-size: 20pt; font-weight: 700;"
                    f"}}"
                    f"QPushButton:pressed {{ background: {COLORS['bg_gray']}; }}"
                )
            btn.setStyleSheet(style)
            btn.clicked.connect(
                lambda _c=False, l=label: self._on_key(l)
            )
            g.addWidget(btn, row, col)
            if label == "✓":
                self._submit_btn = btn
                btn.setEnabled(False)
        return grid_widget

    def _on_key(self, key: str) -> None:
        if key == "←":
            self.pin = self.pin[:-1]
        elif key == "✓":
            if 4 <= len(self.pin) <= 6:
                self.accept()
            return
        elif len(self.pin) < 6:
            self.pin += key
        # Update display
        self._pin_display.setText("●" * len(self.pin))
        self._submit_btn.setEnabled(4 <= len(self.pin) <= 6)
