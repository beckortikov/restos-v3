# B-05 — Печать чеков

В MVP печатается **только гостевой чек** при закрытии заказа. Бегунки кухни, отмена, отчёт смены — Phase 2.

## Стек

- `python-escpos>=3.1` — поддержка USB / TCP / Serial. Встроенная кодовая страница CP866 (для кириллицы).
- Воркер — отдельный процесс / поток `python manage.py print_worker`. Не использует Celery/Redis.

## Модели

```python
# apps/printing/models.py

class PrinterKind(models.TextChoices):
    USB    = "usb",    "USB"
    TCP    = "tcp",    "TCP"
    SERIAL = "serial", "Serial"


class Printer(models.Model):
    restaurant = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE)
    name       = models.CharField(max_length=64)
    kind       = models.CharField(max_length=8, choices=PrinterKind.choices)
    address    = models.CharField(max_length=128)
    # tcp:    "192.168.1.50:9100"
    # usb:    "0x04b8:0x0202"   (vendor:product)
    # serial: "/dev/ttyUSB0:9600"
    is_default = models.BooleanField(default=True)
    is_active  = models.BooleanField(default=True)


class PrintJobStatus(models.TextChoices):
    PENDING  = "pending",  "Ожидает"
    PRINTING = "printing", "Печатается"
    DONE     = "done",     "Готово"
    FAILED   = "failed",   "Ошибка"
    DEAD     = "dead",     "Не доставлено"


class PrintJob(models.Model):
    restaurant   = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE)
    type         = models.CharField(max_length=16, default="receipt")  # MVP: только receipt
    payload      = models.JSONField()
    printer      = models.ForeignKey(Printer, on_delete=models.PROTECT)
    status       = models.CharField(max_length=10, choices=PrintJobStatus.choices,
                                    default=PrintJobStatus.PENDING, db_index=True)
    retries      = models.PositiveSmallIntegerField(default=0)
    scheduled_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at   = models.DateTimeField(null=True, blank=True)
    finished_at  = models.DateTimeField(null=True, blank=True)
    error        = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    BACKOFF_SECONDS = [10, 30, 60, 300, 900]   # 10s, 30s, 1m, 5m, 15m
    MAX_RETRIES = len(BACKOFF_SECONDS)
```

## Сервис очереди

```python
# apps/printing/services.py

WORKER_EVENT = threading.Event()    # «есть работа» — будит воркер


def enqueue_receipt_print(order) -> PrintJob:
    printer = Printer.objects.filter(
        restaurant=order.restaurant, is_default=True, is_active=True
    ).first()
    if not printer:
        raise BusinessError("PRINTER_UNAVAILABLE",
                            "Принтер по умолчанию не настроен", 503)

    payload = build_receipt_payload(order)
    job = PrintJob.objects.create(
        restaurant=order.restaurant, type="receipt",
        payload=payload, printer=printer,
        status=PrintJobStatus.PENDING,
        scheduled_at=timezone.now(),
    )
    WORKER_EVENT.set()
    return job


def build_receipt_payload(order) -> dict:
    """Полностью «замораживает» данные заказа, чтобы при retry они не зависели от БД."""
    return {
        "restaurant": {
            "name": order.restaurant.name,
            "address": order.restaurant.address,
            "phone": order.restaurant.phone,
            "currency": order.restaurant.currency,
        },
        "order": {
            "id": order.id,
            "table": order.table.name,
            "guests": order.guests_count,
            "waiter": order.waiter.full_name,
            "cashier": order.cashier.full_name if order.cashier else "",
            "closed_at": order.closed_at.isoformat() if order.closed_at else "",
            "payment_method": order.payment_method or "",
            "total": str(order.total),
        },
        "items": [
            {"name": it.name_at_order, "qty": it.qty,
             "price": str(it.price_at_order), "subtotal": str(it.subtotal)}
            for it in order.items.all() if it.cancelled_at is None
        ],
    }
```

## Воркер

```python
# apps/printing/management/commands/print_worker.py

class Command(BaseCommand):
    help = "Запускает воркер очереди печати"

    def handle(self, *args, **opts):
        self.stdout.write("print_worker started")
        while True:
            self._tick()
            # ждём либо нового события, либо ближайшего scheduled_at
            wait = self._next_wait()
            WORKER_EVENT.wait(timeout=wait)
            WORKER_EVENT.clear()

    def _tick(self):
        now = timezone.now()
        # одна выборка под FOR UPDATE SKIP LOCKED — конкурентно безопасно
        with transaction.atomic():
            job = (PrintJob.objects
                   .select_for_update(skip_locked=True)
                   .filter(status__in=[PrintJobStatus.PENDING, PrintJobStatus.FAILED],
                           scheduled_at__lte=now)
                   .order_by("scheduled_at").first())
            if not job:
                return
            job.status = PrintJobStatus.PRINTING
            job.started_at = now
            job.save(update_fields=["status", "started_at"])

        try:
            send_to_printer(job)
            job.status = PrintJobStatus.DONE
            job.finished_at = timezone.now()
            job.error = ""
            job.save(update_fields=["status", "finished_at", "error"])
        except Exception as exc:
            job.retries += 1
            if job.retries >= PrintJob.MAX_RETRIES:
                job.status = PrintJobStatus.DEAD
                job.finished_at = timezone.now()
            else:
                job.status = PrintJobStatus.FAILED
                delay = PrintJob.BACKOFF_SECONDS[job.retries - 1]
                job.scheduled_at = timezone.now() + timedelta(seconds=delay)
            job.error = repr(exc)[:5000]
            job.save(update_fields=["retries", "status", "scheduled_at",
                                    "finished_at", "error"])
```

