"""Phase 8C — секция «Заготовки» в Settings для cook/manager.

Список всех is_batch_cooking блюд с prepared_qty и кнопками
«+ Заготовить» / «− Списать» / «История».
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    QDialog,
    QFormLayout,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _WriteoffDialog(QDialog):
    """Маленький диалог: qty + reason для списания готовых порций."""

    def __init__(
        self,
        client: ApiClient,
        item: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._item = item
        self.setWindowTitle("Списать готовое")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["lg"])
        title = QLabel("Списать испорченные порции")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 14pt; font-weight: 700;"
        )
        v.addWidget(title)

        ctx = QLabel(
            f"<b>{self._item.get('name', '?')}</b><br/>"
            f"<span style='color:#64748B; font-size:10pt'>"
            f"Готово: {self._item.get('prepared_qty', 0)} порций</span>"
        )
        ctx.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px; padding: 10px;"
        )
        v.addWidget(ctx)

        form = QFormLayout()
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, int(self._item.get("prepared_qty", 1) or 1))
        self.qty_spin.setSuffix(" порций")
        self.qty_spin.setFixedHeight(40)
        form.addRow("Сколько списать:", self.qty_spin)
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Просрочились / Испортились / Уронили")
        self.reason_edit.setFixedHeight(40)
        form.addRow("Причина:", self.reason_edit)
        v.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        submit = QPushButton("Списать")
        submit.setFixedHeight(40)
        submit.setMinimumWidth(140)
        submit.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
        )
        submit.clicked.connect(self._submit)
        btns.addWidget(submit)
        v.addLayout(btns)

    def _submit(self) -> None:
        qty = int(self.qty_spin.value())
        reason = self.reason_edit.text().strip()
        if not reason:
            QMessageBox.warning(self, "Ошибка", "Укажите причину")
            return
        try:
            self._client.post(
                f"/menu/items/{self._item['id']}/writeoff_prepared/",
                json={"qty": qty, "reason": reason}, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self.accept()


class _HistoryDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        item: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._item = item
        self.setWindowTitle(f"История · {item.get('name','?')}")
        self.setModal(True)
        self.setMinimumSize(640, 480)
        self._build()
        self._load()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Дата", "Тип", "Δ", "Остаток", "Заметка"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._table)

    def _load(self) -> None:
        from PySide6.QtWidgets import QTableWidgetItem
        try:
            data = self._client.get(f"/menu/items/{self._item['id']}/batch_cook/")
            rows = (data or {}).get("data", []) if isinstance(data, dict) else []
        except ApiError:
            rows = []
        self._table.setRowCount(len(rows))
        KIND_LBL = {"cook": "Заготовка", "consume": "Расход", "correct": "Корректировка"}
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem((r.get("created_at") or "")[:16].replace("T", " ")))
            self._table.setItem(i, 1, QTableWidgetItem(KIND_LBL.get(r.get("kind"), r.get("kind", ""))))
            d = int(r.get("qty_delta") or 0)
            self._table.setItem(i, 2, QTableWidgetItem(f"+{d}" if d > 0 else str(d)))
            self._table.setItem(i, 3, QTableWidgetItem(str(r.get("new_total", ""))))
            self._table.setItem(i, 4, QTableWidgetItem(r.get("note", "")))


class _ItemCard(QFrame):
    """Карточка одного batch-блюда: имя + prepared_qty + 3 кнопки."""

    def __init__(
        self,
        client: ApiClient,
        item: dict,
        on_changed,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._item = item
        self._on_changed = on_changed

        prepared = int(item.get("prepared_qty", 0) or 0)
        threshold = int(item.get("low_stock_threshold") or 5)
        if prepared <= 0:
            border = COLORS["danger_red"]
            tint = "#FEF2F2"
        elif prepared <= threshold:
            border = COLORS["accent_orange"]
            tint = "#FFF7ED"
        else:
            border = COLORS["success_green"]
            tint = "#F0FDF4"

        self.setStyleSheet(
            f"QFrame {{"
            f"  background: {tint};"
            f"  border: 2px solid {border};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        v.setSpacing(8)

        name = QLabel(item.get("name", "?"))
        name.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 13pt; font-weight: 700; border: none; background: transparent;"
        )
        v.addWidget(name)

        qty_lbl = QLabel(f"<span style='font-size:22pt; font-weight:700'>{prepared}</span>"
                         f" <span style='font-size:11pt; color:#64748B'>порций</span>")
        qty_lbl.setStyleSheet("border: none; background: transparent;")
        v.addWidget(qty_lbl)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        cook_btn = QPushButton("+ Заготовить")
        cook_btn.setFixedHeight(34)
        cook_btn.setCursor(Qt.PointingHandCursor)
        cook_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 11pt; font-weight: 700;"
            f"}}"
        )
        cook_btn.clicked.connect(self._on_cook)
        btns.addWidget(cook_btn)

        wo_btn = QPushButton("− Списать")
        wo_btn.setFixedHeight(34)
        wo_btn.setCursor(Qt.PointingHandCursor)
        wo_btn.setEnabled(prepared > 0)
        wo_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['danger_red']};"
            f"  border: 1px solid {COLORS['danger_red']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:disabled {{ color: #CBD5E1; border-color: #E2E8F0; }}"
        )
        wo_btn.clicked.connect(self._on_writeoff)
        btns.addWidget(wo_btn)

        hist_btn = QPushButton("История")
        hist_btn.setFixedHeight(34)
        hist_btn.setCursor(Qt.PointingHandCursor)
        hist_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 12px; font-size: 11pt; font-weight: 600;"
            f"}}"
        )
        hist_btn.clicked.connect(self._on_history)
        btns.addWidget(hist_btn)
        v.addLayout(btns)

    def _on_cook(self) -> None:
        from .batch_cook_dialog import BatchCookDialog

        dlg = BatchCookDialog(self._client, self._item, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._on_changed()

    def _on_writeoff(self) -> None:
        dlg = _WriteoffDialog(self._client, self._item, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._on_changed()

    def _on_history(self) -> None:
        _HistoryDialog(self._client, self._item, parent=self).exec()


class CookingSection(QWidget):
    """Phase 8C — секция «Заготовки» в Settings."""

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._build()
        self._load()

    def showEvent(self, event):  # noqa: N802
        """Phase 8E — авто-reload при возврате на вкладку (после заказа
        prepared_qty в БД меняется, нужны свежие данные)."""
        super().showEvent(event)
        # Дёргаем reload при каждом показе виджета. ETag-кеш на сервере
        # экономит трафик если данные не менялись.
        try:
            self._load()
        except Exception:
            pass

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(
            SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["md"]
        )
        title = QLabel("Заготовки")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 18pt; font-weight: 700;"
        )
        head.addWidget(title)
        head.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(36)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
        )
        refresh.clicked.connect(self._load)
        head.addWidget(refresh)
        v.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._grid_holder = QWidget()
        self._grid_holder.setStyleSheet("background: transparent;")
        self._grid_layout = QVBoxLayout(self._grid_holder)
        self._grid_layout.setContentsMargins(
            SPACING["xl"], 0, SPACING["xl"], SPACING["xl"]
        )
        self._grid_layout.setSpacing(SPACING["md"])
        scroll.setWidget(self._grid_holder)
        v.addWidget(scroll, 1)

    def _clear_grid(self) -> None:
        while self._grid_layout.count():
            it = self._grid_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _load(self) -> None:
        try:
            data = self._client.get("/menu/items/", params={"is_batch_cooking": "true"})
            items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        items = [i for i in items if i.get("is_batch_cooking")]

        self._clear_grid()
        if not items:
            empty = QLabel(
                "<span style='color:#64748B; font-size:11pt'>"
                "Нет заготовочных блюд. Включите «Заготовочное (партиями)» "
                "в карточке блюда (Настройки → Меню)."
                "</span>"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("padding: 40px;")
            self._grid_layout.addWidget(empty)
            return

        # Сетка 3 колонки
        row_layout: QHBoxLayout | None = None
        for i, item in enumerate(items):
            if i % 3 == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(SPACING["md"])
                container = QWidget()
                container.setStyleSheet("background: transparent;")
                container.setLayout(row_layout)
                self._grid_layout.addWidget(container)
            card = _ItemCard(self._client, item, on_changed=self._load)
            card.setMinimumWidth(260)
            row_layout.addWidget(card)
        # Допилить последнюю строку до 3 колонок stretch'ем
        if row_layout is not None:
            for _ in range(3 - (len(items) % 3 or 3)):
                row_layout.addStretch(1)
        self._grid_layout.addStretch(1)
