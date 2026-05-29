"""TableMergeDialog — объединение / разъединение столов.

Открывается из TablesScreen («Объединить столы» в шапке).

UX:
- Левая колонка: список свободных столов (чекбоксы) → кнопка «Объединить»
- Правая колонка: активные группы (показ «5+6, 7») → кнопка «Разъединить»

После любого действия — refresh state.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class TableMergeDialog(QDialog):
    """Сигналы:
        groups_changed() — после успешного merge/unmerge → main вызывает refresh.
    """

    groups_changed = Signal()

    def __init__(
        self,
        client: ApiClient,
        tables: list[dict],
        groups: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._tables = list(tables)
        self._groups = list(groups)

        self.setWindowTitle("Объединить столы")
        self.setModal(True)
        self.setMinimumWidth(720)
        self.setMinimumHeight(480)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS['bg_white']}; }}"
        )
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"],
        )
        v.setSpacing(SPACING["md"])

        title = QLabel("Объединить / разъединить столы")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        v.addWidget(title)

        # Body — две колонки
        body = QHBoxLayout()
        body.setSpacing(SPACING["lg"])
        body.addWidget(self._build_merge_col(), 1)
        body.addWidget(self._build_groups_col(), 1)
        v.addLayout(body, 1)

        # Footer
        footer = QHBoxLayout()
        footer.setSpacing(SPACING["md"])
        cancel = QPushButton("Закрыть")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.accept)
        footer.addStretch(1)
        footer.addWidget(cancel)
        v.addLayout(footer)

    # -------- Merge column --------

    def _build_merge_col(self) -> QWidget:
        col = QFrame()
        col.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        cv = QVBoxLayout(col)
        cv.setContentsMargins(16, 14, 16, 14)
        cv.setSpacing(SPACING["sm"])

        head = QLabel("Свободные столы — выберите 2+")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700;"
        )
        cv.addWidget(head)

        # Поле имени (опционально)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Имя группы (опц.) — например «VIP»")
        self._name_input.setFixedHeight(36)
        self._name_input.setStyleSheet(
            f"QLineEdit {{"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 10px; font-size: 11pt;"
            f"  background: {COLORS['bg_white']};"
            f"}}"
            f"QLineEdit:focus {{ border: 1.5px solid {COLORS['accent_orange']}; }}"
        )
        cv.addWidget(self._name_input)

        # Список свободных столов с чекбоксами
        self._free_list = QListWidget()
        self._free_list.setStyleSheet(
            f"QListWidget {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"}}"
            f"QListWidget::item {{ padding: 6px; }}"
        )
        self._checkboxes: dict[int, QCheckBox] = {}
        free_tables = [t for t in self._tables if t.get("status") == "free"]
        if not free_tables:
            empty = QListWidgetItem("Нет свободных столов для объединения")
            empty.setFlags(Qt.NoItemFlags)
            self._free_list.addItem(empty)
        for t in free_tables:
            item = QListWidgetItem()
            self._free_list.addItem(item)
            cb = QCheckBox(
                f"{t.get('zone_name', '')} — {t.get('name', '')} "
                f"({t.get('capacity', 0)} мест)"
            )
            cb.setStyleSheet(
                f"QCheckBox {{ font-size: 11pt; color: {COLORS['text_primary']}; }}"
            )
            cb.toggled.connect(self._update_merge_btn_state)
            self._checkboxes[int(t["id"])] = cb
            self._free_list.setItemWidget(item, cb)
        cv.addWidget(self._free_list, 1)

        self._merge_btn = QPushButton("Объединить выбранные")
        self._merge_btn.setFixedHeight(40)
        self._merge_btn.setEnabled(False)
        self._merge_btn.setCursor(Qt.PointingHandCursor)
        self._merge_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['accent_orange']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 11pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #DC6803; }}"
            f"QPushButton:disabled {{"
            f"  background: {COLORS['border_light']};"
            f"  color: {COLORS['text_secondary']};"
            f"}}"
        )
        self._merge_btn.clicked.connect(self._on_merge)
        cv.addWidget(self._merge_btn)
        return col

    def _update_merge_btn_state(self) -> None:
        n = sum(1 for cb in self._checkboxes.values() if cb.isChecked())
        self._merge_btn.setEnabled(n >= 2)

    def _selected_ids(self) -> list[int]:
        return [
            tid for tid, cb in self._checkboxes.items() if cb.isChecked()
        ]

    def _on_merge(self) -> None:
        ids = self._selected_ids()
        if len(ids) < 2:
            return
        body = {"table_ids": ids, "name": self._name_input.text().strip()}
        try:
            self._client.post("/tables/merge/", json=body)
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"{e.message}\n[{e.code}]",
            )
            return
        self.groups_changed.emit()
        self.accept()

    # -------- Groups column --------

    def _build_groups_col(self) -> QWidget:
        col = QFrame()
        col.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['md']}px;"
            f"}}"
        )
        cv = QVBoxLayout(col)
        cv.setContentsMargins(16, 14, 16, 14)
        cv.setSpacing(SPACING["sm"])

        head = QLabel("Активные группы")
        head.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700;"
        )
        cv.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        gv = QVBoxLayout(holder)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(SPACING["sm"])
        gv.setAlignment(Qt.AlignTop)

        if not self._groups:
            empty = QLabel("Активных групп нет")
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11pt;"
                f" font-style: italic; padding: 12px;"
            )
            gv.addWidget(empty)
        else:
            for g in self._groups:
                gv.addWidget(self._build_group_row(g))

        scroll.setWidget(holder)
        cv.addWidget(scroll, 1)
        return col

    def _build_group_row(self, group: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{"
            f"  background: {COLORS['bg_gray']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(SPACING["sm"])

        names = group.get("table_names") or []
        # Извлечь только номера
        shorts = []
        for n in names:
            parts = n.split()
            shorts.append(parts[-1] if parts else n)
        title_text = "+".join(shorts)
        if group.get("name"):
            title_text = f"{title_text}  ·  {group['name']}"
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 12pt; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        h.addWidget(title, 1)

        unmerge_btn = QPushButton("Разъединить")
        unmerge_btn.setFixedHeight(32)
        unmerge_btn.setMinimumWidth(120)
        unmerge_btn.setCursor(Qt.PointingHandCursor)
        unmerge_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['danger_red']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: 6px;"
            f"  padding: 4px 12px; font-size: 11pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: #FEF2F2; }}"
        )
        unmerge_btn.clicked.connect(
            lambda _c=False, gid=int(group["id"]): self._on_unmerge(gid)
        )
        h.addWidget(unmerge_btn)
        return row

    def _on_unmerge(self, group_id: int) -> None:
        try:
            self._client.post(
                f"/tables/groups/{group_id}/unmerge/", json={},
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка", f"{e.message}\n[{e.code}]",
            )
            return
        self.groups_changed.emit()
        self.accept()
