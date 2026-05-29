"""Phase 6 — сервисный слой для табеля и зарплат."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from common.exceptions import BusinessError

from .models import (
    PayrollPeriod,
    PayrollPeriodStatus,
    TimeEntry,
    TimeEntryStatus,
)


# ─── TimeEntry ──────────────────────────────────────────────────────────────


@transaction.atomic
def clock_in(*, user, restaurant, note: str = "") -> TimeEntry:
    """Открыть смену сотрудника. Если уже есть open — бросаем ошибку."""
    if not user.is_active:
        raise BusinessError("USER_INACTIVE", "Сотрудник деактивирован", 400)
    existing = TimeEntry.objects.filter(
        user=user, restaurant=restaurant, status=TimeEntryStatus.OPEN
    ).first()
    if existing is not None:
        raise BusinessError(
            "ALREADY_CLOCKED_IN",
            f"Смена уже открыта в {existing.clock_in:%H:%M}", 409,
        )
    entry = TimeEntry.objects.create(
        restaurant=restaurant,
        user=user,
        clock_in=timezone.now(),
        status=TimeEntryStatus.OPEN,
        hourly_rate_snapshot=user.hourly_rate or Decimal("0.00"),
        note=note or "",
    )
    return entry


@transaction.atomic
def clock_out(*, user, restaurant, note: str = "") -> TimeEntry:
    """Закрыть последнюю открытую смену сотрудника."""
    entry = TimeEntry.objects.select_for_update().filter(
        user=user, restaurant=restaurant, status=TimeEntryStatus.OPEN
    ).order_by("-clock_in").first()
    if entry is None:
        raise BusinessError("NOT_CLOCKED_IN", "Нет открытой смены", 404)
    entry.clock_out = timezone.now()
    entry.status = TimeEntryStatus.CLOSED
    if note:
        entry.note = (entry.note + " | " + note).strip(" |")
    entry.save(update_fields=["clock_out", "status", "note", "updated_at"])
    return entry


def auto_close_stale_entries(*, restaurant=None, max_hours: int = 16) -> int:
    """Авто-закрытие зависших OPEN-записей старше max_hours.

    Запускается cron'ом раз в час. Возвращает кол-во закрытых.
    """
    qs = TimeEntry.objects.filter(status=TimeEntryStatus.OPEN)
    if restaurant is not None:
        qs = qs.filter(restaurant=restaurant)
    cutoff = timezone.now() - timedelta(hours=max_hours)
    stale = qs.filter(clock_in__lt=cutoff)
    count = 0
    for entry in stale:
        with transaction.atomic():
            entry.clock_out = entry.clock_in + timedelta(hours=max_hours)
            entry.status = TimeEntryStatus.AUTO_CLOSED
            entry.save(update_fields=["clock_out", "status", "updated_at"])
            count += 1
    return count


# ─── PayrollPeriod ──────────────────────────────────────────────────────────


def _to_aware_dt(d: date, *, end_of_day: bool = False) -> datetime:
    t = datetime.min.time().replace(hour=23, minute=59, second=59) if end_of_day \
        else datetime.min.time()
    return timezone.make_aware(datetime.combine(d, t))


@transaction.atomic
def calculate_period(
    *,
    user,
    restaurant,
    period_start: date,
    period_end: date,
    bonuses: Decimal = Decimal("0"),
    deductions: Decimal = Decimal("0"),
    note: str = "",
) -> PayrollPeriod:
    """Создать DRAFT PayrollPeriod, посчитать часы из TimeEntry."""
    if period_end < period_start:
        raise BusinessError("INVALID_VALUE", "period_end < period_start", 400)

    start_dt = _to_aware_dt(period_start)
    end_dt = _to_aware_dt(period_end, end_of_day=True)

    entries = TimeEntry.objects.filter(
        user=user, restaurant=restaurant,
        clock_in__gte=start_dt, clock_in__lte=end_dt,
        clock_out__isnull=False,
    )

    total_hours = Decimal("0.00")
    weighted_rate_sum = Decimal("0.00")
    for e in entries:
        h = e.hours_worked
        total_hours += h
        weighted_rate_sum += h * (e.hourly_rate_snapshot or Decimal("0"))

    if total_hours > 0:
        avg_rate = (weighted_rate_sum / total_hours).quantize(Decimal("0.01"))
    else:
        avg_rate = Decimal("0.00")
    base_salary = (total_hours * avg_rate).quantize(Decimal("0.01"))
    total = base_salary + Decimal(bonuses or 0) - Decimal(deductions or 0)

    period = PayrollPeriod.objects.create(
        restaurant=restaurant,
        user=user,
        period_start=period_start,
        period_end=period_end,
        hours_worked=total_hours,
        hourly_rate=avg_rate,
        base_salary=base_salary,
        bonuses=Decimal(bonuses or 0),
        deductions=Decimal(deductions or 0),
        total=total,
        note=note or "",
        status=PayrollPeriodStatus.DRAFT,
    )
    return period


@transaction.atomic
def finalize_period(*, period: PayrollPeriod) -> PayrollPeriod:
    """Зафиксировать период — после этого править только bonuses/deductions нельзя."""
    if period.status != PayrollPeriodStatus.DRAFT:
        raise BusinessError(
            "INVALID_STATE",
            f"Период в статусе {period.status}, финализация невозможна", 400,
        )
    period.status = PayrollPeriodStatus.FINALIZED
    period.save(update_fields=["status", "updated_at"])
    return period


@transaction.atomic
def pay_period(*, period: PayrollPeriod, paid_operation_id: int | None = None) -> PayrollPeriod:
    """Пометить период как выплаченный + проставить FK на FinancialOperation.

    `paid_operation_id` — внешний ID (Phase 3 пока не существует, soft-ref).
    """
    if period.status not in (
        PayrollPeriodStatus.FINALIZED, PayrollPeriodStatus.DRAFT,
    ):
        raise BusinessError(
            "INVALID_STATE",
            f"Период уже {period.status}", 400,
        )
    period.status = PayrollPeriodStatus.PAID
    period.paid_at = timezone.now()
    if paid_operation_id is not None:
        period.paid_operation_id = int(paid_operation_id)
    period.save(update_fields=["status", "paid_at", "paid_operation_id", "updated_at"])
    return period
