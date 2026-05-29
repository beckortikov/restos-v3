"""HTTP-обвязка над сервисом ABC-анализа."""
from datetime import date, timedelta

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from common.exceptions import BusinessError
from common.permissions import IsCashier

from .services import (
    compute_abc_report,
    compute_food_cost,
    compute_peak_hours,
    compute_waiter_analytics,
    save_abc_snapshot,
    serialize_abc_report,
)


def _parse_date(value: str | None, *, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise BusinessError(
            "INVALID_DATE",
            f"Ожидается дата в формате YYYY-MM-DD, получено: {value!r}",
            400,
        ) from exc


@api_view(["GET"])
@permission_classes([IsCashier])
def abc_menu_report(request):
    """GET /api/v1/analytics/abc-menu/?from=YYYY-MM-DD&to=YYYY-MM-DD

    Дефолт: последние 30 дней.
    """
    today = date.today()
    period_from = _parse_date(
        request.query_params.get("from"), fallback=today - timedelta(days=30),
    )
    period_to = _parse_date(
        request.query_params.get("to"), fallback=today,
    )
    if period_from > period_to:
        raise BusinessError(
            "INVALID_DATE", "Дата «от» больше даты «до»", 400,
        )
    if (period_to - period_from).days > 366:
        raise BusinessError(
            "INVALID_DATE",
            "Период не может превышать 366 дней",
            400,
        )

    report = compute_abc_report(
        restaurant=request.user.restaurant,
        period_from=period_from,
        period_to=period_to,
    )
    return Response({"data": serialize_abc_report(report)})


def _period_from_query(request):
    today = date.today()
    period_from = _parse_date(
        request.query_params.get("from"), fallback=today - timedelta(days=30),
    )
    period_to = _parse_date(
        request.query_params.get("to"), fallback=today,
    )
    if period_from > period_to:
        raise BusinessError("INVALID_DATE", "Дата «от» больше даты «до»", 400)
    if (period_to - period_from).days > 366:
        raise BusinessError("INVALID_DATE", "Период > 366 дней", 400)
    return period_from, period_to


@api_view(["GET"])
@permission_classes([IsCashier])
def peak_hours_report(request):
    """GET /api/v1/analytics/peak-hours/?from=…&to=…"""
    period_from, period_to = _period_from_query(request)
    data = compute_peak_hours(
        restaurant=request.user.restaurant,
        period_from=period_from, period_to=period_to,
    )
    return Response({
        "data": data,
        "meta": {"from": period_from.isoformat(), "to": period_to.isoformat()},
    })


@api_view(["GET"])
@permission_classes([IsCashier])
def food_cost_report(request):
    """GET /api/v1/analytics/food-cost/?from=…&to=…"""
    period_from, period_to = _period_from_query(request)
    data = compute_food_cost(
        restaurant=request.user.restaurant,
        period_from=period_from, period_to=period_to,
    )
    return Response({
        "data": data,
        "meta": {"from": period_from.isoformat(), "to": period_to.isoformat()},
    })


@api_view(["GET"])
@permission_classes([IsCashier])
def waiter_analytics_report(request):
    """GET /api/v1/analytics/waiters/?from=…&to=…"""
    period_from, period_to = _period_from_query(request)
    data = compute_waiter_analytics(
        restaurant=request.user.restaurant,
        period_from=period_from, period_to=period_to,
    )
    return Response({
        "data": data,
        "meta": {"from": period_from.isoformat(), "to": period_to.isoformat()},
    })


@api_view(["GET", "POST"])
@permission_classes([IsCashier])
def abc_snapshots(request):
    """GET — список снимков. POST {kind, from, to} — создать новый."""
    from .models import AbcSnapshot

    if request.method == "GET":
        kind = request.query_params.get("kind") or None
        qs = AbcSnapshot.objects.filter(
            restaurant=request.user.restaurant
        ).order_by("-created_at")
        if kind:
            qs = qs.filter(kind=kind)
        return Response({
            "data": [
                {
                    "id": s.id, "kind": s.kind,
                    "period_from": s.period_from.isoformat(),
                    "period_to": s.period_to.isoformat(),
                    "total_revenue": str(s.total_revenue),
                    "total_cogs": str(s.total_cogs),
                    "total_margin": str(s.total_margin),
                    "created_at": s.created_at.isoformat(),
                    "created_by": s.created_by_id,
                    "lines_count": s.lines.count(),
                }
                for s in qs[:50]
            ]
        })

    kind = (request.data.get("kind") or "menu").strip()
    if kind not in {"menu", "inventory"}:
        raise BusinessError("INVALID_VALUE", "kind должен быть menu/inventory", 400)
    period_from = _parse_date(
        request.data.get("from"), fallback=date.today() - timedelta(days=30),
    )
    period_to = _parse_date(request.data.get("to"), fallback=date.today())
    report = compute_abc_report(
        restaurant=request.user.restaurant,
        period_from=period_from, period_to=period_to,
    )
    snap = save_abc_snapshot(
        restaurant=request.user.restaurant,
        report=report, kind=kind, created_by=request.user,
    )
    return Response({"data": {"id": snap.id, "lines_count": snap.lines.count()}}, status=201)


@api_view(["GET"])
@permission_classes([IsCashier])
def abc_snapshot_detail(request, snapshot_id: int):
    """GET /api/v1/analytics/abc-snapshots/{id}/ — детальный просмотр снимка."""
    from .models import AbcSnapshot

    try:
        snap = AbcSnapshot.objects.get(
            id=snapshot_id, restaurant=request.user.restaurant,
        )
    except AbcSnapshot.DoesNotExist:
        raise BusinessError("NOT_FOUND", "Снимок не найден", 404)
    lines = snap.lines.all().order_by("rank")
    return Response({
        "data": {
            "id": snap.id, "kind": snap.kind,
            "period_from": snap.period_from.isoformat(),
            "period_to": snap.period_to.isoformat(),
            "total_revenue": str(snap.total_revenue),
            "total_cogs": str(snap.total_cogs),
            "total_margin": str(snap.total_margin),
            "rows": [
                {
                    "rank": l.rank, "name": l.name_snapshot,
                    "qty_sold": str(l.qty_sold),
                    "revenue": str(l.revenue), "cogs": str(l.cogs),
                    "margin": str(l.margin),
                    "revenue_share_pct": str(l.revenue_share_pct),
                    "cumulative_share_pct": str(l.cumulative_share_pct),
                    "abc_class": l.abc_class,
                }
                for l in lines
            ],
        }
    })
