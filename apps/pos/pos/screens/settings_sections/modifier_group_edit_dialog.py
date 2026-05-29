"""Диалог редактирования группы модификаторов с вложенным списком опций.

Поля группы: name, is_required, min_select, max_select, sort_order, is_active.
Опции — в таблице (имя + price_delta + удалить-кнопка) с кнопкой «+ Опция».
Сохранение — POST /menu/modifier-groups/ или PATCH /menu/modifier-groups/{id}/.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _SaveWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self, client: ApiClient, group_id: int | None, payload: dict
    ) -> None:
        super().__init__()
        self.client = client
        self.group_id = group_id
        self.payload = payload

    def run(self) -> None:
        try:
            if self.group_id is None:
                data = self.client.post(
                    "/menu/modifier-groups/", json=self.payload, idempotent=True,
                )
            else:
                data = self.client.request(
                    "PATCH", f"/menu/modifier-groups/{self.group_id}/",
                    json=self.payload, idempotent=True,
                )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class ModifierGroupEditDialog(QDialog):
    """Открывается из ModifierGroupsDialog. group=None → создание."""

    def __init__(
        self,
        client: ApiClient,
        group: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._group = group  # None для нового
        self._threads: list[QThread] = []
        # Список строк опций: [{ "id"?: int, "name": str, "price_delta": str,
        #                        "row_widget": QWidget }]
        self._option_rows: list[dict] = []

        self.setWindowTitle(
            "Новая группа модификаторов" if group is None
            else f"Редактирование: {group.get('name', '')}"
        )
        self.setModal(True)
        self.setMinimumSize(520, 600)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()
        if group is not None:
            self._fill(group)

    # ---- build ----

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["md"])

        # Name
        v.addWidget(self._field_label("Название"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("Например: «Прожарка», «Соусы»")
        self._name.setStyleSheet(self._input_qss())
        v.addWidget(self._name)

        # min / max / required в одной строке
        row = QHBoxLayout()
        row.setSpacing(SPACING["md"])

        col_min = QVBoxLayout()
        col_min.addWidget(self._field_label("Мин. опций"))
        self._min = QSpinBox()
        self._min.setRange(0, 20)
        self._min.setStyleSheet(self._input_qss())
        col_min.addWidget(self._min)
        row.addLayout(col_min)

        col_max = QVBoxLayout()
        col_max.addWidget(self._field_label("Макс. опций"))
        self._max = QSpinBox()
        self._max.setRange(1, 20)
        self._max.setValue(1)
        self._max.setStyleSheet(self._input_qss())
        col_max.addWidget(self._max)
        row.addLayout(col_max)

        col_sort = QVBoxLayout()
        col_sort.addWidget(self._field_label("Сорт."))
        self._sort = QSpinBox()
        self._sort.setRange(0, 999)
        self._sort.setStyleSheet(self._input_qss())
        col_sort.addWidget(self._sort)
        row.addLayout(col_sort)

        v.addLayout(row)

        flags = QHBoxLayout()
        self._required = QCheckBox("Обязательная (нужно выбрать минимум 1)")
        flags.addWidget(self._required)
        flags.addStretch(1)
        self._active = QCheckBox("Активна")
        self._active.setChecked(True)
        flags.addWidget(self._active)
        v.addLayout(flags)

        # Options list
        opts_head = QHBoxLayout()
        lbl = QLabel("Опции")
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 13pt; font-weight: 700;"
        )
        opts_head.addWidget(lbl)
        opts_head.addStretch(1)
        add_opt = QPushButton("+ Опция")
        add_opt.setCursor(Qt.PointingHandCursor)
        add_opt.setFixedHeight(34)
        add_opt.setStyleSheet(self._btn_qss(primary=False))
        add_opt.clicked.connect(lambda: self._add_option_row(None))
        opts_head.addWidget(add_opt)
        v.addLayout(opts_head)

        self._opts_holder = QWidget()
        self._opts_holder.setStyleSheet("background: transparent;")
        self._opts_layout = QVBoxLayout(self._opts_holder)
        self._opts_layout.setContentsMargins(0, 0, 0, 0)
        self._opts_layout.setSpacing(SPACING["sm"])
        self._opts_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._opts_holder)
        v.addWidget(scroll, 1)

        # Footer
        btns = QHBoxLayout()
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._btn_qss(primary=False))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addStretch(1)

        self._save_btn = QPushButton("Сохранить")
        self._save_btn.setFixedHeight(44)
        self._save_btn.setMinimumWidth(160)
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setStyleSheet(self._btn_qss(primary=True))
        self._save_btn.clicked.connect(self._on_save)
        btns.addWidget(self._save_btn)
        v.addLayout(btns)

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 10pt; font-weight: 600;"
        )
        return lbl

    def _input_qss(self) -> str:
        return (
            f"QLineEdit, QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 6px 10px; font-size: 11pt;"
            f"}}"
        )

    def _btn_qss(self, *, primary: bool) -> str:
        if primary:
            return (
                f"QPushButton {{"
                f"  background: {COLORS['accent_orange']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: {RADIUS['sm']}px;"
                f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #EA5E0C; }}"
            )
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 14px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    # ---- options ----

    def _add_option_row(self, opt: dict | None) -> None:
        row = QFrame()
        row.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(8)

        name = QLineEdit()
        name.setPlaceholderText("Имя опции")
        name.setStyleSheet(self._input_qss())
        h.addWidget(name, 2)

        delta = QLineEdit()
        delta.setPlaceholderText("Δ цена")
        delta.setMaximumWidth(110)
        delta.setStyleSheet(self._input_qss())
        h.addWidget(delta)

        rm = QPushButton("Удалить")
        rm.setFixedHeight(30)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setStyleSheet(self._btn_qss(primary=False))
        h.addWidget(rm)

        entry: dict = {
            "id": (opt or {}).get("id"),
            "name_widget": name,
            "delta_widget": delta,
            "row_widget": row,
        }
        if opt:
            name.setText(str(opt.get("name", "")))
            delta.setText(str(opt.get("price_delta") or "0"))
        else:
            delta.setText("0")
        rm.clicked.connect(lambda _c=False, e=entry: self._remove_option(e))

        self._option_rows.append(entry)
        self._opts_layout.addWidget(row)

    def _remove_option(self, entry: dict) -> None:
        try:
            self._option_rows.remove(entry)
        except ValueError:
            pass
        w = entry.get("row_widget")
        if w is not None:
            w.deleteLater()

    # ---- fill from existing ----

    def _fill(self, group: dict) -> None:
        self._name.setText(group.get("name", ""))
        self._min.setValue(int(group.get("min_select") or 0))
        self._max.setValue(int(group.get("max_select") or 1))
        self._sort.setValue(int(group.get("sort_order") or 0))
        self._required.setChecked(bool(group.get("is_required")))
        self._active.setChecked(bool(group.get("is_active", True)))
        for opt in group.get("modifiers") or []:
            self._add_option_row(opt)

    # ---- save ----

    def _collect_payload(self) -> dict:
        opts: list[dict] = []
        for row in self._option_rows:
            n = row["name_widget"].text().strip()
            d = row["delta_widget"].text().strip() or "0"
            if not n:
                continue
            opt: dict = {"name": n, "price_delta": d}
            if row.get("id"):
                opt["id"] = int(row["id"])
            opts.append(opt)
        return {
            "name": self._name.text().strip(),
            "min_select": int(self._min.value()),
            "max_select": int(self._max.value()),
            "is_required": bool(self._required.isChecked()),
            "sort_order": int(self._sort.value()),
            "is_active": bool(self._active.isChecked()),
            "modifiers": opts,
        }

    def _on_save(self) -> None:
        payload = self._collect_payload()
        if not payload["name"]:
            QMessageBox.warning(self, "Ошибка", "Имя группы не может быть пустым")
            return
        if payload["min_select"] > payload["max_select"]:
            QMessageBox.warning(
                self, "Ошибка",
                "Мин. опций не может быть больше максимума",
            )
            return
        if payload["is_required"] and payload["min_select"] < 1:
            payload["min_select"] = 1

        self._save_btn.setEnabled(False)
        thread = QThread(self)
        gid = int(self._group["id"]) if self._group else None
        worker = _SaveWorker(self._client, gid, payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(lambda _d: self.accept())
        worker.error.connect(self._on_save_error)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread._worker = worker  # noqa: SLF001
        self._threads.append(thread)
        thread.start()

    def _on_save_error(self, exc: ApiError) -> None:
        self._save_btn.setEnabled(True)
        QMessageBox.warning(
            self, "Ошибка сохранения",
            f"[{exc.code}] {exc.message}",
        )
