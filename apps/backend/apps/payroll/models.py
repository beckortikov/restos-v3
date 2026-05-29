"""Phase 6 — Зарплата и табель.

Модели:
- `TimeEntry` — табель (clock_in / clock_out).
- `PayrollPeriod` — расчётный период (часы × ставка ± бонусы/штрафы).

`FinancialOperation` ещё не реализован (Phase 3 финансы), поэтому ссылка
на выплату хранится через nullable `paid_operation_id: int` — мы пометим её
PROTECT-FK после реализации финансов.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models


class TimeEntryStatus(models.TextChoices):
    OPEN = "open", "Открыта"
    CLOSED = "closed", "Закрыта"
    AUTO_CLOSED = "auto_closed", "Закрыта автоматом"


class TimeEntry(models.Model):
    """Одна запись табеля = один заход сотрудника (clock_in → clock_out).

    Если сотрудник не закрыл смену — manager может закрыть вручную, или
    cron-задача `auto_close_stale_time_entries` через N часов простоя
    (см. apps/payroll/services.py).
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="time_entries",
    )
    user = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="time_entries",
    )
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=TimeEntryStatus.choices,
        default=TimeEntryStatus.OPEN, db_index=True,
    )
    # Ставка на момент clock_in — snapshot. Если ставка в User поменяется
    # позже, исторические записи не пересчитываются.
    hourly_rate_snapshot = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Ставка/час на момент clock_in (snapshot)",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payroll_time_entries"
        ordering = ["-clock_in"]
        verbose_name = "Запись табеля"
        verbose_name_plural = "Записи табеля"
        indexes = [
            models.Index(fields=["restaurant", "user", "-clock_in"]),
            models.Index(fields=["restaurant", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(clock_out__isnull=True)
                    | models.Q(clock_out__gte=models.F("clock_in"))
                ),
                name="time_entry_clock_out_after_in",
            ),
        ]

    @property
    def hours_worked(self) -> Decimal:
        if self.clock_out is None:
            return Decimal("0.00")
        seconds = (self.clock_out - self.clock_in).total_seconds()
        return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return f"{self.user_id}: {self.clock_in:%Y-%m-%d %H:%M} → {self.clock_out or '...'}"


class PayrollPeriodStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    FINALIZED = "finalized", "Финализирован"
    PAID = "paid", "Выплачено"


class PayrollPeriod(models.Model):
    """Расчётный период сотрудника: с date by date, hours_worked × rate."""

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="payroll_periods",
    )
    user = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="payroll_periods",
    )
    period_start = models.DateField()
    period_end = models.DateField()

    hours_worked = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
    )
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Использованная ставка (среднее по TimeEntry.hourly_rate_snapshot)",
    )
    base_salary = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="hours_worked × hourly_rate",
    )
    bonuses = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
    )
    deductions = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="base_salary + bonuses - deductions",
    )
    note = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(
        max_length=12, choices=PayrollPeriodStatus.choices,
        default=PayrollPeriodStatus.DRAFT, db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    # FK будет переведён в PROTECT после реализации FinancialOperation (Phase 3).
    paid_operation_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="ID FinancialOperation (Phase 3, пока soft-ref)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payroll_periods"
        ordering = ["-period_start"]
        verbose_name = "Период зарплаты"
        verbose_name_plural = "Периоды зарплат"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="payroll_period_end_gte_start",
            ),
        ]
        indexes = [
            models.Index(fields=["restaurant", "user", "-period_start"]),
            models.Index(fields=["restaurant", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.period_start}..{self.period_end} = {self.total}"
