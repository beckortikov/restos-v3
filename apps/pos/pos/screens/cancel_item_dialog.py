"""Отмена позиции заказа — модалка с обязательным полем «Причина».

В дизайне frame 3 кнопка «×» на каждой позиции в правой панели → этот диалог.
Backend: POST /orders/{id}/cancel_item/ body {item_id, reason}.
Если позиция последняя активная — backend сам отменит весь заказ.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pos.http_client import ApiClient, ApiError
from pos.resources.icons import qpixmap
from pos.resources.tokens import COLORS, RADIUS, SPACING


class _CancelItemWorker(QObject):
    success = Signal(dict)
    error = Signal(object)

    def __init__(
        self, client: ApiClient, order_id: int, item_id: int, reason: str
    ) -> None:
        super().__init__()
        self.client = client
        self.order_id = order_id
        self.item_id = item_id
        self.reason = reason

    def run(self) -> None:
        try:
            data = self.client.post(
                f"/orders/{self.order_id}/cancel_item/",
                json={"item_id": self.item_id, "reason": self.reason},
            )
            self.success.emit(data if isinstance(data, dict) else {})
        except ApiError as e:
            self.error.emit(e)


class CancelItemDialog(QDialog):
    """Подтверждение отмены позиции с textarea «Причина»."""

    item_cancelled = Signal(dict)

    def __init__(
        self,
        order_id: int,
        item: dict,
        client: ApiClient,
        parent: QWidget | None = None,
        reasons: list[dict] | None = None,
    ) -> None:
        super().__init__(parent)
        self._order_id = order_id
        self._item = item
        self._client = client
        self._thread: QThread | None = None
        self._worker: _CancelItemWorker | None = None
        # Список причин — приходит готовым из родителя (он кэширует),
        # либо подтянем сами через /cancel_reasons/?kind=item.
        self._reasons: list[dict] = reasons if reasons is not None else self._fetch_reasons()

        self.setWindowTitle("Отмена позиции")
        self.setModal(True)
        self.setFixedWidth(480)
        self._build()

    def _fetch_reasons(self) -> list[dict]:
        try:
            data = self._client.get(
                "/cancel_reasons/", params={"kind": "item", "is_active": "true"}
            )
            items = data if isinstance(data, list) else (data or {}).get("data", [])
            return [r for r in items if r.get("is_active", True)]
        except ApiError:
            return []

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-bottom: 1px solid {COLORS['border_light']};"
        )
        layout = QHBoxLayout(h)
        layout.setContentsMargins(SPACING["xl"], 0, SPACING["xl"], 0)
        layout.setSpacing(SPACING["sm"])

        icon = QLabel()
        icon.setPixmap(qpixmap("alert-triangle", COLORS["danger_red"], 22))
        layout.addWidget(icon)

        title = QLabel("Отменить позицию?")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14pt; font-weight: 700;"
        )
        layout.addWidget(title)
        layout.addStretch(1)
        return h

    def _build_body(self) -> QWidget:
        body = QFrame()
        body.setStyleSheet(f"background: {COLORS['bg_white']};")
        v = QVBoxLayout(body)
        v.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        v.setSpacing(SPACING["md"])

        # Item info
        name = self._item.get("name_at_order", "?")
        qty = int(self._item.get("qty", 1))
        sub = self._item.get("subtotal", "0.00")
        info = QLabel(f"«{name}» × {qty}  —  {sub} TJS")
        info.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13pt; font-weight: 600;"
            f" padding: 12px;"
            f" background: {COLORS['bg_light']};"
            f" border: 1px solid {COLORS['border_light']};"
            f" border-radius: {RADIUS['sm']}px;"
        )
        v.addWidget(info)

        warn = QLabel(
            "Если это последняя активная позиция, заказ будет отменён целиком."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10pt;"
        )
        v.addWidget(warn)

        # Чипы быстрого выбора
        if self._reasons:
            chips_lbl = QLabel("Быстрый выбор:")
            chips_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 10pt; margin-top: 4px;"
            )
            v.addWidget(chips_lbl)
            v.addWidget(self._build_chips())

        reason_lbl = QLabel("Причина отмены (обязательно)")
        reason_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 11pt; font-weight: 600;"
            f" margin-top: 4px;"
        )
        v.addWidget(reason_lbl)

        self._reason_edit = QTextEdit()
        self._reason_edit.setFixedHeight(64)
        self._reason_edit.setPlaceholderText(
            "Выберите готовую причину выше или впишите свою…"
        )
        self._reason_edit.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {COLORS['bg_white']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 8px 12px;"
            f"  color: {COLORS['text_primary']};"
            f"  font-size: 12pt;"
            f"}}"
            f"QTextEdit:focus {{ border: 1.5px solid {COLORS['danger_red']}; }}"
        )
        v.addWidget(self._reason_edit)
        return body

    def _build_chips(self) -> QWidget:
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(SPACING["sm"])

        cols = 2
        sorted_reasons = sorted(
            self._reasons,
            key=lambda r: (int(r.get("sort_order", 0)), r.get("label", "")),
        )
        for i, r in enumerate(sorted_reasons):
            chip = QPushButton(r.get("label", ""))
            chip.setFixedHeight(36)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(
                f"QPushButton {{"
                f"  background: {COLORS['bg_light']};"
                f"  color: {COLORS['text_primary']};"
                f"  border: 1px solid {COLORS['border_light']};"
                f"  border-radius: 18px;"  # half of 36 — pill shape
                f"  padding: 0 14px;"
                f"  font-size: 11pt; font-weight: 600;"
                f"  text-align: center;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background: #FEE2E2;"
                f"  border-color: {COLORS['danger_red']};"
                f"  color: {COLORS['danger_red']};"
                f"}}"
            )
            chip.clicked.connect(
                lambda _c=False, label=r.get("label", ""): self._pick_reason(label)
            )
            grid.addWidget(chip, i // cols, i % cols)
        return holder

    def _pick_reason(self, label: str) -> None:
        self._reason_edit.setPlainText(label)

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"background: {COLORS['bg_white']};"
            f" border-top: 1px solid {COLORS['border_light']};"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(SPACING["xl"], SPACING["md"], SPACING["xl"], SPACING["md"])
        h.setSpacing(SPACING["sm"])

        cancel = QPushButton("Не отменять")
        cancel.setFixedHeight(44)
        cancel.setMinimumWidth(140)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['bg_white']};"
            f"  color: {COLORS['text_primary']};"
            f"  border: 1px solid {COLORS['border_light']};"
            f"  border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {COLORS['bg_gray']}; }}"
        )
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)
        h.addStretch(1)

        self._submit_btn = QPushButton("Отменить позицию")
        self._submit_btn.setFixedHeight(44)
        self._submit_btn.setMinimumWidth(180)
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger_red']};"
            f"  color: {COLORS['text_white']};"
            f"  border: none; border-radius: {RADIUS['sm']}px;"
            f"  padding: 0 18px; font-size: 12pt; font-weight: 700;"
            f"}}"
            f"QPushButton:hover:enabled {{ background: #B91C1C; }}"
            f"QPushButton:disabled {{ background: #FCA5A5; color: white; }}"
        )
        self._submit_btn.clicked.connect(self._submit)
        h.addWidget(self._submit_btn)
        return f

    def _submit(self) -> None:
        if self._thread is not None:
            return
        reason = self._reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Ошибка", "Укажите причину отмены")
            return
        self._submit_btn.setEnabled(False)
        self._submit_btn.setText("Отмена…")

        thread = QThread(self)
        worker = _CancelItemWorker(
            self._client, int(self._order_id), int(self._item["id"]), reason
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_done)
        worker.error.connect(self._on_failed)
        worker.success.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        # Удержать worker, иначе Python GC удалит его до старта потока.
        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup(self) -> None:
        t = self._thread
        self._thread = None
        self._worker = None
        if t is not None:
            t.deleteLater()

    def _on_done(self, data: dict) -> None:
        self.item_cancelled.emit(data)
        self.accept()

    def _on_failed(self, exc: ApiError) -> None:
        self._submit_btn.setEnabled(True)
        self._submit_btn.setText("Отменить позицию")
        QMessageBox.warning(
            self, "Ошибка", f"Не удалось отменить позицию: {exc.message}"
        )
