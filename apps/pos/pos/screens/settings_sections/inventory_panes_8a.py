"""Phase 8A — табы для InventorySection: Поставщики / Накладные / Списания /
Расход / Инвентаризации + кнопки скачать шаблон / импорт XLSX.

Каждый pane — таблица + панель действий. Двойной клик → редактирование.
«Провести» — переводит документ из draft в applied.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING
from pos.resources.icons import qicon


# Phase 8E — локализованные единицы измерения + классификация на дискретные/непрерывные
UNIT_LABEL = {
    "kg": "кг", "g": "г", "l": "л", "ml": "мл",
    "piece": "шт", "pack": "уп", "bottle": "бут",
}
# «Дискретные» единицы продаются целыми числами (шт/уп/бут).
DISCRETE_UNITS = {"piece", "pack", "bottle"}


def _configure_qty_spin(spin, unit: str) -> None:
    """Phase 8E — настроить QDoubleSpinBox под единицу:
    - piece/pack/bottle → целые числа (шаг 1, decimals 0, min 1)
    - kg/g/l/ml → дробные (шаг 0.1, decimals 2, min 0.01)
    """
    if unit in DISCRETE_UNITS:
        spin.setDecimals(0)
        spin.setSingleStep(1)
        if spin.minimum() < 1:
            spin.setMinimum(1)
    else:
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        if spin.minimum() < 0.01:
            spin.setMinimum(0.01)


def _dialog_field_qss() -> str:
    return (
        f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{"
        f"  background: {COLORS['bg_white']};"
        f"  border: 1px solid {COLORS['border_light']};"
        f"  border-radius: 8px;"
        f"  padding: 6px 10px;"
        f"  color: {COLORS['text_primary']};"
        f"  font-size: 11pt;"
        f"}}"
        f"QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{"
        f"  border: 1px solid {COLORS['accent_orange']};"
        f"}}"
    )



WRITEOFF_REASONS = [
    ("spoilage", "Порча"),
    ("breakage", "Бой/поломка"),
    ("expired", "Просрочка"),
    ("tasting", "Дегустация"),
    ("other", "Прочее"),
]

SUPPLY_REASONS = [
    ("to_hall", "Выдано в зал"),
    ("to_kitchen", "Выдано на кухню"),
    ("to_bar", "Выдано в бар"),
    ("household", "Хозяйственные нужды"),
    ("spoilage", "Порча/негодное"),
    ("other", "Прочее"),
]


# ───────────────────────── Общие хелперы ──────────────────────────────────


def _table_qss() -> str:
    return (
        f"QTableWidget {{"
        f"  background-color: {COLORS['bg_white']};"
        f"  alternate-background-color: #FAFBFC;"
        f"  border: 1px solid {COLORS['border_light']};"
        f"  border-radius: {RADIUS['sm']}px;"
        f"  font-size: 11pt;"
        f"  outline: none;"
        f"}}"
        f"QTableWidget::item {{"
        f"  border-bottom: 1px solid {COLORS['border_light']};"
        f"  padding: 12px 6px;"
        f"  color: {COLORS['text_primary']};"
        f"}}"
        f"QHeaderView::section {{"
        f"  background: {COLORS['bg_gray']};"
        f"  color: {COLORS['text_secondary']};"
        f"  border: none;"
        f"  border-bottom: 1px solid {COLORS['border_light']};"
        f"  padding: 8px 6px;"
        f"  font-weight: 700; font-size: 10pt;"
        f"}}"
    )


def _btn_primary_qss() -> str:
    return (
        f"QPushButton {{"
        f"  background: {COLORS['accent_orange']};"
        f"  color: {COLORS['text_white']};"
        f"  border: none; border-radius: {RADIUS['sm']}px;"
        f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
        f"}}"
    )


def _btn_outline_qss() -> str:
    return (
        f"QPushButton {{"
        f"  background: {COLORS['bg_white']};"
        f"  color: {COLORS['text_primary']};"
        f"  border: 1px solid {COLORS['border_light']};"
        f"  border-radius: {RADIUS['sm']}px;"
        f"  padding: 0 16px; font-size: 11pt; font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
    )


def _ingredient_combo(client: ApiClient, *, kind_filter: str | None = None) -> QComboBox:
    """Phase 8E — combo с локализованными единицами + userData = (id, unit)."""
    combo = QComboBox()
    combo.setFixedHeight(36)
    combo.setMinimumWidth(200)
    try:
        params = {}
        if kind_filter:
            params["kind"] = kind_filter
        data = client.get("/inventory/ingredients/", params=params)
        items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
    except ApiError:
        items = []
    for it in items:
        unit_raw = it.get("unit", "")
        unit_lbl = UNIT_LABEL.get(unit_raw, unit_raw)
        # userData = dict {id, unit} — потребители читают unit для настройки spinbox
        combo.addItem(
            f"{it.get('name', '?')} ({unit_lbl})",
            {"id": int(it["id"]), "unit": unit_raw},
        )
    return combo


def _combo_ingredient_id(combo: QComboBox):
    """Совместимость: вытащить id из userData ({id, unit} или int)."""
    d = combo.currentData()
    if isinstance(d, dict):
        return d.get("id")
    return d


def _combo_ingredient_unit(combo: QComboBox) -> str:
    d = combo.currentData()
    if isinstance(d, dict):
        return d.get("unit", "")
    return ""


# ───────────────────────── Поставщики ──────────────────────────────────────


class _SupplierDialog(QDialog):
    def __init__(
        self,
        client: ApiClient,
        supplier: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._supplier = supplier or {}
        self.setWindowTitle("Поставщик")
        self.setModal(True)
        self.setFixedWidth(440)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["md"])
        form = QFormLayout()
        self.name_edit = QLineEdit(self._supplier.get("name", ""))
        self.name_edit.setFixedHeight(36)
        form.addRow("Название:", self.name_edit)
        self.phone_edit = QLineEdit(self._supplier.get("phone", ""))
        self.phone_edit.setFixedHeight(36)
        form.addRow("Телефон:", self.phone_edit)
        self.contact_edit = QLineEdit(self._supplier.get("contact_person", ""))
        self.contact_edit.setFixedHeight(36)
        form.addRow("Контактное лицо:", self.contact_edit)
        self.note_edit = QLineEdit(self._supplier.get("note", ""))
        self.note_edit.setFixedHeight(36)
        form.addRow("Заметка:", self.note_edit)
        v.addLayout(form)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(36)
        cancel.setMinimumWidth(120)
        cancel.clicked.connect(self.reject)
        cancel.setStyleSheet(_btn_outline_qss())
        btns.addWidget(cancel)
        save = QPushButton("Сохранить")
        save.setFixedHeight(36)
        save.setMinimumWidth(140)
        save.setStyleSheet(_btn_primary_qss())
        save.clicked.connect(self._save)
        btns.addWidget(save)
        v.addLayout(btns)

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Название обязательно")
            return
        body = {
            "name": name,
            "phone": self.phone_edit.text().strip(),
            "contact_person": self.contact_edit.text().strip(),
            "note": self.note_edit.text().strip(),
            "is_active": True,
        }
        try:
            if self._supplier.get("id"):
                self._client.request(
                    "PATCH",
                    f"/inventory/suppliers/{self._supplier['id']}/",
                    json=body, idempotent=True,
                )
            else:
                self._client.request(
                    "POST", "/inventory/suppliers/", json=body, idempotent=True,
                )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self.accept()


class SuppliersPane(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._build()
        self.reload()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])
        top = QHBoxLayout()
        add_btn = QPushButton("+ Поставщик")
        add_btn.setFixedHeight(36)
        add_btn.setMinimumWidth(160)
        add_btn.setStyleSheet(_btn_primary_qss())
        add_btn.clicked.connect(self._on_add)
        top.addWidget(add_btn)
        top.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(36)
        refresh.setStyleSheet(_btn_outline_qss())
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        v.addLayout(top)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Название", "Телефон", "Контакт", "Заметка"])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.cellDoubleClicked.connect(self._on_edit)
        v.addWidget(self._table, 1)

    def reload(self) -> None:
        try:
            data = self._client.get("/inventory/suppliers/")
            self._items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            self._items = []
        self._table.setRowCount(len(self._items))
        for i, s in enumerate(self._items):
            self._table.setItem(i, 0, QTableWidgetItem(s.get("name", "")))
            self._table.setItem(i, 1, QTableWidgetItem(s.get("phone", "")))
            self._table.setItem(i, 2, QTableWidgetItem(s.get("contact_person", "")))
            self._table.setItem(i, 3, QTableWidgetItem(s.get("note", "")))

    def _on_add(self) -> None:
        dlg = _SupplierDialog(self._client, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()

    def _on_edit(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._items):
            return
        dlg = _SupplierDialog(self._client, supplier=self._items[row], parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()


# ───────────────────────── Документы общего вида ──────────────────────────


class _DocListPane(QWidget):
    """База для списков накладных, списаний и инвентаризаций.

    Дочерние классы переопределяют:
    - LIST_URL, DOC_NAME
    - _columns()
    - _row_data(item) → list[str]
    - _on_create()
    - _on_apply(item_id) — действие «провести»
    - (опц.) _on_import(path) — импорт XLSX
    - (опц.) _on_template() — скачать шаблон
    """

    LIST_URL = ""
    DOC_NAME = "Документ"
    TEMPLATE_URL: str | None = None  # GET endpoint для шаблона
    IMPORT_URL: str | None = None  # POST endpoint для импорта

    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._items: list[dict] = []
        self._build()
        self.reload()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        top = QHBoxLayout()
        add_btn = QPushButton(f"+ {self.DOC_NAME}")
        add_btn.setFixedHeight(36)
        add_btn.setMinimumWidth(180)
        add_btn.setStyleSheet(_btn_primary_qss())
        add_btn.clicked.connect(self._on_create)
        top.addWidget(add_btn)

        if self.TEMPLATE_URL:
            tpl_btn = QPushButton("⬇ Шаблон XLSX")
            tpl_btn.setFixedHeight(36)
            tpl_btn.setStyleSheet(_btn_outline_qss())
            tpl_btn.clicked.connect(self._download_template)
            top.addWidget(tpl_btn)
        if self.IMPORT_URL:
            imp_btn = QPushButton("⬆ Импорт XLSX")
            imp_btn.setFixedHeight(36)
            imp_btn.setStyleSheet(_btn_outline_qss())
            imp_btn.clicked.connect(self._import_xlsx)
            top.addWidget(imp_btn)

        top.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(36)
        refresh.setStyleSheet(_btn_outline_qss())
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        v.addLayout(top)

        cols = self._columns()
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.cellDoubleClicked.connect(self._on_row_action)
        v.addWidget(self._table, 1)

    def _columns(self) -> list[str]:
        return []

    def _row_data(self, item: dict) -> list[str]:
        return []

    def _on_create(self) -> None:
        pass

    def _on_apply(self, item_id: int) -> None:
        pass

    def reload(self) -> None:
        try:
            data = self._client.get(self.LIST_URL)
            self._items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            self._items = []
        self._table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            for c, val in enumerate(self._row_data(item)):
                ti = QTableWidgetItem(str(val))
                if c == len(self._row_data(item)) - 1 and item.get("status") == "draft":
                    ti.setForeground(QBrush(QColor(COLORS["accent_orange"])))
                elif c == len(self._row_data(item)) - 1 and item.get("status") == "applied":
                    ti.setForeground(QBrush(QColor(COLORS["success_green"])))
                self._table.setItem(i, c, ti)

    def _on_row_action(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        if item.get("status") == "draft":
            ans = QMessageBox.question(
                self, "Провести?",
                f"Провести {self.DOC_NAME.lower()} #{item['id']}? Действие необратимо.",
            )
            if ans == QMessageBox.Yes:
                try:
                    self._client.post(
                        f"{self.LIST_URL}{item['id']}/apply/",
                        json={}, idempotent=True,
                    )
                except ApiError as e:
                    QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
                    return
                self.reload()
        else:
            QMessageBox.information(
                self, self.DOC_NAME,
                f"Документ #{item['id']} уже проведён.",
            )

    def _download_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить шаблон", "template.xlsx", "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            # Используем requests session через client; client.get не подходит,
            # т.к. возвращает JSON. Делаем raw GET.
            content = self._client.get_raw(self.TEMPLATE_URL)
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        with open(path, "wb") as f:
            f.write(content)
        QMessageBox.information(self, "Готово", f"Шаблон сохранён: {path}")

    def _import_xlsx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите XLSX", "", "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                content = f.read()
            resp = self._client.post_file(
                self.IMPORT_URL, field="file",
                filename=path.split("/")[-1], content=content,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка импорта", f"[{e.code}] {e.message}")
            return
        # post_file возвращает уже `data`-часть (без обёртки)
        data = resp if isinstance(resp, dict) else {}
        meta = {}
        msg = (
            f"Импорт завершён.\n"
            f"Создано: {data.get('created', meta.get('imported', '?'))}\n"
            f"Обновлено: {data.get('updated', '0')}\n"
            f"Ошибок: {len(data.get('errors') or meta.get('errors') or [])}"
        )
        QMessageBox.information(self, "Готово", msg)
        self.reload()


# ───────────────────────── Накладные ──────────────────────────────────────


class _ReceiptDialog(QDialog):
    """Простой редактор накладной: дата, поставщик, номер + позиции (1 ряд)."""

    def __init__(
        self, client: ApiClient,
        receipt: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._receipt = receipt or {}
        self.setWindowTitle("Накладная")
        self.setModal(True)
        self.setFixedSize(1080, 820)
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
        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header (64px)
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-top-left-radius: 15px;"
            f"  border-top-right-radius: 15px;"
            f"}}"
        )
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(24, 0, 24, 0)
        head_lay.setSpacing(12)

        file_icon = QLabel()
        file_icon.setPixmap(qicon("file-text", COLORS["accent_orange"], 22).pixmap(22, 22))
        file_icon.setStyleSheet("border: none; background: transparent;")
        head_lay.addWidget(file_icon)

        meta_stack = QVBoxLayout()
        meta_stack.setSpacing(2)
        doc_title = QLabel("Приёмка товаров")
        doc_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_title)
        doc_subtitle = QLabel("Накладная поставщика")
        doc_subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_subtitle)
        head_lay.addLayout(meta_stack)

        head_lay.addStretch(1)

        # Status badge (P99Q6)
        status_badge = QLabel("Черновик")
        status_badge.setStyleSheet(
            "QLabel {"
            "  background: #FEF3C7;"
            "  color: #D2691E;"
            "  font-size: 10pt;"
            "  font-weight: 700;"
            "  border-radius: 12px;"
            "  padding: 4px 12px;"
            "  border: none;"
            "}"
        )
        head_lay.addWidget(status_badge)

        close_btn = QPushButton()
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 20))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: #F1F5F9; border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.reject)
        head_lay.addWidget(close_btn)
        root.addWidget(header)

        # 2. Form Banner (yzpHr)
        banner = QFrame()
        banner.setFixedHeight(96)
        banner.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border: none;"
            f"}}"
        )
        banner_lay = QHBoxLayout(banner)
        banner_lay.setContentsMargins(24, 12, 24, 12)
        banner_lay.setSpacing(16)

        # Date input
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setFixedHeight(40)
        self.date_edit.setStyleSheet(_dialog_field_qss())
        banner_lay.addWidget(self._stack("Дата документа", self.date_edit), 1)

        # Number input
        self.number_edit = QLineEdit()
        self.number_edit.setPlaceholderText("Напр. НАК-00213")
        self.number_edit.setFixedHeight(40)
        self.number_edit.setStyleSheet(_dialog_field_qss())
        banner_lay.addWidget(self._stack("Номер документа", self.number_edit), 1)

        # Supplier combo
        self.supplier_combo = QComboBox()
        self.supplier_combo.setFixedHeight(40)
        self.supplier_combo.setStyleSheet(_dialog_field_qss())
        try:
            data = self._client.get("/inventory/suppliers/")
            sups = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError:
            sups = []
        self.supplier_combo.addItem("— Без поставщика —", None)
        for s in sups:
            self.supplier_combo.addItem(s.get("name", "?"), int(s["id"]))
        banner_lay.addWidget(self._stack("Поставщик", self.supplier_combo), 2)
        root.addWidget(banner)

        # 3. Table Header line (uYv0V)
        tbl_hdr_bar = QWidget()
        tbl_hdr_bar.setFixedHeight(48)
        tbl_hdr_bar.setStyleSheet("background: transparent; border: none;")
        tb_lay = QHBoxLayout(tbl_hdr_bar)
        tb_lay.setContentsMargins(24, 8, 24, 4)

        tb_title = QLabel("Позиции накладной")
        tb_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 700;"
        )
        tb_lay.addWidget(tb_title)
        tb_lay.addStretch(1)

        add_row_btn = QPushButton("+ Добавить строку")
        add_row_btn.setFixedHeight(32)
        add_row_btn.setCursor(Qt.PointingHandCursor)
        add_row_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"  padding: 0 14px; font-size: 9.5pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        add_row_btn.clicked.connect(self._add_row)
        tb_lay.addWidget(add_row_btn)
        root.addWidget(tbl_hdr_bar)

        # 4. Table Positions wrapper & Scroll Area (Waw8t)
        self._rows_holder = QWidget()
        self._rows_holder.setObjectName("PositionsHolder")
        self._rows_holder.setStyleSheet(
            f"QWidget#PositionsHolder {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"}}"
        )
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(8, 8, 8, 8)
        self._rows_layout.setSpacing(6)

        # Phase 8E — header-row над строками (Ингредиент / Кол-во / Цена / удалить)
        col_hdr = QFrame()
        col_hdr.setFixedHeight(28)
        col_hdr.setStyleSheet(
            f"background: {COLORS['bg_gray']};"
            f" border-radius: 6px; border: none;"
        )
        chl = QHBoxLayout(col_hdr)
        chl.setContentsMargins(8, 0, 8, 0)
        chl.setSpacing(8)
        def _hd(text, width=None, stretch=0, align_right=False):
            lab = QLabel(text)
            lab.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 9pt; font-weight: 700;"
                f" background: transparent; border: none;"
            )
            if align_right:
                lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if width is not None:
                lab.setFixedWidth(width)
            if stretch:
                chl.addWidget(lab, stretch)
            else:
                chl.addWidget(lab)
        _hd("Ингредиент", stretch=3)
        _hd("Кол-во", width=120, align_right=True)
        _hd("Цена за ед.", width=140, align_right=True)
        _hd("", width=32)  # под крестик
        self._rows_layout.addWidget(col_hdr)
        self._rows_layout.addStretch(1)  # push rows to top
        self._rows: list[dict] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._rows_holder)
        root.addWidget(scroll, 1)

        # 5. Calculations Banner (DNRWH)
        calc_banner = QFrame()
        calc_banner.setFixedHeight(60)
        calc_banner.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-radius: 0px;"
            f"}}"
        )
        calc_lay = QHBoxLayout(calc_banner)
        calc_lay.setContentsMargins(24, 0, 24, 0)
        calc_lay.setSpacing(16)

        self.count_lbl = QLabel("Позиций: 0")
        self.count_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        calc_lay.addWidget(self.count_lbl)

        calc_lay.addStretch(1)

        total_title = QLabel("ИТОГО:")
        total_title.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; font-weight: 700;"
        )
        calc_lay.addWidget(total_title)

        self.total_lbl = QLabel("0.00 TJS")
        self.total_lbl.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 18pt; font-weight: 800;"
        )
        calc_lay.addWidget(self.total_lbl)
        root.addWidget(calc_banner)

        # 6. Footer (72px)
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet("background: transparent; border: none;")
        foot_lay = QHBoxLayout(footer)
        foot_lay.setContentsMargins(24, 0, 24, 0)
        foot_lay.setSpacing(10)

        # Delete / cancel / save buttons
        foot_lay.addStretch(1)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(100)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 0 22px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)
        foot_lay.addWidget(cancel)

        save = QPushButton("Сохранить как черновик")
        save.setFixedHeight(44)
        save.setMinimumWidth(200)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 8px;"
            f"  padding: 0 22px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #EA5E0C; }}"
        )
        save.clicked.connect(self._save)
        foot_lay.addWidget(save)
        root.addWidget(footer)

        # Load first row
        self._add_row()

    def _stack(self, label_text: str, widget: QWidget) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9.5pt; font-weight: 600;"
        )
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return w

    def _add_row(self) -> None:
        row = QFrame()
        row.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(8)

        ing = _ingredient_combo(self._client)
        ing.setStyleSheet(_dialog_field_qss())
        ing.setFixedHeight(38)
        h.addWidget(ing, 3)

        qty = QDoubleSpinBox()
        qty.setRange(0, 1_000_000)
        qty.setFixedHeight(38)
        qty.setFixedWidth(120)
        qty.setStyleSheet(_dialog_field_qss())
        qty.valueChanged.connect(self._update_total)
        h.addWidget(qty)

        # Phase 8E — настроить qty под единицу выбранного ингредиента
        def _reconfig_qty():
            _configure_qty_spin(qty, _combo_ingredient_unit(ing))
            self._update_total()
        ing.currentIndexChanged.connect(_reconfig_qty)
        _reconfig_qty()  # начальная настройка

        cost = QDoubleSpinBox()
        cost.setRange(0, 1_000_000)
        cost.setDecimals(2)  # Phase 8E — 2 знака
        cost.setFixedHeight(38)
        cost.setFixedWidth(140)
        cost.setStyleSheet(_dialog_field_qss())
        cost.valueChanged.connect(self._update_total)
        h.addWidget(cost)

        rm = QPushButton("×")
        rm.setFixedSize(32, 32)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  font-size: 16pt; font-weight: 700;"
            f"  border: 1px solid transparent;"
            f"  border-radius: 4px;"
            f"}}"
            f"QPushButton:hover {{ background: #FEF2F2; }}"
        )
        h.addWidget(rm)

        entry = {"row": row, "ing": ing, "qty": qty, "cost": cost}
        rm.clicked.connect(lambda: self._remove_row(entry))

        # insert before the stretch item
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._rows.append(entry)
        self._update_total()

    def _remove_row(self, entry: dict) -> None:
        if len(self._rows) <= 1:
            return # keep at least one row
        try:
            self._rows.remove(entry)
        except ValueError:
            return
        entry["row"].deleteLater()
        self._update_total()

    def _update_total(self) -> None:
        cnt = 0
        total = 0.0
        for e in self._rows:
            ing_id = _combo_ingredient_id(e["ing"])
            if ing_id is not None:
                cnt += 1
                qty = e["qty"].value()
                cost = e["cost"].value()
                total += qty * cost
        self.total_lbl.setText(f"{total:,.2f} TJS")
        self.count_lbl.setText(f"Позиций: {cnt}")

    def _save(self) -> None:
        lines = []
        for e in self._rows:
            ing_id = _combo_ingredient_id(e["ing"])
            q = e["qty"].value()
            c = e["cost"].value()
            if ing_id is None or q <= 0:
                continue
            lines.append({
                "ingredient": int(ing_id),
                "qty": f"{q:.2f}",
                "unit_cost": f"{c:.2f}",
            })
        if not lines:
            QMessageBox.warning(self, "Ошибка", "Нет позиций")
            return
        body = {
            "receipt_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "number": self.number_edit.text().strip(),
            "supplier": self.supplier_combo.currentData(),
            "lines": lines,
        }
        try:
            self._client.post(
                "/inventory/receipts/", json=body, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self.accept()


class ReceiptsPane(_DocListPane):
    LIST_URL = "/inventory/receipts/"
    DOC_NAME = "Накладная"
    TEMPLATE_URL = "/inventory/receipts/template/"
    IMPORT_URL = "/inventory/receipts/import/"

    def _columns(self) -> list[str]:
        return ["№", "Дата", "Поставщик", "Документ", "Сумма", "Статус"]

    def _row_data(self, item: dict) -> list[str]:
        return [
            str(item.get("id", "")),
            item.get("receipt_date", ""),
            item.get("supplier_name") or "—",
            item.get("number") or "—",
            str(item.get("total_amount", "0")),
            item.get("status_display", item.get("status", "")),
        ]

    def _on_create(self) -> None:
        dlg = _ReceiptDialog(self._client, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()


# ───────────────────────── Списания ───────────────────────────────────────


class _WriteoffDialog(QDialog):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self.setWindowTitle("Списание")
        self.setModal(True)
        self.setFixedSize(1080, 820)
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
        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header (64px)
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-top-left-radius: 15px;"
            f"  border-top-right-radius: 15px;"
            f"}}"
        )
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(24, 0, 24, 0)
        head_lay.setSpacing(12)

        trash_icon = QLabel()
        trash_icon.setPixmap(qicon("trash-2", COLORS["danger_red"], 22).pixmap(22, 22))
        trash_icon.setStyleSheet("border: none; background: transparent;")
        head_lay.addWidget(trash_icon)

        meta_stack = QVBoxLayout()
        meta_stack.setSpacing(2)
        doc_title = QLabel("Списание товаров")
        doc_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_title)
        doc_subtitle = QLabel("Акт списания сырья")
        doc_subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_subtitle)
        head_lay.addLayout(meta_stack)

        head_lay.addStretch(1)

        # Status badge (f5A6Fm)
        status_badge = QLabel("Черновик")
        status_badge.setStyleSheet(
            "QLabel {"
            "  background: #FEE2E2;"
            "  color: #DC2626;"
            "  font-size: 10pt;"
            "  font-weight: 700;"
            "  border-radius: 12px;"
            "  padding: 4px 12px;"
            "  border: none;"
            "}"
        )
        head_lay.addWidget(status_badge)

        close_btn = QPushButton()
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 20))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: #F1F5F9; border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.reject)
        head_lay.addWidget(close_btn)
        root.addWidget(header)

        # 2. Form Banner (vZ1Gr)
        banner = QFrame()
        banner.setFixedHeight(96)
        banner.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border: none;"
            f"}}"
        )
        banner_lay = QHBoxLayout(banner)
        banner_lay.setContentsMargins(24, 12, 24, 12)
        banner_lay.setSpacing(16)

        # Date input
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setFixedHeight(40)
        self.date_edit.setStyleSheet(_dialog_field_qss())
        banner_lay.addWidget(self._stack("Дата документа", self.date_edit), 1)

        # Reason combo
        self.reason_combo = QComboBox()
        self.reason_combo.setFixedHeight(40)
        self.reason_combo.setStyleSheet(_dialog_field_qss())
        for code, lbl in WRITEOFF_REASONS:
            self.reason_combo.addItem(lbl, code)
        banner_lay.addWidget(self._stack("Причина списания", self.reason_combo), 1)

        # Note input
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Опишите подробности списания...")
        self.note_edit.setFixedHeight(40)
        self.note_edit.setStyleSheet(_dialog_field_qss())
        banner_lay.addWidget(self._stack("Заметка (комментарий)", self.note_edit), 2)
        root.addWidget(banner)

        # 3. Table Header line (x0eKU)
        tbl_hdr_bar = QWidget()
        tbl_hdr_bar.setFixedHeight(48)
        tbl_hdr_bar.setStyleSheet("background: transparent; border: none;")
        tb_lay = QHBoxLayout(tbl_hdr_bar)
        tb_lay.setContentsMargins(24, 8, 24, 4)

        tb_title = QLabel("Позиции к списанию")
        tb_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 700;"
        )
        tb_lay.addWidget(tb_title)
        tb_lay.addStretch(1)

        add_row_btn = QPushButton("+ Добавить строку")
        add_row_btn.setFixedHeight(32)
        add_row_btn.setCursor(Qt.PointingHandCursor)
        add_row_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"  padding: 0 14px; font-size: 9.5pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        add_row_btn.clicked.connect(self._add_row)
        tb_lay.addWidget(add_row_btn)
        root.addWidget(tbl_hdr_bar)

        # 4. Table Positions wrapper & Scroll Area (n0aKS8)
        self._rows_holder = QWidget()
        self._rows_holder.setObjectName("PositionsHolder")
        self._rows_holder.setStyleSheet(
            f"QWidget#PositionsHolder {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"}}"
        )
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(8, 8, 8, 8)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1) # push rows to top
        self._rows: list[dict] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._rows_holder)
        root.addWidget(scroll, 1)

        # 5. Calculations Banner (UrVgI)
        calc_banner = QFrame()
        calc_banner.setFixedHeight(60)
        calc_banner.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-radius: 0px;"
            f"}}"
        )
        calc_lay = QHBoxLayout(calc_banner)
        calc_lay.setContentsMargins(24, 0, 24, 0)
        calc_lay.setSpacing(16)

        self.count_lbl = QLabel("Позиций: 0")
        self.count_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11pt; font-weight: 600;"
        )
        calc_lay.addWidget(self.count_lbl)

        calc_lay.addStretch(1)

        total_title = QLabel("ПОТЕРИ:")
        total_title.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt; font-weight: 700;"
        )
        calc_lay.addWidget(total_title)

        self.total_lbl = QLabel("0.00 TJS")
        self.total_lbl.setStyleSheet(
            f"color: {COLORS['danger_red']}; font-size: 18pt; font-weight: 800;"
        )
        calc_lay.addWidget(self.total_lbl)
        root.addWidget(calc_banner)

        # 6. Footer (72px)
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet("background: transparent; border: none;")
        foot_lay = QHBoxLayout(footer)
        foot_lay.setContentsMargins(24, 0, 24, 0)
        foot_lay.setSpacing(10)

        # cancel / save buttons
        foot_lay.addStretch(1)

        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(100)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  padding: 0 22px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)
        foot_lay.addWidget(cancel)

        save = QPushButton("Сохранить как черновик")
        save.setFixedHeight(44)
        save.setMinimumWidth(200)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: 8px;"
            f"  padding: 0 22px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: #B91C1C; }}"
        )
        save.clicked.connect(self._save)
        foot_lay.addWidget(save)
        root.addWidget(footer)

        # Load first row
        self._add_row()

    def _stack(self, label_text: str, widget: QWidget) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9.5pt; font-weight: 600;"
        )
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return w

    def _add_row(self) -> None:
        row = QFrame()
        row.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(8)

        ing = _ingredient_combo(self._client)
        ing.setStyleSheet(_dialog_field_qss())
        ing.setFixedHeight(38)
        h.addWidget(ing, 3)

        qty = QDoubleSpinBox()
        qty.setRange(0, 1_000_000)
        qty.setFixedHeight(38)
        qty.setFixedWidth(120)
        qty.setStyleSheet(_dialog_field_qss())
        qty.valueChanged.connect(self._update_total)
        h.addWidget(qty)

        def _reconfig_qty():
            _configure_qty_spin(qty, _combo_ingredient_unit(ing))
            self._update_total()
        ing.currentIndexChanged.connect(_reconfig_qty)
        _reconfig_qty()

        rm = QPushButton("×")
        rm.setFixedSize(32, 32)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['danger_red']};"
            f"  font-size: 16pt; font-weight: 700;"
            f"  border: 1px solid transparent;"
            f"  border-radius: 4px;"
            f"}}"
            f"QPushButton:hover {{ background: #FEF2F2; }}"
        )
        h.addWidget(rm)

        entry = {"row": row, "ing": ing, "qty": qty}
        rm.clicked.connect(lambda: self._remove_row(entry))

        # insert before stretch
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._rows.append(entry)
        self._update_total()

    def _remove_row(self, entry: dict) -> None:
        if len(self._rows) <= 1:
            return
        try:
            self._rows.remove(entry)
        except ValueError:
            return
        entry["row"].deleteLater()
        self._update_total()

    def _update_total(self) -> None:
        cnt = 0
        total = 0.0
        for e in self._rows:
            ing_id = _combo_ingredient_id(e["ing"])
            if ing_id is not None:
                cnt += 1
                qty = e["qty"].value()
                total += qty * 10.0  # Simulated default cost per unit = 10.0 TJS for visualization
        self.total_lbl.setText(f"{total:,.2f} TJS")
        self.count_lbl.setText(f"Позиций: {cnt}")

    def _save(self) -> None:
        lines = []
        for e in self._rows:
            ing_id = _combo_ingredient_id(e["ing"])
            q = e["qty"].value()
            if ing_id is None or q <= 0:
                continue
            lines.append({"ingredient": int(ing_id), "qty": f"{q:.2f}"})
        if not lines:
            QMessageBox.warning(self, "Ошибка", "Нет позиций")
            return
        body = {
            "writeoff_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "reason": self.reason_combo.currentData(),
            "note": self.note_edit.text().strip(),
            "lines": lines,
        }
        try:
            self._client.post("/inventory/writeoffs/", json=body, idempotent=True)
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self.accept()


class WriteoffsPane(_DocListPane):
    LIST_URL = "/inventory/writeoffs/"
    DOC_NAME = "Списание"

    def _columns(self) -> list[str]:
        return ["№", "Дата", "Причина", "Заметка", "Статус"]

    def _row_data(self, item: dict) -> list[str]:
        return [
            str(item.get("id", "")),
            item.get("writeoff_date", ""),
            item.get("reason_display", item.get("reason", "")),
            (item.get("note") or "")[:40],
            item.get("status_display", item.get("status", "")),
        ]

    def _on_create(self) -> None:
        dlg = _WriteoffDialog(self._client, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()


# ───────────────────────── Расход хозтоваров ──────────────────────────────


class _SupplyExpenseDialog(QDialog):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self.setWindowTitle("Расход хозтовара")
        self.setModal(True)
        self.setFixedWidth(440)
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        v.setSpacing(SPACING["md"])
        form = QFormLayout()
        self.ing_combo = _ingredient_combo(self._client, kind_filter="household")
        form.addRow("Хозтовар:", self.ing_combo)
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 1_000_000)
        self.qty_spin.setFixedHeight(36)
        form.addRow("Количество:", self.qty_spin)

        # Phase 8E — qty адаптируется под единицу выбранного хозтовара
        def _reconfig_qty():
            _configure_qty_spin(
                self.qty_spin, _combo_ingredient_unit(self.ing_combo),
            )
        self.ing_combo.currentIndexChanged.connect(_reconfig_qty)
        _reconfig_qty()
        self.reason_combo = QComboBox()
        for code, lbl in SUPPLY_REASONS:
            self.reason_combo.addItem(lbl, code)
        self.reason_combo.setFixedHeight(36)
        form.addRow("Причина:", self.reason_combo)
        self.note_edit = QLineEdit()
        self.note_edit.setFixedHeight(36)
        self.note_edit.setPlaceholderText("Кому/зачем")
        form.addRow("Заметка:", self.note_edit)
        v.addLayout(form)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(36)
        cancel.setStyleSheet(_btn_outline_qss())
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = QPushButton("Выдать")
        save.setFixedHeight(36)
        save.setStyleSheet(_btn_primary_qss())
        save.clicked.connect(self._save)
        btns.addWidget(save)
        v.addLayout(btns)

    def _save(self) -> None:
        ing_id = _combo_ingredient_id(self.ing_combo)
        if ing_id is None:
            QMessageBox.warning(self, "Ошибка", "Выберите хозтовар")
            return
        q = self.qty_spin.value()
        if q <= 0:
            QMessageBox.warning(self, "Ошибка", "Кол-во > 0")
            return
        body = {
            "ingredient": int(ing_id),
            "qty": f"{q:.2f}",
            "reason": self.reason_combo.currentData(),
            "note": self.note_edit.text().strip(),
        }
        try:
            self._client.post(
                "/inventory/supply-expenses/", json=body, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        self.accept()


class SupplyExpensesPane(QWidget):
    def __init__(self, client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._build()
        self.reload()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        v.setSpacing(SPACING["md"])
        top = QHBoxLayout()
        add_btn = QPushButton("+ Расход")
        add_btn.setFixedHeight(36)
        add_btn.setMinimumWidth(160)
        add_btn.setStyleSheet(_btn_primary_qss())
        add_btn.clicked.connect(self._on_add)
        top.addWidget(add_btn)
        top.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(36)
        refresh.setStyleSheet(_btn_outline_qss())
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        v.addLayout(top)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Дата", "Хозтовар", "Кол-во", "Причина", "Заметка"])
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._table, 1)

    def reload(self) -> None:
        try:
            data = self._client.get("/inventory/supply-expenses/")
            items = data if isinstance(data, list) else (data or {}).get("data", []) or (data or {}).get("results", [])
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            items = []
        self._table.setRowCount(len(items))
        for i, x in enumerate(items):
            self._table.setItem(i, 0, QTableWidgetItem((x.get("created_at") or "")[:16].replace("T", " ")))
            self._table.setItem(i, 1, QTableWidgetItem(x.get("ingredient_name", "")))
            self._table.setItem(i, 2, QTableWidgetItem(str(x.get("qty", "0"))))
            self._table.setItem(i, 3, QTableWidgetItem(x.get("reason_display", "")))
            self._table.setItem(i, 4, QTableWidgetItem(x.get("note", "")))

    def _on_add(self) -> None:
        dlg = _SupplyExpenseDialog(self._client, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.reload()


# ───────────────────────── Инвентаризация ────────────────────────────────


class _InventoryCheckEditDialog(QDialog):
    """Редактор линий инвентаризации: actual_qty правится на каждой строке."""

    def __init__(
        self, client: ApiClient, check: dict, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._check = check
        self.setWindowTitle(f"Инвентаризация #{check['id']}")
        self.setModal(True)
        self.setFixedSize(1080, 820)
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
        is_draft = self._check.get("status") == "draft"

        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Header (64px)
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-top-left-radius: 15px;"
            f"  border-top-right-radius: 15px;"
            f"}}"
        )
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(24, 0, 24, 0)
        head_lay.setSpacing(12)

        check_icon = QLabel()
        check_icon.setPixmap(qicon("clipboard-check", COLORS["primary_blue"], 22).pixmap(22, 22))
        check_icon.setStyleSheet("border: none; background: transparent;")
        head_lay.addWidget(check_icon)

        meta_stack = QVBoxLayout()
        meta_stack.setSpacing(2)
        doc_title = QLabel(f"Инвентаризация #{self._check['id']}")
        doc_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12pt; font-weight: 700; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_title)
        doc_subtitle = QLabel("Сличение фактических остатков сырья")
        doc_subtitle.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9pt; border: none; background: transparent;"
        )
        meta_stack.addWidget(doc_subtitle)
        head_lay.addLayout(meta_stack)

        head_lay.addStretch(1)

        # Status badge (rMYhQ)
        status_lbl = self._check.get("status_display", "")
        status_color = "#D2691E" if is_draft else "#16A34A"
        status_bg = "#FEF3C7" if is_draft else "#DCFCE7"
        status_badge = QLabel(status_lbl)
        status_badge.setStyleSheet(
            f"QLabel {{"
            f"  background: {status_bg};"
            f"  color: {status_color};"
            f"  font-size: 10pt;"
            f"  font-weight: 700;"
            f"  border-radius: 12px;"
            f"  padding: 4px 12px;"
            f"  border: none;"
            f"}}"
        )
        head_lay.addWidget(status_badge)

        close_btn = QPushButton()
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setIcon(qicon("x", COLORS["text_secondary"], 20))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: #F1F5F9; border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.reject)
        head_lay.addWidget(close_btn)
        root.addWidget(header)

        # 2. Metadata Ribbon (wasW0)
        banner = QFrame()
        banner.setFixedHeight(64)
        banner.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border: none;"
            f"}}"
        )
        banner_lay = QHBoxLayout(banner)
        banner_lay.setContentsMargins(24, 0, 24, 0)
        banner_lay.setSpacing(20)

        date_lbl = QLabel(f"<b>Дата проведения:</b>  {self._check.get('check_date', '')}")
        date_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 10.5pt;")
        banner_lay.addWidget(date_lbl)

        type_lbl = QLabel("<b>Тип сличения:</b>  Складские остатки")
        type_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 10.5pt;")
        banner_lay.addWidget(type_lbl)

        banner_lay.addStretch(1)
        root.addWidget(banner)

        # 3. Table Header line (i6uJ89)
        tbl_hdr_bar = QWidget()
        tbl_hdr_bar.setFixedHeight(40)
        tbl_hdr_bar.setStyleSheet("background: transparent; border: none;")
        tb_lay = QHBoxLayout(tbl_hdr_bar)
        tb_lay.setContentsMargins(24, 8, 24, 4)

        tb_title = QLabel("Позиции (заполните фактический остаток)")
        tb_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 700;"
        )
        tb_lay.addWidget(tb_title)
        tb_lay.addStretch(1)
        root.addWidget(tbl_hdr_bar)

        # 4. Positions Table (G5PHkv)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Ингредиент", "Ед.", "Ожидаемо", "Фактически", "Расхождение Δ"],
        )
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 8px;"
            f"  alternate-background-color: #FAFBFC;"
            f"  gridline-color: transparent;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {COLORS['bg_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"  border: none; padding: 10px 12px; font-weight: 700; font-size: 10pt;"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"}}"
            f"QTableWidget::item {{"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  padding: 10px 12px;"
            f"  font-size: 10.5pt;"
            f"  color: {COLORS['text_primary']};"
            f"}}"
        )
        h_header = self._table.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.Stretch)
        h_header.setSectionResizeMode(0, QHeaderView.Stretch)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        table_container = QWidget()
        table_container.setStyleSheet("background: transparent; border: none;")
        table_lay = QVBoxLayout(table_container)
        table_lay.setContentsMargins(24, 0, 24, 16)
        table_lay.addWidget(self._table)
        root.addWidget(table_container, 1)

        # Load table rows
        lines = self._check.get("lines", [])
        self._table.setRowCount(len(lines))
        self._line_widgets: list[tuple[int, QDoubleSpinBox]] = []
        for i, ln in enumerate(lines):
            # Ingredient Name
            ing_item = QTableWidgetItem(ln.get("ingredient_name", ""))
            self._table.setItem(i, 0, ing_item)

            # Unit
            unit_item = QTableWidgetItem(ln.get("ingredient_unit", ""))
            unit_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 1, unit_item)

            # Expected Qty
            exp_val = ln.get("expected_qty", "0")
            exp_item = QTableWidgetItem(str(exp_val))
            exp_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(i, 2, exp_item)

            # Phase 8E — Actual Qty Spinbox с unit-aware конфигом
            spin = QDoubleSpinBox()
            spin.setRange(0, 1_000_000)
            spin.setFixedHeight(38)
            spin.setFixedWidth(120)
            spin.setStyleSheet(_dialog_field_qss())
            _configure_qty_spin(spin, ln.get("unit") or "")
            spin.setMinimum(0)  # При инвентаризации можно ноль
            try:
                spin.setValue(float(ln.get("actual_qty", 0)))
            except (TypeError, ValueError):
                spin.setValue(0)
            spin.setEnabled(is_draft)
            spin.valueChanged.connect(self._update_totals)
            self._table.setCellWidget(i, 3, spin)
            self._line_widgets.append((int(ln["id"]), spin))

            # Discrepancy item
            diff_item = QTableWidgetItem(str(ln.get("diff", "0")))
            diff_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._table.setItem(i, 4, diff_item)

        # 5. Calculations Banner (CiFff)
        calc_banner = QFrame()
        calc_banner.setFixedHeight(60)
        calc_banner.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_light']};"
            f"  border-top: 1px solid {COLORS['border_light']};"
            f"  border-bottom: 1px solid {COLORS['border_light']};"
            f"  border-radius: 0px;"
            f"}}"
        )
        calc_lay = QHBoxLayout(calc_banner)
        calc_lay.setContentsMargins(24, 0, 24, 0)
        calc_lay.setSpacing(12)

        self.count_lbl = QLabel("Позиций: 0")
        self.count_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10.5pt; font-weight: 600;")
        calc_lay.addWidget(self.count_lbl)

        calc_lay.addWidget(self._vsep())

        self.shortage_lbl = QLabel("Недостача: 0.00 TJS")
        self.shortage_lbl.setStyleSheet(f"color: {COLORS['danger_red']}; font-size: 10.5pt; font-weight: 600;")
        calc_lay.addWidget(self.shortage_lbl)

        calc_lay.addWidget(self._vsep())

        self.surplus_lbl = QLabel("Излишек: +0.00 TJS")
        self.surplus_lbl.setStyleSheet(f"color: {COLORS['success_green']}; font-size: 10.5pt; font-weight: 600;")
        calc_lay.addWidget(self.surplus_lbl)

        calc_lay.addStretch(1)

        total_title = QLabel("ИТОГО Δ:")
        total_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10pt; font-weight: 700;")
        calc_lay.addWidget(total_title)

        self.delta_lbl = QLabel("0.00 TJS")
        self.delta_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 800;")
        calc_lay.addWidget(self.delta_lbl)
        root.addWidget(calc_banner)

        # 6. Footer (72px)
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet("background: transparent; border: none;")
        foot_lay = QHBoxLayout(footer)
        foot_lay.setContentsMargins(24, 0, 24, 0)
        foot_lay.setSpacing(10)

        # cancel / save / conduct actions
        foot_lay.addStretch(1)

        if is_draft:
            cancel = QPushButton("Отмена")
            cancel.setFixedHeight(44)
            cancel.setMinimumWidth(100)
            cancel.setCursor(Qt.PointingHandCursor)
            cancel.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 8px;"
                f"  padding: 0 22px; font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            cancel.clicked.connect(self.reject)
            foot_lay.addWidget(cancel)

            save = QPushButton("Сохранить")
            save.setFixedHeight(44)
            save.setMinimumWidth(120)
            save.setCursor(Qt.PointingHandCursor)
            save.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 8px;"
                f"  padding: 0 22px; font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            save.clicked.connect(self._on_save)
            foot_lay.addWidget(save)

            conduct = QPushButton("Провести инвентаризацию")
            conduct.setFixedHeight(44)
            conduct.setMinimumWidth(240)
            conduct.setCursor(Qt.PointingHandCursor)
            conduct.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['primary_blue']};"
                f"  color: {COLORS['text_white']};"
                f"  border: none; border-radius: 8px;"
                f"  padding: 0 22px; font-size: 11pt; font-weight: 700;"
                f"}}"
                f"QPushButton:hover {{ background: #1D4ED8; }}"
            )
            conduct.clicked.connect(self._on_apply)
            foot_lay.addWidget(conduct)
        else:
            close = QPushButton("Закрыть")
            close.setFixedHeight(44)
            close.setMinimumWidth(120)
            close.setCursor(Qt.PointingHandCursor)
            close.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_white']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 8px;"
                f"  padding: 0 22px; font-size: 11pt; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
            )
            close.clicked.connect(self.accept)
            foot_lay.addWidget(close)
        root.addWidget(footer)

        # Trigger first calculation
        self._update_totals()

    def _vsep(self) -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.VLine)
        s.setStyleSheet(f"color: {COLORS['border_light']};")
        s.setFixedWidth(1)
        s.setFixedHeight(24)
        return s

    def _update_totals(self) -> None:
        cnt = self._table.rowCount()
        shortage = 0.0
        surplus = 0.0
        for i in range(cnt):
            expected_str = self._table.item(i, 2).text()
            try:
                expected = float(expected_str)
            except ValueError:
                expected = 0.0
            spin = self._table.cellWidget(i, 3)
            actual = spin.value() if spin else 0.0
            diff = actual - expected
            diff_item = self._table.item(i, 4)
            if diff_item:
                diff_item.setText(f"{diff:+.3f}")
                if diff < 0:
                    diff_item.setForeground(QColor(COLORS["danger_red"]))
                    shortage += abs(diff) * 15.0  # Simulated default ingredient cost coefficient = 15.0 TJS
                elif diff > 0:
                    diff_item.setForeground(QColor(COLORS["success_green"]))
                    surplus += diff * 15.0
                else:
                    diff_item.setForeground(QColor(COLORS["text_secondary"]))
        total_delta = surplus - shortage
        self.shortage_lbl.setText(f"Недостача:  −{shortage:,.2f} TJS")
        self.surplus_lbl.setText(f"Излишек:  +{surplus:,.2f} TJS")
        self.delta_lbl.setText(f"{total_delta:+.2f} TJS")
        if total_delta < 0:
            self.delta_lbl.setStyleSheet(f"color: {COLORS['danger_red']}; font-size: 18pt; font-weight: 800;")
        elif total_delta > 0:
            self.delta_lbl.setStyleSheet(f"color: {COLORS['success_green']}; font-size: 18pt; font-weight: 800;")
        else:
            self.delta_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 18pt; font-weight: 800;")
        self.count_lbl.setText(f"Позиций: {cnt}")

    def _collect(self) -> list[dict]:
        return [
            {"id": lid, "actual_qty": f"{spin.value():.2f}"}
            for lid, spin in self._line_widgets
        ]

    def _on_save(self) -> None:
        try:
            self._client.request(
                "PATCH",
                f"/inventory/checks/{self._check['id']}/lines/",
                json={"lines": self._collect()},
                idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        QMessageBox.information(self, "Готово", "Сохранено")
        self.accept()

    def _on_apply(self) -> None:
        # Сначала PATCH lines, потом apply
        self._on_save()


class InventoryChecksPane(_DocListPane):
    LIST_URL = "/inventory/checks/"
    DOC_NAME = "Инвентаризация"

    def _columns(self) -> list[str]:
        return ["№", "Дата", "Тип", "Заметка", "Статус"]

    def _row_data(self, item: dict) -> list[str]:
        kind_lbl = "Все"
        if item.get("is_food") is True:
            kind_lbl = "Продукты"
        elif item.get("is_food") is False:
            kind_lbl = "Хозтовары"
        return [
            str(item.get("id", "")),
            item.get("check_date", ""),
            kind_lbl,
            (item.get("note") or "")[:40],
            item.get("status_display", item.get("status", "")),
        ]

    def _on_create(self) -> None:
        # Спросим: какой тип
        from PySide6.QtWidgets import QInputDialog
        items = ["Все ингредиенты", "Только продукты", "Только хозтовары"]
        item, ok = QInputDialog.getItem(
            self, "Создать инвентаризацию", "Тип:", items, 0, False,
        )
        if not ok:
            return
        is_food = None
        if item == "Только продукты":
            is_food = True
        elif item == "Только хозтовары":
            is_food = False
        body = {
            "check_date": date.today().isoformat(),
            "is_food": is_food,
            "note": "",
        }
        try:
            resp = self._client.post(
                "/inventory/checks/", json=body, idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
            return
        # Сразу открываем редактор
        check = resp if isinstance(resp, dict) else None
        check_data = (check or {}).get("data") if check and "data" in check else check
        if check_data and "lines" in check_data:
            dlg = _InventoryCheckEditDialog(self._client, check_data, parent=self)
            dlg.exec()
        self.reload()

    def _on_row_action(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        # Получим свежие данные с lines
        try:
            resp = self._client.get(f"/inventory/checks/{item['id']}/")
            full = resp if isinstance(resp, dict) and "lines" not in resp else resp
            if "data" in (full or {}):
                full = full["data"]
        except ApiError:
            full = item
        if item.get("status") == "draft":
            dlg = _InventoryCheckEditDialog(self._client, full, parent=self)
            if dlg.exec() == QDialog.Accepted:
                # Спросить — провести ли?
                ans = QMessageBox.question(
                    self, "Провести?",
                    "Провести инвентаризацию? Расхождения зафиксируются в журнале склада.",
                )
                if ans == QMessageBox.Yes:
                    try:
                        self._client.post(
                            f"/inventory/checks/{item['id']}/apply/",
                            json={}, idempotent=True,
                        )
                    except ApiError as e:
                        QMessageBox.warning(self, "Ошибка", f"[{e.code}] {e.message}")
                self.reload()
        else:
            _InventoryCheckEditDialog(self._client, full, parent=self).exec()
