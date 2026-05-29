# C-03 — Печать на стороне кассира

В MVP **печатает backend**, а не кассир. Cashier-app только инициирует печать (через `close_order`) и следит за статусом задания. Это упрощает архитектуру: принтер физически подключён к main POS-машине (где живёт Django), и backend — единственный, кто его трогает.

## Поток

```
[PaymentScreen]                       [Backend]
  POST /orders/{id}/close/  ────────►  close_order():
   {payment_method}                       transaction.atomic():
                                            Order.status = done
                                            free_table()
                                            enqueue_receipt_print(order)
                                              → PrintJob(status=pending)
                                              → WORKER_EVENT.set()
  ◄──────  { order, print_job: { id, status: "pending" } }

[ReceiptStatusScreen]
  слушает state.sse.print_job_updated  ◄── event: print_job.updated
                                              { id, status, retries, error }
   …
   на status="done" → закрыть окно
```

Никакого polling'а — статус задания приходит push'ом через SSE.

## Реализация в `pos/screens/receipt_status.py`

```python
class ReceiptStatusScreen(QDialog):
    def __init__(self, job_id: int, parent=None):
        super().__init__(parent)
        self.job_id = job_id
        self.setWindowTitle(f"Печать чека № {job_id}")
        self._build_ui()

        # сразу подгружаем текущее состояние, дальше живём по SSE
        try:
            job = state.client.get(f"/printing/jobs/{self.job_id}/")
            self._render(job)
        except ApiError as e:
            self._show_error(e.message)

        state.sse.print_job_updated.connect(self._on_event)

    def _on_event(self, payload: dict):
        if payload.get("id") != self.job_id:
            return
        self._render(payload)

    def _render(self, job: dict):
        s = job["status"]
        if s in ("pending", "printing"):
            self.spinner.show()
            self.label.setText(f"Печать чека… попытка {job.get('retries', 0)+1}")
        elif s == "done":
            self.spinner.hide()
            self.label.setText("✓ Готово")
            QTimer.singleShot(3000, self.accept)
        elif s == "failed":
            self.label.setText(f"Сбой, повтор автоматически. {(job.get('error') or '')[:80]}")
        elif s == "dead":
            self.spinner.hide()
            self.label.setText("✕ Принтер недоступен после 5 попыток.")
            self.btn_retry.setEnabled(True)

    def on_retry(self):
        try:
            state.client.post(f"/printing/jobs/{self.job_id}/retry/", idempotent=False)
            self.btn_retry.setEnabled(False)
        except ApiError as e:
            self._show_error(e.message)

    def closeEvent(self, ev):
        try: state.sse.print_job_updated.disconnect(self._on_event)
        except Exception: pass
        super().closeEvent(ev)
```

## Что НЕ делает кассир-приложение

- ❌ Не открывает USB/serial/network-сокет к принтеру. Это задача backend'а (`apps/printing/escpos_sender.py`).
- ❌ Не генерирует ESC/POS-команды. Шаблон чека целиком на сервере.
- ❌ Не хранит payload чека. При retry backend читает из `PrintJob.payload` (он «заморожен» на момент `close_order`).

Это сознательное упрощение: один путь печати, легко тестировать, легко мониторить из Django admin.

## В Phase 2

Когда добавится бегунок кухни и фискальные принтеры, появятся варианты:

- **Бегунок на станционный принтер**: backend сам кладёт в очередь нужный принтер по `MenuItem.station → Printer`.
- **Фискальный регистратор** (если потребуется по законодательству): отдельный воркер с другим SDK; cashier UI будет показывать «Чек ушёл в фискалку».
- **Печать с кассира напрямую** (если принтер физически подключён к кассиру, а не к Django-машине): добавим `cashier`-режим воркера, который читает свою «локальную» очередь через дополнительный endpoint `/printing/jobs/?for=cashier`. Но это уже усложнение; в MVP не делаем.

## Принтер в виртуальном режиме (для разработки)

В dev-окружении удобно не иметь реального принтера. Запуск:

```bash
PRINTER_VIRTUAL=true python manage.py print_worker
```

Backend будет писать рендер в `BASE_DIR/printouts/<job_id>.txt`. Cashier-app не отличает виртуальную печать от реальной — статус `done` приходит через 1–2 секунды, и кассир продолжает работать. Полезно при playback'е кейсов и в e2e-тестах waiter-PWA.
