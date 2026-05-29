"""Restaurant-side: сбор агрегатов из локальной БД."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from datetime import timezone as tz
from decimal import Decimal

from django.utils import timezone

DUSHANBE = tz(timedelta(hours=5))
ZERO = Decimal("0.00")


def _local_today() -> date:
    return timezone.now().astimezone(DUSHANBE).date()


def _local_day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=DUSHANBE)


def collect_catalog(*, restaurant) -> dict:
    """Снимок каталога меню для cloud.

    Содержит только публичные данные: имя ресторана, список категорий и
    блюд с минимумом полей. НЕ включает: cogs, ингредиенты, техкарты,
    image-файлы. Это коммерчески чувствительно и остаётся локально.
    """
    from apps.menu.models import Category, MenuItem

    items_by_cat: dict[int, int] = {}
    item_rows: list[dict] = []

    for it in MenuItem.objects.filter(restaurant=restaurant).select_related(
        "category"
    ).only(
        "id", "category_id", "name", "price",
        "kind", "is_available", "unit", "sort_order",
    ):
        items_by_cat[it.category_id] = items_by_cat.get(it.category_id, 0) + 1
        item_rows.append({
            "category": it.category.name if it.category else "",
            "name": it.name,
            "price": str(it.price),
            "kind": it.kind,
            "unit": it.unit,
            "is_available": it.is_available,
            "sort_order": it.sort_order,
        })

    categories = []
    for c in Category.objects.filter(restaurant=restaurant).order_by("sort_order"):
        categories.append({
            "name": c.name,
            "sort_order": c.sort_order,
            "items_count": items_by_cat.get(c.id, 0),
        })

    active = sum(1 for r in item_rows if r["is_available"])
    return {
        "restaurant": {
            "name": restaurant.name,
            "currency": restaurant.currency,
        },
        "categories": categories,
        "items": item_rows,
        "totals": {
            "categories": len(categories),
            "items": len(item_rows),
            "active_items": active,
        },
    }


def collect_telemetry(*, restaurant) -> dict:
    """Собирает агрегаты для текущего дня и возвращает готовый payload.

    Использует локальную БД ресторана (Orders, CashShift, Restaurant).
    Чем меньше JOIN-ов — тем лучше, sync-команда часто запускается на cron.
    """
    from apps.orders.models import Order, OrderStatus
    from apps.shifts.models import CashShift, ShiftStatus

    today = _local_today()
    month_start = today.replace(day=1)
    today_start_utc = _local_day_start(today)
    month_start_utc = _local_day_start(month_start)
    now = timezone.now()

    # Сегодняшние закрытые заказы
    today_closed = Order.objects.filter(
        restaurant=restaurant, status=OrderStatus.DONE,
        closed_at__gte=today_start_utc,
    )
    daily_count = today_closed.count()
    daily_revenue = ZERO
    last_order_at = None
    for o in today_closed.only("id", "closed_at"):
        daily_revenue += o.total
        if last_order_at is None or (o.closed_at and o.closed_at > last_order_at):
            last_order_at = o.closed_at

    # Месячная выручка
    mtd_revenue = ZERO
    for o in Order.objects.filter(
        restaurant=restaurant, status=OrderStatus.DONE,
        closed_at__gte=month_start_utc,
    ).only("id"):
        mtd_revenue += o.total

    # Если сегодня заказов не было — last_order_at берём за всё время
    if last_order_at is None:
        last = (
            Order.objects.filter(restaurant=restaurant, status=OrderStatus.DONE)
            .order_by("-closed_at").only("closed_at").first()
        )
        if last is not None:
            last_order_at = last.closed_at

    open_shifts = CashShift.objects.filter(
        restaurant=restaurant, status=ShiftStatus.OPEN,
    ).count()

    return {
        "business_date": today.isoformat(),
        "captured_at": now.isoformat(),
        "daily_revenue": str(daily_revenue.quantize(Decimal("0.01"))),
        "daily_orders_count": daily_count,
        "mtd_revenue": str(mtd_revenue.quantize(Decimal("0.01"))),
        "last_order_at": (
            last_order_at.isoformat() if last_order_at else None
        ),
        "open_shifts_count": open_shifts,
        "app_version": getattr(restaurant, "app_version", "") or "",
    }
