"""Сервисы super-admin: операции над License/Restaurant + статистика."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from datetime import timezone as tz
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.licensing.models import License, LicensePlan
from apps.orders.models import Order, OrderStatus
from apps.users.models import Restaurant
from common.exceptions import BusinessError

DUSHANBE = tz(timedelta(hours=5))
ZERO = Decimal("0.00")


# -------- License operations --------


def extend_license(*, license_obj: License, days: int) -> License:
    """Продлить лицензию на N дней от текущего expires_at (или now, если уже истекла)."""
    if days <= 0:
        raise BusinessError("INVALID_VALUE", "days должно быть > 0", 400)
    now = timezone.now()
    base = max(license_obj.expires_at, now)
    license_obj.expires_at = base + timedelta(days=days)
    # Если ранее была блокировка — снять её при продлении (опционально).
    license_obj.save(update_fields=["expires_at", "updated_at"])
    return license_obj


def change_plan(*, license_obj: License, plan: str) -> License:
    if plan not in LicensePlan.values:
        raise BusinessError("INVALID_VALUE", f"План {plan!r} не существует", 400)
    license_obj.plan = plan
    license_obj.save(update_fields=["plan", "updated_at"])
    return license_obj


def block_license(*, license_obj: License, reason: str) -> License:
    license_obj.is_blocked = True
    license_obj.block_reason = (reason or "").strip()[:255]
    license_obj.save(update_fields=["is_blocked", "block_reason", "updated_at"])
    return license_obj


def unblock_license(*, license_obj: License) -> License:
    license_obj.is_blocked = False
    license_obj.block_reason = ""
    license_obj.save(update_fields=["is_blocked", "block_reason", "updated_at"])
    return license_obj


# -------- Statistics --------


def _start_of_today_local() -> datetime:
    return datetime.combine(date.today(), time.min, tzinfo=DUSHANBE)


def restaurants_overview() -> list[dict]:
    """Список ресторанов с краткой инфой для дашборда (license + heartbeat + сегодняшняя выручка)."""
    now = timezone.now()
    today_start = _start_of_today_local()
    rows: list[dict] = []
    qs = Restaurant.objects.all().select_related("license").order_by("name")
    for r in qs:
        lic = getattr(r, "license", None)
        if lic is not None:
            grace_end = lic.expires_at + timedelta(days=License.GRACE_DAYS)
            if lic.is_blocked:
                status = "blocked"
            elif now > grace_end:
                status = "expired"
            elif now > lic.expires_at:
                status = "grace"
            else:
                status = "active"
        else:
            status = "no_license"

        rev = (
            Order.objects.filter(
                restaurant=r,
                status=OrderStatus.DONE,
                closed_at__gte=today_start,
            ).aggregate(s=Sum("service_charge_pct"))  # placeholder, см. ниже
        )
        # Считаем выручку через total per order вручную (Sum по @property total не работает)
        revenue = ZERO
        for o in Order.objects.filter(
            restaurant=r, status=OrderStatus.DONE, closed_at__gte=today_start,
        ).only("id"):
            revenue += o.total  # @property
        rows.append({
            "id": r.id,
            "name": r.name,
            "currency": r.currency,
            "license_status": status,
            "plan": lic.plan if lic else None,
            "expires_at": lic.expires_at.isoformat() if lic else None,
            "is_blocked": bool(lic and lic.is_blocked),
            "block_reason": (lic.block_reason if lic else "") or "",
            "last_heartbeat_at": (
                r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None
            ),
            "app_version": r.app_version or "",
            "today_revenue": str(revenue.quantize(Decimal("0.01"))),
        })
    return rows


def platform_stats() -> dict:
    """Сводная статистика по всей платформе для top-of-dashboard."""
    now = timezone.now()
    licenses = License.objects.all().only(
        "id", "plan", "expires_at", "is_blocked",
    )

    active = grace = expired = blocked = 0
    plan_counts: dict[str, int] = {}
    for lic in licenses:
        grace_end = lic.expires_at + timedelta(days=License.GRACE_DAYS)
        if lic.is_blocked:
            blocked += 1
        elif now > grace_end:
            expired += 1
        elif now > lic.expires_at:
            grace += 1
        else:
            active += 1
        plan_counts[lic.plan] = plan_counts.get(lic.plan, 0) + 1

    # «Живые» — пинговали в последний час
    live_threshold = now - timedelta(hours=1)
    live = Restaurant.objects.filter(
        last_heartbeat_at__gte=live_threshold,
    ).count()

    total_restaurants = Restaurant.objects.count()
    return {
        "total_restaurants": total_restaurants,
        "live_now": live,
        "license_status": {
            "active": active,
            "grace": grace,
            "expired": expired,
            "blocked": blocked,
        },
        "plan_counts": plan_counts,
    }
