"""ABC-анализ меню по выручке и маржинальности.

Алгоритм:
1. Берём все DONE-заказы за период.
2. Группируем по menu_item: суммируем qty, выручку (price_at_order × qty),
   модификаторы (sum of price_delta), себестоимость (cogs × qty).
3. Маржа = выручка − себестоимость.
4. Сортируем по выручке убыв., присваиваем класс A/B/C:
   - A: топ-80% накопленной выручки
   - B: следующие 15%
   - C: оставшиеся 5%

Отменённые позиции (`cancelled_at is not None`) — НЕ учитываются.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as tz
from decimal import Decimal
from typing import Iterable

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from apps.orders.models import Order, OrderItem, OrderStatus

DUSHANBE = tz(timedelta(hours=5))
ZERO = Decimal("0.00")
Q2 = Decimal("0.01")


@dataclass
class AbcRow:
    menu_item_id: int
    name: str
    category_name: str
    sold_qty: int
    revenue: Decimal
    cogs_total: Decimal
    margin: Decimal
    margin_pct: Decimal  # 0..100; revenue==0 → 0
    revenue_share_pct: Decimal  # доля от общей выручки, 0..100
    cumulative_share_pct: Decimal  # накопительная, 0..100
    abc_class: str  # "A" / "B" / "C"


@dataclass
class AbcReport:
    period_from: date
    period_to: date
    total_revenue: Decimal
    total_cogs: Decimal
    total_margin: Decimal
    rows: list[AbcRow]


def _start_of_day(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=DUSHANBE)


def _end_of_day(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=DUSHANBE)


def _modifier_delta_per_unit(order_item: OrderItem) -> Decimal:
    """Сумма price_delta_at_order всех модификаторов позиции (за единицу)."""
    return sum(
        (Decimal(str(m.price_delta_at_order)) for m in order_item.modifiers.all()),
        ZERO,
    )


def compute_abc_report(
    *, restaurant, period_from: date, period_to: date,
) -> AbcReport:
    """Возвращает ABC-отчёт по выручке/марже за период (inclusive обе даты).

    Period — по `Order.closed_at` (когда оплачен). Незакрытые заказы не
    участвуют — это незавершённая выручка.
    """
    start = _start_of_day(period_from)
    end = _end_of_day(period_to)

    # Выбираем все DONE-позиции за период с непустыми menu_item
    items = (
        OrderItem.objects
        .filter(
            order__restaurant=restaurant,
            order__status=OrderStatus.DONE,
            order__closed_at__gte=start,
            order__closed_at__lte=end,
            cancelled_at__isnull=True,
            menu_item__isnull=False,
        )
        .select_related("menu_item", "menu_item__category")
        .prefetch_related("modifiers")
    )

    # Группируем вручную, чтобы учесть модификаторы (price_delta) и cogs.
    agg: dict[int, dict] = {}
    for it in items:
        mi = it.menu_item
        if mi is None:
            continue
        delta = _modifier_delta_per_unit(it)
        unit_revenue = Decimal(str(it.price_at_order)) + delta
        line_revenue = unit_revenue * it.qty
        line_cogs = Decimal(str(mi.cogs or 0)) * it.qty
        row = agg.setdefault(mi.id, {
            "menu_item": mi,
            "qty": 0,
            "revenue": ZERO,
            "cogs_total": ZERO,
        })
        row["qty"] += it.qty
        row["revenue"] += line_revenue
        row["cogs_total"] += line_cogs

    # Сортируем по выручке убыв.
    sorted_rows = sorted(
        agg.values(), key=lambda r: r["revenue"], reverse=True,
    )

    total_revenue = sum((r["revenue"] for r in sorted_rows), ZERO)
    total_cogs = sum((r["cogs_total"] for r in sorted_rows), ZERO)
    total_margin = total_revenue - total_cogs

    rows: list[AbcRow] = []
    prev_cum = ZERO  # накопительная доля ДО текущей строки
    cumulative = ZERO
    for r in sorted_rows:
        mi = r["menu_item"]
        revenue = r["revenue"]
        cogs_total = r["cogs_total"]
        margin = revenue - cogs_total
        margin_pct = (
            (margin / revenue * Decimal("100")).quantize(Q2)
            if revenue > 0 else ZERO
        )
        share = (
            (revenue / total_revenue * Decimal("100")).quantize(Q2)
            if total_revenue > 0 else ZERO
        )
        cumulative += share
        cum = cumulative.quantize(Q2)

        # Класс по накопительной доле ДО включения текущей строки —
        # классический ABC (первая строка всегда A независимо от её доли,
        # т.к. до неё накоплено 0% < 80%).
        if prev_cum < Decimal("80"):
            abc_class = "A"
        elif prev_cum < Decimal("95"):
            abc_class = "B"
        else:
            abc_class = "C"
        prev_cum = cum

        rows.append(AbcRow(
            menu_item_id=mi.id,
            name=mi.name,
            category_name=mi.category.name if mi.category else "",
            sold_qty=r["qty"],
            revenue=revenue.quantize(Q2),
            cogs_total=cogs_total.quantize(Q2),
            margin=margin.quantize(Q2),
            margin_pct=margin_pct,
            revenue_share_pct=share,
            cumulative_share_pct=cum,
            abc_class=abc_class,
        ))

    return AbcReport(
        period_from=period_from,
        period_to=period_to,
        total_revenue=total_revenue.quantize(Q2),
        total_cogs=total_cogs.quantize(Q2),
        total_margin=total_margin.quantize(Q2),
        rows=rows,
    )


def save_abc_snapshot(*, restaurant, report: AbcReport, kind: str, created_by=None):
    """Сохранить отчёт как `AbcSnapshot` + `AbcSnapshotLine` (Phase 7)."""
    from django.db import transaction

    from .models import AbcSnapshot, AbcSnapshotLine

    with transaction.atomic():
        snap = AbcSnapshot.objects.create(
            restaurant=restaurant,
            kind=kind,
            period_from=report.period_from,
            period_to=report.period_to,
            total_revenue=report.total_revenue,
            total_cogs=report.total_cogs,
            total_margin=report.total_margin,
            created_by=created_by,
        )
        bulk = []
        for rank, row in enumerate(report.rows, start=1):
            bulk.append(AbcSnapshotLine(
                snapshot=snap,
                menu_item_id=row.menu_item_id if kind == "menu" else None,
                name_snapshot=row.name,
                qty_sold=Decimal(row.sold_qty),
                revenue=row.revenue,
                cogs=row.cogs_total,
                margin=row.margin,
                revenue_share_pct=row.revenue_share_pct,
                cumulative_share_pct=row.cumulative_share_pct,
                abc_class=row.abc_class,
                rank=rank,
            ))
        AbcSnapshotLine.objects.bulk_create(bulk)
    return snap


def compute_peak_hours(*, restaurant, period_from: date, period_to: date) -> list[dict]:
    """Распределение DONE-заказов по (day_of_week, hour) в часовом поясе Душанбе.

    Возвращает плоский список ячеек: [{dow: 0..6, hour: 0..23, count, revenue}, ...].
    dow=0 — Понедельник (ISO).
    """
    start = _start_of_day(period_from)
    end = _end_of_day(period_to)
    orders = Order.objects.filter(
        restaurant=restaurant,
        status=OrderStatus.DONE,
        closed_at__gte=start, closed_at__lte=end,
    ).prefetch_related("items")

    buckets: dict[tuple[int, int], dict] = {}
    for o in orders:
        if o.closed_at is None:
            continue
        total = o.total  # @property
        local = o.closed_at.astimezone(DUSHANBE)
        # ISO weekday: Monday=1..Sunday=7 → нормализуем к 0..6 (Mon=0)
        dow = local.isoweekday() - 1
        hour = local.hour
        key = (dow, hour)
        bucket = buckets.setdefault(key, {"dow": dow, "hour": hour, "count": 0, "revenue": ZERO})
        bucket["count"] += 1
        bucket["revenue"] += Decimal(str(total or 0))

    return [
        {**b, "revenue": str(b["revenue"].quantize(Q2))}
        for b in sorted(buckets.values(), key=lambda x: (x["dow"], x["hour"]))
    ]


def compute_food_cost(*, restaurant, period_from: date, period_to: date) -> dict:
    """Food-cost % по категориям меню.

    cogs% = total_cogs / total_revenue × 100 за период (DONE заказы).
    Возвращает: {totals: {revenue, cogs, food_cost_pct}, categories: [...]}.
    """
    start = _start_of_day(period_from)
    end = _end_of_day(period_to)
    items = (
        OrderItem.objects
        .filter(
            order__restaurant=restaurant,
            order__status=OrderStatus.DONE,
            order__closed_at__gte=start, order__closed_at__lte=end,
            cancelled_at__isnull=True,
            menu_item__isnull=False,
        )
        .select_related("menu_item", "menu_item__category")
        .prefetch_related("modifiers")
    )

    cat_agg: dict[int, dict] = {}
    total_rev = ZERO
    total_cogs = ZERO
    for it in items:
        mi = it.menu_item
        delta = _modifier_delta_per_unit(it)
        line_rev = (Decimal(str(it.price_at_order)) + delta) * it.qty
        line_cogs = Decimal(str(mi.cogs or 0)) * it.qty
        total_rev += line_rev
        total_cogs += line_cogs
        cat = mi.category
        cat_id = cat.id if cat else 0
        cat_name = cat.name if cat else "Без категории"
        row = cat_agg.setdefault(cat_id, {
            "id": cat_id, "name": cat_name,
            "revenue": ZERO, "cogs": ZERO, "items_count": 0,
        })
        row["revenue"] += line_rev
        row["cogs"] += line_cogs
        row["items_count"] += int(it.qty)

    categories = []
    for r in cat_agg.values():
        rev = r["revenue"]
        cogs = r["cogs"]
        pct = (cogs / rev * 100).quantize(Q2) if rev > 0 else ZERO
        categories.append({
            "id": r["id"], "name": r["name"],
            "revenue": str(rev.quantize(Q2)),
            "cogs": str(cogs.quantize(Q2)),
            "food_cost_pct": str(pct),
            "items_count": r["items_count"],
        })
    categories.sort(key=lambda c: Decimal(c["revenue"]), reverse=True)

    overall_pct = (
        (total_cogs / total_rev * 100).quantize(Q2) if total_rev > 0 else ZERO
    )
    return {
        "totals": {
            "revenue": str(total_rev.quantize(Q2)),
            "cogs": str(total_cogs.quantize(Q2)),
            "food_cost_pct": str(overall_pct),
        },
        "categories": categories,
    }


def compute_waiter_analytics(
    *, restaurant, period_from: date, period_to: date,
) -> list[dict]:
    """Аналитика по официантам: кол-во заказов, средний чек, выручка."""
    start = _start_of_day(period_from)
    end = _end_of_day(period_to)
    orders = (
        Order.objects
        .filter(
            restaurant=restaurant, status=OrderStatus.DONE,
            closed_at__gte=start, closed_at__lte=end,
        )
        .select_related("waiter")
        .prefetch_related("items")
    )

    agg: dict[int, dict] = {}
    for o in orders:
        w = o.waiter
        if w is None:
            continue
        row = agg.setdefault(w.id, {
            "user_id": w.id,
            "name": w.full_name,
            "orders_count": 0,
            "revenue": ZERO,
            "guests_total": 0,
        })
        row["orders_count"] += 1
        row["revenue"] += Decimal(str(o.total or 0))
        row["guests_total"] += int(o.guests_count or 0)

    result = []
    for r in agg.values():
        cnt = r["orders_count"]
        rev = r["revenue"]
        avg = (rev / cnt).quantize(Q2) if cnt > 0 else ZERO
        result.append({
            "user_id": r["user_id"],
            "name": r["name"],
            "orders_count": cnt,
            "revenue": str(rev.quantize(Q2)),
            "average_check": str(avg),
            "guests_total": r["guests_total"],
        })
    result.sort(key=lambda x: Decimal(x["revenue"]), reverse=True)
    return result


def serialize_abc_report(report: AbcReport) -> dict:
    """Подготовить payload для JSON-ответа API."""
    return {
        "period": {
            "from": report.period_from.isoformat(),
            "to": report.period_to.isoformat(),
        },
        "totals": {
            "revenue": str(report.total_revenue),
            "cogs": str(report.total_cogs),
            "margin": str(report.total_margin),
            "margin_pct": str(
                (report.total_margin / report.total_revenue * Decimal("100")).quantize(Q2)
                if report.total_revenue > 0 else ZERO
            ),
            "items_count": len(report.rows),
        },
        "rows": [
            {
                "menu_item_id": r.menu_item_id,
                "name": r.name,
                "category_name": r.category_name,
                "sold_qty": r.sold_qty,
                "revenue": str(r.revenue),
                "cogs_total": str(r.cogs_total),
                "margin": str(r.margin),
                "margin_pct": str(r.margin_pct),
                "revenue_share_pct": str(r.revenue_share_pct),
                "cumulative_share_pct": str(r.cumulative_share_pct),
                "abc_class": r.abc_class,
            }
            for r in report.rows
        ],
    }
