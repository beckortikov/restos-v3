from django.db import models
from django.utils import timezone


class PrinterKind(models.TextChoices):
    USB = "usb", "USB"
    TCP = "tcp", "TCP/IP"
    SERIAL = "serial", "Serial"
    VIRTUAL = "virtual", "Виртуальный (файл)"


class PrintJobStatus(models.TextChoices):
    PENDING = "pending", "В очереди"
    PRINTING = "printing", "Печатается"
    DONE = "done", "Готово"
    FAILED = "failed", "Ошибка (повтор)"
    DEAD = "dead", "Не доставлено"


class PrintJobKind(models.TextChoices):
    GUEST_RECEIPT = "guest_receipt", "Гостевой чек"
    KITCHEN_ORDER = "kitchen_order", "Заказ на кухню"
    BAR_ORDER = "bar_order", "Заказ в бар"
    PRE_BILL = "pre_bill", "Пре-чек"
    REFUND_RECEIPT = "refund_receipt", "Чек возврата"
    Z_REPORT = "z_report", "Z-отчёт по смене"
    X_REPORT = "x_report", "X-отчёт (промежуточный)"
    # Бегунок отмены — печатается на станционный принтер кухни/бара когда
    # уже принятая в работу позиция отменяется. Повар видит «ОТМЕНА: Плов ×2».
    CANCEL_RUNNER = "cancel_runner", "Бегунок отмены"
    # Бегунок «готово к выдаче» — печатается на станционном/выдачном принтере
    # когда повар переводит позицию в READY. Официант видит и забирает блюдо.
    READY_RUNNER = "ready_runner", "Бегунок готовности"


class PaperSize(models.TextChoices):
    P_58MM = "58mm", "58 мм"
    P_76MM = "76mm", "76 мм"
    P_80MM = "80mm", "80 мм"


class Printer(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="printers"
    )
    name = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=PrinterKind.choices)
    address = models.CharField(max_length=128, blank=True)
    paper_size = models.CharField(
        max_length=8, choices=PaperSize.choices, default=PaperSize.P_80MM,
        help_text="Ширина термобумаги — влияет на ширину строки ESC/POS-чека",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "printers"
        verbose_name = "Принтер"
        verbose_name_plural = "Принтеры"

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class PrintJob(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="print_jobs"
    )
    printer = models.ForeignKey(
        Printer, on_delete=models.PROTECT, null=True, blank=True, related_name="jobs"
    )
    order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="print_jobs"
    )
    kind = models.CharField(
        max_length=24, choices=PrintJobKind.choices, default=PrintJobKind.GUEST_RECEIPT
    )
    status = models.CharField(
        max_length=12,
        choices=PrintJobStatus.choices,
        default=PrintJobStatus.PENDING,
        db_index=True,
    )
    payload = models.JSONField(default=dict)
    retries = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    BACKOFF_SECONDS = (10, 30, 60, 300, 900)
    MAX_RETRIES = len(BACKOFF_SECONDS)

    class Meta:
        db_table = "print_jobs"
        ordering = ["-scheduled_at"]
        verbose_name = "Задание печати"
        verbose_name_plural = "Задания печати"

    def __str__(self) -> str:
        return f"PrintJob #{self.id} [{self.status}]"


class PrintStation(models.Model):
    """Точка печати (цех / бар / касса) — динамическая, admin создаёт сколько надо.

    Примеры: «Горячий цех», «Холодный цех», «Бар», «Витрина», «Касса».

    `system_code`:
    - None → обычная станция (цех, бар), может быть удалена
    - 'cashier' → системная касса для guest_receipt / pre_bill / refund_receipt
    - 'kitchen' → дефолтный fallback для блюд без явной привязки

    System-станции (system_code != None) нельзя удалить — гарантия, что
    есть куда отправлять чеки гостю.
    """

    SYSTEM_CASHIER = "cashier"
    SYSTEM_KITCHEN = "kitchen"

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="print_stations"
    )
    name = models.CharField(max_length=64)
    system_code = models.CharField(
        max_length=16, blank=True, default="",
        help_text="cashier / kitchen для системных станций; пусто для обычных цехов",
    )
    printer = models.ForeignKey(
        Printer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stations",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "print_stations"
        ordering = ["sort_order", "name"]
        verbose_name = "Цех / станция печати"
        verbose_name_plural = "Цеха / станции печати"

    def __str__(self) -> str:
        return f"{self.name} → {self.printer or '—'}"

    @property
    def is_system(self) -> bool:
        return bool(self.system_code)
