"""License banner — показывает статус лицензии на каждом экране.

- active + days > 7 → не показываем (всё ок)
- active + days <= 7 → жёлтый «Лицензия истекает через N дней»
- grace → оранжевый «Лицензия истекла, осталось N дней до блокировки»
- expired → красный «Лицензия истекла. Read-only режим. Обратитесь к поставщику.»
- blocked → красный «Лицензия заблокирована: {block_reason}»
- missing → красный «Лицензия не выдана»

Подключается к `state.license_changed`. Виджет занимает 0px высоты когда скрыт.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from pos.resources.tokens import COLORS


class LicenseBanner(QFrame):
    """Тонкая полоса сверху всех экранов. Скрывается если license = active+>7d."""

    # Pulse signal — main.py может подписаться, чтобы заблокировать write-кнопки
    license_state_changed = Signal(str)  # status: active/grace/expired/blocked/missing

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("licenseBanner")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build()
        self.hide()

    def _build(self) -> None:
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 6, 16, 6)
        h.setSpacing(12)

        self._icon_lbl = QLabel("")
        self._icon_lbl.setStyleSheet(
            "background: transparent; font-size: 14pt;"
        )
        h.addWidget(self._icon_lbl)

        self._msg_lbl = QLabel("")
        self._msg_lbl.setStyleSheet(
            f"background: transparent; color: {COLORS['text_white']};"
            f" font-size: 11pt; font-weight: 700;"
        )
        h.addWidget(self._msg_lbl, 1)

    def update_from_license(self, lic: dict | None) -> None:
        """Принимает результат GET /license/status/ → перерисовывает баннер."""
        if not lic:
            self.hide()
            self.license_state_changed.emit("active")
            return
        status = lic.get("status", "active")
        days_left = int(lic.get("days_left") or 0)
        days_to_expiry = int(lic.get("days_to_expiry") or 0)
        is_blocked = bool(lic.get("is_blocked"))
        block_reason = lic.get("block_reason") or ""

        if status == "blocked" or is_blocked:
            self._show("⛔", f"Лицензия заблокирована: {block_reason or '—'}", "danger")
        elif status == "expired":
            self._show(
                "❌",
                "Лицензия истекла. Режим только-чтение. "
                "Обратитесь к поставщику для продления.",
                "danger",
            )
        elif status == "grace":
            self._show(
                "⚠️",
                f"Лицензия истекла. Осталось {days_left} дн. до блокировки. "
                "Продлите подписку.",
                "warning",
            )
        elif status == "active" and days_to_expiry <= 7:
            self._show(
                "ℹ️",
                f"Лицензия истекает через {days_to_expiry} дн. "
                "Свяжитесь с поставщиком для продления.",
                "info",
            )
        else:
            # active, > 7 дней — баннер скрыт
            self.hide()
            self.license_state_changed.emit(status)
            return

        self.show()
        self.license_state_changed.emit(status)

    def _show(self, icon: str, msg: str, kind: str) -> None:
        bg_map = {
            "danger": COLORS["danger_red"],
            "warning": "#F59E0B",  # amber-500
            "info": COLORS["primary_blue"],
        }
        bg = bg_map.get(kind, COLORS["accent_orange"])
        self.setStyleSheet(
            f"#licenseBanner {{ background-color: {bg}; }}"
        )
        self._icon_lbl.setText(icon)
        self._msg_lbl.setText(msg)
