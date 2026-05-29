"""Touch-friendly диалог резервации.

Принципы:
- Никаких QSpinBox / QDateTimeEdit / календарь-попапов — всё крупными кнопками.
- Пресеты времени: «+30 мин», «+1 ч», «+2 ч», «Завтра 19:00» и т.д.
- Гости — большие кнопки `−` / `+` со значением посередине.
- Длительность — chip-row («1 ч», «1.5 ч», «2 ч», «3 ч»).
- Поля ввода крупные (52px+), пригодны для пальцев.
"""
from datetime import datetime, time, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


# Пресет-длительности (минуты).
DURATION_PRESETS = [
    (60, "1 ч"),
    (90, "1.5 ч"),
    (120, "2 ч"),
    (180, "3 ч"),
    (240, "4 ч"),
]


class ReservationFormDialog(QDialog):
    """Сигналы:
        reservation_created(dict) — успешно создано на backend.
    """

    reservation_created = Signal(dict)

    def __init__(
        self,
        client: ApiClient,
        tables: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._tables = list(tables)
        # Внутреннее состояние — мутируется кнопками.
        self._scheduled_at: datetime = self._round_up_to_quarter(
            datetime.now() + timedelta(minutes=30)
        )
        self._duration_min: int = 120
        self._party_size: int = 2
        self._submitting: bool = False

        self.setWindowTitle("Резервация")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMaximumWidth(640)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS['bg_white']}; }}"
        )
        self._build()
        self._refresh_dynamic_labels()

    # -------- helpers --------

    @staticmethod
    def _round_up_to_quarter(dt: datetime) -> datetime:
        """Округлить вверх до ближайших 15 минут."""
        minute = dt.minute
        delta_to_next = (15 - (minute % 15)) % 15
        if delta_to_next == 0 and dt.second == 0 and dt.microsecond == 0:
            return dt.replace(second=0, microsecond=0)
        rounded = dt + timedelta(minutes=delta_to_next)
        return rounded.replace(second=0, microsecond=0)

    # -------- build --------

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"],
        )
        v.setSpacing(SPACING["md"])

        title = QLabel("Резервация")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        v.addWidget(title)

        # Стол
        if len(self._tables) > 1:
            v.addWidget(self._lbl("Стол"))
            self._table_combo = QComboBox()
            self._table_combo.setFixedHeight(52)
            self._table_combo.setStyleSheet(self._field_qss())
            for t in self._tables:
                label = (
                    f"{t.get('zone_name', '')} — {t.get('name', '')} "
                    f"({t.get('capacity', 0)} мест)"
                )
                self._table_combo.addItem(label, int(t["id"]))
            v.addWidget(self._table_combo)
        else:
            # Один стол — показываем как readonly-label, без combobox
            self._table_combo = None
            t = self._tables[0]
            tlbl = QLabel(
                f"📍  {t.get('zone_name', '')} — {t.get('name', '')} "
                f"({t.get('capacity', 0)} мест)"
            )
            tlbl.setStyleSheet(
                f"color: {COLORS['text_primary']};"
                f" font-size: 13pt; font-weight: 600;"
                f" background: {COLORS['bg_gray']};"
                f" border-radius: {RADIUS['sm']}px;"
                f" padding: 14px 16px;"
            )
            v.addWidget(tlbl)

        # Имя
        v.addWidget(self._lbl("Имя гостя"))
        self._name = QLineEdit()
        self._name.setFixedHeight(52)
        self._name.setPlaceholderText("Иван Иванов")
        self._name.setStyleSheet(self._field_qss())
        self._name.textChanged.connect(self._update_save_state)
        v.addWidget(self._name)

        # Телефон
        v.addWidget(self._lbl("Телефон (опц.)"))
        self._phone = QLineEdit()
        self._phone.setFixedHeight(52)
        self._phone.setPlaceholderText("+992 901 23 45 67")
        self._phone.setStyleSheet(self._field_qss())
        v.addWidget(self._phone)

        # Гости (− 4 +)
        v.addWidget(self._lbl("Гостей"))
        v.addLayout(self._build_guests_row())

        # Когда (пресеты + −15/+15)
        v.addWidget(self._lbl("Когда"))
        v.addLayout(self._build_when_block())

        # На сколько (chip row)
        v.addWidget(self._lbl("На сколько"))
        v.addLayout(self._build_duration_row())

        # Footer
        v.addLayout(self._build_footer())

    def _build_guests_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(SPACING["md"])

        minus = self._big_step_btn("−", lambda: self._change_party(-1))
        h.addWidget(minus)

        self._guests_lbl = QLabel(str(self._party_size))
        self._guests_lbl.setAlignment(Qt.AlignCenter)
        self._guests_lbl.setStyleSheet(
            f"QLabel {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 22pt; font-weight: 800;"
            f"  padding: 8px 0;"
            f"}}"
        )
        self._guests_lbl.setMinimumHeight(64)
        h.addWidget(self._guests_lbl, 1)

        plus = self._big_step_btn("+", lambda: self._change_party(+1))
        h.addWidget(plus)
        return h

    def _build_when_block(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(SPACING["sm"])

        # Пресеты-чипы
        chips = QHBoxLayout()
        chips.setSpacing(SPACING["sm"])
        for label, delta_min in [
            ("+30 мин", 30),
            ("+1 час", 60),
            ("+2 часа", 120),
            ("+3 часа", 180),
        ]:
            btn = self._chip(
                label, lambda _c=False, m=delta_min: self._set_in_minutes(m)
            )
            chips.addWidget(btn, 1)
        v.addLayout(chips)

        # «Завтра» пресеты
        chips2 = QHBoxLayout()
        chips2.setSpacing(SPACING["sm"])
        for label, hour in [
            ("Завтра 13:00", 13),
            ("Завтра 19:00", 19),
            ("Завтра 20:00", 20),
        ]:
            btn = self._chip(
                label, lambda _c=False, h=hour: self._set_tomorrow_hour(h)
            )
            chips2.addWidget(btn, 1)
        v.addLayout(chips2)

        # Тонкая настройка: −15  [время]  +15
        fine = QHBoxLayout()
        fine.setSpacing(SPACING["md"])
        m15 = self._big_step_btn(
            "−15", lambda: self._shift_minutes(-15), accent=False,
        )
        fine.addWidget(m15)

        self._dt_lbl = QLabel("")
        self._dt_lbl.setAlignment(Qt.AlignCenter)
        self._dt_lbl.setStyleSheet(
            f"QLabel {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['accent_orange']};"
            f"  border: 1.5px solid {COLORS['accent_orange']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 18pt; font-weight: 800;"
            f"  padding: 8px 12px;"
            f"}}"
        )
        self._dt_lbl.setMinimumHeight(64)
        fine.addWidget(self._dt_lbl, 2)

        p15 = self._big_step_btn(
            "+15", lambda: self._shift_minutes(+15), accent=False,
        )
        fine.addWidget(p15)
        v.addLayout(fine)
        return v

    def _build_duration_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(SPACING["sm"])
        self._duration_buttons: dict[int, QPushButton] = {}
        for minutes, label in DURATION_PRESETS:
            btn = QPushButton(label)
            btn.setMinimumHeight(52)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setStyleSheet(self._duration_btn_qss(active=False))
            btn.clicked.connect(
                lambda _c=False, m=minutes: self._set_duration(m)
            )
            self._duration_buttons[minutes] = btn
            h.addWidget(btn, 1)
        return h

    def _build_footer(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(SPACING["md"])
        h.setContentsMargins(0, SPACING["md"], 0, 0)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(56)
        cancel.setMinimumWidth(160)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)
        h.addStretch(1)

        self._save_btn = QPushButton("✓  Создать резервацию")
        self._save_btn.setFixedHeight(56)
        self._save_btn.setMinimumWidth(280)
        self._save_btn.setEnabled(False)
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setStyleSheet(self._save_qss())
        self._save_btn.clicked.connect(self._on_save)
        h.addWidget(self._save_btn)
        return h

    # -------- factories --------

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 12pt; font-weight: 700;"
            f" margin-top: 2px;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QComboBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 16px; font-size: 14pt; min-height: 48px;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus "
            f"{{ border: 1.5px solid {COLORS['accent_orange']}; }}"
            f"QComboBox::drop-down {{ width: 36px; }}"
        )

    def _big_step_btn(self, text: str, handler, *, accent: bool = True) -> QPushButton:
        b = QPushButton(text)
        b.setMinimumSize(64, 64)
        b.setCursor(Qt.PointingHandCursor)
        bg = COLORS["accent_orange"] if accent else COLORS["bg_gray"]
        fg = COLORS["text_white"] if accent else COLORS["text_primary"]
        hover = "#DC6803" if accent else COLORS["border_light"]
        b.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {fg};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  font-size: 22pt; font-weight: 800;"
            f"}}"
            f"QPushButton:pressed {{ background: {hover}; }}"
        )
        b.clicked.connect(handler)
        return b

    def _chip(self, text: str, handler) -> QPushButton:
        b = QPushButton(text)
        b.setMinimumHeight(48)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border-color: {COLORS['accent_orange']};"
            f"}}"
        )
        b.clicked.connect(handler)
        return b

    def _duration_btn_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  font-size: 14pt; font-weight: 800;"
                f"}}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  font-size: 14pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ border-color: {COLORS['accent_orange']}; }}"
        )

    def _cancel_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1.5px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 28px; font-size: 14pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _save_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 28px; font-size: 14pt; font-weight: 800;"
            f"}}"
            f"QPushButton:pressed {{ background: #DC6803; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )

    # -------- state mutators --------

    def _change_party(self, delta: int) -> None:
        self._party_size = max(1, min(50, self._party_size + delta))
        self._guests_lbl.setText(str(self._party_size))

    def _set_duration(self, minutes: int) -> None:
        self._duration_min = int(minutes)
        for m, btn in self._duration_buttons.items():
            btn.setStyleSheet(
                self._duration_btn_qss(active=(m == self._duration_min))
            )
            btn.setChecked(m == self._duration_min)

    def _set_in_minutes(self, delta: int) -> None:
        self._scheduled_at = self._round_up_to_quarter(
            datetime.now() + timedelta(minutes=delta)
        )
        self._refresh_dynamic_labels()

    def _set_tomorrow_hour(self, hour: int) -> None:
        tomorrow = datetime.now().date() + timedelta(days=1)
        self._scheduled_at = datetime.combine(
            tomorrow, time(hour=hour, minute=0)
        )
        self._refresh_dynamic_labels()

    def _shift_minutes(self, delta: int) -> None:
        self._scheduled_at = self._scheduled_at + timedelta(minutes=delta)
        # Не уходим в прошлое
        now = datetime.now() - timedelta(minutes=5)
        if self._scheduled_at < now:
            self._scheduled_at = self._round_up_to_quarter(
                datetime.now() + timedelta(minutes=15)
            )
        self._refresh_dynamic_labels()

    def _refresh_dynamic_labels(self) -> None:
        if hasattr(self, "_dt_lbl"):
            self._dt_lbl.setText(self._fmt_dt(self._scheduled_at))
        if hasattr(self, "_duration_buttons"):
            self._set_duration(self._duration_min)

    @staticmethod
    def _fmt_dt(dt: datetime) -> str:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        if dt.date() == today:
            prefix = "Сегодня"
        elif dt.date() == tomorrow:
            prefix = "Завтра"
        else:
            prefix = dt.strftime("%d.%m")
        return f"{prefix}  {dt.strftime('%H:%M')}"

    # -------- save flow --------

    def _update_save_state(self) -> None:
        ok = bool(self._name.text().strip())
        if self._table_combo is not None:
            ok = ok and self._table_combo.count() > 0
        self._save_btn.setEnabled(ok and not self._submitting)

    def _on_save(self) -> None:
        if not self._save_btn.isEnabled() or self._submitting:
            return
        # table_id
        if self._table_combo is not None:
            if self._table_combo.currentIndex() < 0:
                return
            table_id = int(self._table_combo.currentData())
        else:
            table_id = int(self._tables[0]["id"])

        body = {
            "table": table_id,
            "customer_name": self._name.text().strip(),
            "customer_phone": self._phone.text().strip(),
            "party_size": int(self._party_size),
            "duration_min": int(self._duration_min),
            "scheduled_at": self._scheduled_at.isoformat(),
            "notes": "",
        }
        # Блокируем повторные клики и показываем «Создаю…»
        self._submitting = True
        self._save_btn.setEnabled(False)
        self._save_btn.setText("Создаю…")
        # Защита: если backend завис, через 8 сек разблокируем кнопку обратно.
        QTimer.singleShot(8000, self._restore_button_if_stuck)
        try:
            data = self._client.post("/reservations/", json=body)
        except ApiError as e:
            self._submitting = False
            self._save_btn.setText("✓  Создать резервацию")
            self._save_btn.setEnabled(True)
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось создать резервацию:\n{e.message}\n[{e.code}]",
            )
            return
        rec = data.get("data") if isinstance(data, dict) and "data" in data else data
        self.reservation_created.emit(rec or body)
        self.accept()

    def _restore_button_if_stuck(self) -> None:
        """Если форма не закрылась за 8 сек — разблокируем кнопку. Защита от
        зависшего backend, чтобы пользователь мог попробовать снова или
        отменить."""
        if self._submitting and self.isVisible():
            self._submitting = False
            self._save_btn.setEnabled(True)
            self._save_btn.setText("✓  Создать резервацию")