## ESC/POS отправитель

```python
# apps/printing/escpos_sender.py
from escpos.printer import Usb, Network, Serial

def send_to_printer(job):
    if settings.PRINTER_VIRTUAL:
        return _write_to_disk(job)

    p = job.printer
    if p.kind == "tcp":
        host, port = p.address.split(":")
        printer = Network(host, int(port), timeout=5)
    elif p.kind == "usb":
        vid, pid = p.address.split(":")
        printer = Usb(int(vid, 16), int(pid, 16))
    elif p.kind == "serial":
        dev, baud = p.address.split(":")
        printer = Serial(dev, baudrate=int(baud))
    else:
        raise ValueError(f"Unknown printer kind {p.kind}")

    try:
        render_receipt(printer, job.payload)
        printer.cut()
    finally:
        printer.close()


def _write_to_disk(job):
    out = Path(settings.PRINTER_OUTPUT_DIR) / f"{job.id}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_format_text_preview(job.payload), encoding="utf-8")
```

## Шаблон чека

```python
# apps/printing/templates/receipt.py
from datetime import datetime, timezone as tz, timedelta

DUSHANBE = tz(timedelta(hours=5))
PM_RU = {"cash": "Наличные", "card": "Карта", "transfer": "Перевод"}

def render_receipt(p, data):
    r = data["restaurant"]; o = data["order"]
    p.set(align="center", text_type="B", width=2, height=2)
    p.text(f"{r['name']}\n")
    p.set(align="center", text_type="NORMAL", width=1, height=1)
    if r.get("address"): p.text(f"{r['address']}\n")
    if r.get("phone"):   p.text(f"тел. {r['phone']}\n")
    p.text("─" * 32 + "\n")

    p.set(align="left")
    closed = datetime.fromisoformat(o["closed_at"]).astimezone(DUSHANBE)
    p.text(f"Чек № {o['id']:<6}  {closed.strftime('%d.%m.%Y %H:%M')}\n")
    p.text(f"Стол: {o['table']:<10}  Гостей: {o['guests']}\n")
    p.text(f"Официант: {o['waiter']}\n")
    if o['cashier']:
        p.text(f"Кассир:   {o['cashier']}\n")
    p.text("─" * 32 + "\n")

    for it in data["items"]:
        p.text(f"{it['name']}\n")
        line = f"  {it['qty']} x {it['price']} = {it['subtotal']}"
        p.text(line.rjust(32) + "\n")
    p.text("─" * 32 + "\n")

    p.set(text_type="B")
    p.text(f"ИТОГО: {o['total']:>20} {r['currency']}\n")
    p.set(text_type="NORMAL")
    p.text(f"Оплата: {PM_RU.get(o['payment_method'], o['payment_method']):>22}\n")
    p.text("─" * 32 + "\n")

    p.set(align="center")
    p.text("Спасибо за визит!\n\n\n")
```

`escpos.printer.*` сам шлёт `ESC @` (reset), `FS .` (disable Kanji) и автоматом включает CP866 при `set(charcode_table='CP866')` или вызовом `_dev._raw(b'\x1bt\x11')` если нужно вручную. Кириллица из примера выше пройдёт корректно.

## Эндпоинты

```
GET    /api/v1/printing/printers/          список настроенных принтеров
GET    /api/v1/printing/jobs/{id}/         {id, status, retries, error, scheduled_at}
POST   /api/v1/printing/jobs/{id}/retry/   reset status=PENDING, scheduled_at=now → бужу воркер
```

```python
# apps/printing/views.py

class PrinterViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PrinterSerializer
    permission_classes = [IsCashier]

    def get_queryset(self):
        return Printer.objects.filter(restaurant=self.request.user.restaurant)


class PrintJobViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PrintJobSerializer
    permission_classes = [IsCashier]

    def get_queryset(self):
        return PrintJob.objects.filter(restaurant=self.request.user.restaurant)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        job = self.get_object()
        if job.status == PrintJobStatus.DONE:
            return Response({"data": PrintJobSerializer(job).data})
        job.status = PrintJobStatus.PENDING
        job.scheduled_at = timezone.now()
        job.error = ""
        job.save(update_fields=["status", "scheduled_at", "error"])
        WORKER_EVENT.set()
        return Response({"data": PrintJobSerializer(job).data})
```

## Тесты

`apps/printing/tests/`:

1. `test_escpos_snapshot.py` — рендерим чек в `BytesIO` и сверяем побайтово с `snapshots/receipt_basic.bin`. Изменение шаблона — осознанный пересмотр снапшота.
2. `test_worker_backoff.py` — мок `send_to_printer` бросает `ConnectionError` 5 раз → проверяем, что `retries` доходит до 5 и статус → `dead`. `scheduled_at` после i-й попытки = `now + BACKOFF_SECONDS[i-1]`.
3. `test_worker_concurrent.py` — два воркера в потоках одновременно: оба не возьмут одну job (`select_for_update(skip_locked=True)`).
4. `test_virtual_printer.py` — `PRINTER_VIRTUAL=True` → файл `printouts/<id>.txt` создан.

## Замечания

- В Phase 2 добавим bot для бегунков кухни (`type="runner"`), отмены (`type="cancel"`), отчёт смены (`type="shift_close"`). Сейчас payload-формат специфичен для `receipt`.
- Запасной путь: если принтер недоступен > 15 минут (попытка 5 → `dead`), кассир всегда может вручную нажать «Повторить» из экрана PySide или из Django admin. До тех пор payload надёжно лежит в JSONB и не зависит от текущего состояния БД.
