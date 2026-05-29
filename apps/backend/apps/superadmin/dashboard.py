"""Dashboard для главной страницы Django admin (`/admin/`).

Подключается через `UNFOLD["DASHBOARD_CALLBACK"]`. Возвращает KPI-карточки
и краткую сводку по платформе.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from datetime import timezone as tz
from decimal import Decimal

from django.utils import timezone

DUSHANBE = tz(timedelta(hours=5))
ZERO = Decimal("0.00")


def _start_of_today_local() -> datetime:
    return datetime.combine(date.today(), time.min, tzinfo=DUSHANBE)


def dashboard_callback(request, context):
    """Заполняет context для шаблона admin/index.html.

    Возвращает 4 KPI-секции:
    - Платформа (рестораны / пользователи)
    - Лицензии (статусы + истекают скоро)
    - Сегодня (заказы / выручка)
    - Heartbeat (живые / idle / offline)
    """
    from apps.licensing.models import License
    from apps.orders.models import Order, OrderStatus
    from apps.users.models import Restaurant, User

    now = timezone.now()
    today_start = _start_of_today_local()

    # --- Restaurants ---
    total_restaurants = Restaurant.objects.count()
    live_threshold = now - timedelta(hours=1)
    idle_threshold = now - timedelta(hours=24)

    live_now = Restaurant.objects.filter(
        last_heartbeat_at__gte=live_threshold,
    ).count()
    idle = Restaurant.objects.filter(
        last_heartbeat_at__gte=idle_threshold,
        last_heartbeat_at__lt=live_threshold,
    ).count()
    offline = total_restaurants - live_now - idle

    # --- Users ---
    total_users = User.objects.filter(is_active=True).count()
    by_role = {}
    for u in User.objects.filter(is_active=True).values_list("role", flat=True):
        by_role[u] = by_role.get(u, 0) + 1

    # --- Licenses ---
    active = grace = expired = blocked = 0
    expiring_soon = 0
    for lic in License.objects.all().only("expires_at", "is_blocked"):
        grace_end = lic.expires_at + timedelta(days=License.GRACE_DAYS)
        if lic.is_blocked:
            blocked += 1
        elif now > grace_end:
            expired += 1
        elif now > lic.expires_at:
            grace += 1
        else:
            active += 1
            if lic.expires_at <= now + timedelta(days=7):
                expiring_soon += 1

    # --- Today (orders/revenue) ---
    # На cloud-инстансе локальной таблицы Order нет (она у каждого ресторана
    # своя). Поэтому суммируем из TelemetrySnapshot — агрегаты которые пушат
    # рестораны. На dev-инстансе (где Order локально есть) — берём из Order.
    from django.db.models import Count, Sum

    from apps.telemetry.models import TelemetrySnapshot

    today_local = today_start.date()
    snaps_today = TelemetrySnapshot.objects.filter(business_date=today_local)
    if snaps_today.exists():
        agg = snaps_today.aggregate(
            rev=Sum("daily_revenue"),
            cnt=Sum("daily_orders_count"),
        )
        todays_revenue = agg["rev"] or ZERO
        todays_count = agg["cnt"] or 0
    else:
        # Fallback на локальный Order (dev / single-instance mode)
        todays_orders_qs = Order.objects.filter(
            status=OrderStatus.DONE, closed_at__gte=today_start,
        )
        todays_count = todays_orders_qs.count()
        todays_revenue = ZERO
        for o in todays_orders_qs.only("id"):
            todays_revenue += o.total

    # --- KPI cards (unfold renders them as tiles on the index page) ---
    context["kpi"] = [
        {
            "title": "Рестораны",
            "metric": total_restaurants,
            "footer": (
                f'<strong class="text-green-600">{live_now}</strong> онлайн • '
                f'<strong class="text-yellow-600">{idle}</strong> idle • '
                f'<strong class="text-red-600">{offline}</strong> offline'
            ),
        },
        {
            "title": "Пользователи (активные)",
            "metric": total_users,
            "footer": " • ".join(
                f"{role}: <strong>{cnt}</strong>"
                for role, cnt in sorted(by_role.items())
            ) or "нет",
        },
        {
            "title": "Активные лицензии",
            "metric": active,
            "footer": (
                f'⚠ <strong class="text-yellow-600">{expiring_soon}</strong> '
                f'истекают за неделю • '
                f'<strong class="text-orange-600">{grace}</strong> grace • '
                f'<strong class="text-red-600">{expired}</strong> истекли • '
                f'<strong class="text-red-600">{blocked}</strong> заблок.'
            ),
        },
        {
            "title": "Сегодня",
            "metric": f"{todays_revenue:.2f}",
            "footer": (
                f'<strong>{todays_count}</strong> заказов · '
                f'средний чек: '
                f'<strong>{(todays_revenue / todays_count) if todays_count else 0:.2f}</strong>'
            ),
        },
    ]

    # --- Краткие списки последних событий ---
    recent_restaurants = list(
        Restaurant.objects.order_by("-created_at").only(
            "id", "name", "created_at",
        )[:5]
    )
    expiring_soon_list = []
    for lic in License.objects.filter(
        is_blocked=False,
        expires_at__gte=now,
        expires_at__lte=now + timedelta(days=14),
    ).select_related("restaurant").order_by("expires_at")[:8]:
        days = max(0, int((lic.expires_at - now).total_seconds() // 86400))
        expiring_soon_list.append({
            "id": lic.restaurant_id,
            "name": lic.restaurant.name,
            "plan": lic.plan,
            "expires_at": lic.expires_at,
            "days_left": days,
        })

    context["recent_restaurants"] = recent_restaurants
    context["expiring_soon_licenses"] = expiring_soon_list
    return context
