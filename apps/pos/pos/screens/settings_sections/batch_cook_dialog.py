"""Phase 7E — диалог «+N порций» для заготовочных блюд.

Cook (или менеджер) нажимает «Заготовить» рядом с batch-блюдом →
вводит N + note → backend списывает сырьё по техкарте × N и
увеличивает prepared_qty на N.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.tokens import COLORS, RADIUS, SPACING


class BatchCookDialog(QDialog):
    """Заготовить N порций batch-блюда."""

    def __init__(
        self,
        client: ApiClient,
        item: dict,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._item = item
        self.setWindowTitle("Заготовить партию")
        self.setModal(True)
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['bg_white']}; }}")
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(
            SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"]
        )
        v.setSpacing(SPACING["lg"])

        title = QLabel("Заготовить партию")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            f" font-size: 16pt; font-weight: 700;"
        )
        v.addWidget(title)

        ctx = QLabel(
            f"<b>{self._item.get('name', '?')}</b><br/>"
            f"<span style='color:#64748B; font-size:10pt'>"
            f"Готово сейчас: {self._item.get('prepared_qty', 0)} порций"
            f"</span>"
        )
        ctx.setStyleSheet(
            f"background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px; padding: 12px;"
        )
        v.addWidget(ctx)

        form = QFormLayout()
        form.setSpacing(SPACING["md"])

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 9999)
        self.qty_spin.setValue(10)
        self.qty_spin.setSuffix(" порций")
        self.qty_spin.setStyleSheet(self._field_qss())
        self.qty_spin.setFixedHeight(40)
        form.addRow(self._lbl("Сколько заготовили"), self.qty_spin)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Утренняя варка (необязательно)")
        self.note_edit.setStyleSheet(self._field_qss())
        self.note_edit.setFixedHeight(40)
        form.addRow(self._lbl("Заметка"), self.note_edit)

        v.addLayout(form)

        hint = QLabel(
            "<span style='color:#64748B; font-size:10pt'>"
            "Сырьё по техкарте × N будет автоматически списано со склада."
            "</span>"
        )
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setFixedHeight(40)
        cancel.setMinimumWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(self._cancel_qss())
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        submit = QPushButton("Заготовить")
        submit.setFixedHeight(40)
        submit.setMinimumWidth(160)
        submit.setCursor(Qt.PointingHandCursor)
        submit.setStyleSheet(self._submit_qss())
        submit.clicked.connect(self._submit)
        btns.addWidget(submit)
        v.addLayout(btns)

    def _lbl(self, t: str) -> QLabel:
        l = QLabel(t)
        l.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            f" font-size: 11pt; font-weight: 600;"
        )
        return l

    def _field_qss(self) -> str:
        return (
            f"QLineEdit, QSpinBox {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt; min-height: 24px;"
            f"}}"
        )

    def _cancel_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )

    def _submit_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background: {COLORS['success_green']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 20px; font-size: 12pt; font-weight: 700;"
            f"}}"
        )

    def _submit(self) -> None:
        qty = int(self.qty_spin.value())
        note = self.note_edit.text().strip()
        try:
            self._client.post(
                f"/menu/items/{self._item['id']}/batch_cook/",
                json={"qty": qty, "note": note},
                idempotent=True,
            )
        except ApiError as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось списать заготовку: [{e.code}] {e.message}",
            )
            return
        self.accept()
