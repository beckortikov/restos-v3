"""Sidebar 72px по design frame "3. POS — Столы + Заказ" (id=Vm2ym).

Иконки — lucide SVG inline (см. pos.resources.icons)."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from pos.resources.icons import qicon
from pos.resources.tokens import COLORS

SIDEBAR_WIDTH = 72
NAV_ICON_SIZE = 26

# Цвета иконок — solid hex (QSvgRenderer Qt6 SVG-Tiny не парсит rgba() в stroke=).
_ICON_INACTIVE = "#94A3B8"   # slate-400 — хорошо видно на $bg-dark
_ICON_ACTIVE = COLORS["accent_orange"]
_ICON_DISABLED = "#475569"   # slate-600 — приглушённо, но различимо


_NAV_BTN_QSS = """
QPushButton {
    background: transparent;
    border: none;
    padding: 0;
}
QPushButton:hover:enabled {
    background: rgba(255,255,255,0.06);
}
"""


# имя кнопки в коде → имя lucide-иконки.
# «menu» (utensils) убран из навигации: блюда теперь открываются inline в
# TablesScreen, а стоп-лист — раздел в Settings → не нуждается в sidebar-кнопке.
NAV_ICON_NAMES = {
    "tables": "layout-grid",
    "orders": "receipt",
    "settings": "settings",
    "logout": "log-out",
}


class Sidebar(QWidget):
    """Сигнал nav_clicked(name): tables | orders | logout (menu/settings — disabled)."""

    nav_clicked = Signal(str)

    def __init__(self, active: str = "tables", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_WIDTH)
        # WA_StyledBackground обязателен для покраски фона QWidget'а через
        # class-name селектор. Без него тёмный bg_dark не применяется и
        # сквозь sidebar просвечивает родительский светлый фон.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"Sidebar {{ background-color: {COLORS['bg_dark']}; }}")
        self._buttons: dict[str, QPushButton] = {}
        self._enabled_flags: dict[str, bool] = {}
        self._build(active)

    def _build(self, active: str) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 20, 0, 20)
        v.setSpacing(0)

        logo = QLabel("R")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background-color: {COLORS['accent_orange']};"
            f" color: {COLORS['text_white']};"
            f" border-radius: 22px;"
            f" font-size: 20pt; font-weight: 700;"
        )
        v.addWidget(logo, 0, Qt.AlignHCenter)
        v.addSpacing(20)

        v.addWidget(self._make_btn("tables", enabled=True))
        v.addSpacing(16)
        v.addWidget(self._make_btn("orders", enabled=True))
        v.addSpacing(16)
        v.addWidget(self._make_btn("settings", enabled=True, tip="Настройки"))

        v.addStretch(1)
        v.addWidget(self._make_btn("logout", enabled=True))

        self.set_active(active)

    def _make_btn(self, name: str, *, enabled: bool, tip: str = "") -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(SIDEBAR_WIDTH, 44)
        btn.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCheckable(True)  # храним active-state программно (визуал даёт icon color)
        btn.setEnabled(enabled)
        if tip:
            btn.setToolTip(tip)
        btn.setStyleSheet(_NAV_BTN_QSS)
        btn.clicked.connect(lambda _checked=False, n=name: self.nav_clicked.emit(n))

        color = _ICON_DISABLED if not enabled else _ICON_INACTIVE
        btn.setIcon(qicon(NAV_ICON_NAMES[name], color, NAV_ICON_SIZE))
        self._buttons[name] = btn
        self._enabled_flags[name] = enabled
        return btn

    def set_active(self, name: str) -> None:
        for n, btn in self._buttons.items():
            is_active = (n == name)
            btn.setChecked(is_active)
            if not self._enabled_flags.get(n, True):
                color = _ICON_DISABLED
            elif is_active:
                color = _ICON_ACTIVE
            else:
                color = _ICON_INACTIVE
            btn.setIcon(qicon(NAV_ICON_NAMES[n], color, NAV_ICON_SIZE))
