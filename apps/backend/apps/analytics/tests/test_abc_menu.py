"""ABC-аналитика по меню: классификация A/B/C, маржинальность."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Кухня")


@pytest.fixture
def items(restaurant, category):
    from apps.menu.models import MenuItem

    return {
        "plov": MenuItem.objects.create(
            restaurant=restaurant, category=category, name="Плов",
            price=Decimal("45.00"), cogs=Decimal("15.00"),
        ),
        "lagman": MenuItem.objects.create(
            restaurant=restaurant, category=category, name="Лагман",
            price=Decimal("40.00"), cogs=Decimal("18.00"),
        ),
        "tea": MenuItem.objects.create(
            restaurant=restaurant, category=category, name="Чай",
            price=Decimal("8.00"), cogs=Decimal("1.00"),
        ),
    }


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind

    return Printer.objects.create(
        restaurant=restaurant, name="Касса", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )


def _close(restaurant, waiter, cashier, mi, qty):
    """Создать takeaway-заказ с одной позицией и закрыть его."""
    from apps.orders.services import close_order, create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": mi.id, "qty": qty}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    return o


# -------- Service: метрики и классификация --------


def test_abc_report_groups_by_menu_item(
    restaurant, waiter, cashier, items, printer,
):
    from apps.analytics.services import compute_abc_report

    # Продали: Плов ×10, Лагман ×5, Чай ×40 (но дешёвый)
    for _ in range(10):
        _close(restaurant, waiter, cashier, items["plov"], 1)
    for _ in range(5):
        _close(restaurant, waiter, cashier, items["lagman"], 1)
    for _ in range(40):
        _close(restaurant, waiter, cashier, items["tea"], 1)

    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    by_name = {r.name: r for r in rep.rows}
    # Плов: 45 × 10 = 450
    assert by_name["Плов"].revenue == Decimal("450.00")
    assert by_name["Плов"].cogs_total == Decimal("150.00")
    assert by_name["Плов"].margin == Decimal("300.00")
    # Чай: 8 × 40 = 320
    assert by_name["Чай"].revenue == Decimal("320.00")
    # Лагман: 40 × 5 = 200
    assert by_name["Лагман"].revenue == Decimal("200.00")
    # Totals
    assert rep.total_revenue == Decimal("970.00")
    assert rep.total_cogs == Decimal("150.00") + Decimal("90.00") + Decimal("40.00")
    assert rep.total_margin == rep.total_revenue - rep.total_cogs


def test_abc_classifies_by_cumulative_revenue(
    restaurant, waiter, cashier, items, printer,
):
    """Классический Pareto-ABC: класс берётся по prev_cumulative.

    Сценарий: 45/40/8 = total 93.
    Накопительно: 48.39% / 91.40% / 100%.
    Алгоритм смотрит на prev_cum (то, что было ДО строки):
      - Плов:    prev=0     <80  → A (тянет cumulative до 48.39%)
      - Лагман:  prev=48.39 <80  → A (тянет до 91.40%)
      - Чай:     prev=91.40 <95  → B
    Класс C появляется только когда уже накопили ≥95% и есть ещё хвост.
    """
    from apps.analytics.services import compute_abc_report

    _close(restaurant, waiter, cashier, items["plov"], 1)
    _close(restaurant, waiter, cashier, items["lagman"], 1)
    _close(restaurant, waiter, cashier, items["tea"], 1)

    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    by_name = {r.name: r for r in rep.rows}
    assert by_name["Плов"].abc_class == "A"
    assert by_name["Лагман"].abc_class == "A"
    assert by_name["Чай"].abc_class == "B"


def test_abc_class_c_appears_in_long_tail(
    restaurant, waiter, cashier, items, printer,
):
    """C-класс появляется когда есть длинный хвост дешёвых блюд (накопили ≥95%)."""
    from apps.analytics.services import compute_abc_report

    # Большой объём дорогого Плова + Лагман + один Чай (хвост).
    for _ in range(50):
        _close(restaurant, waiter, cashier, items["plov"], 1)  # 50×45 = 2250
    for _ in range(10):
        _close(restaurant, waiter, cashier, items["lagman"], 1)  # 10×40 = 400
    _close(restaurant, waiter, cashier, items["tea"], 1)  # 1×8 = 8
    # total = 2658. Плов: share=84.65%. prev=0<80 → A (cum=84.65).
    # Лагман: prev=84.65>=80 и <95 → B (cum=99.70).
    # Чай: prev=99.70 ≥ 95 → C.

    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    by_name = {r.name: r for r in rep.rows}
    assert by_name["Плов"].abc_class == "A"
    assert by_name["Лагман"].abc_class == "B"
    assert by_name["Чай"].abc_class == "C"


def test_abc_margin_percent(
    restaurant, waiter, cashier, items, printer,
):
    from apps.analytics.services import compute_abc_report

    _close(restaurant, waiter, cashier, items["plov"], 2)
    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    row = next(r for r in rep.rows if r.name == "Плов")
    # revenue=90, cogs=30, margin=60, margin_pct = 60/90*100 = 66.67
    assert row.revenue == Decimal("90.00")
    assert row.margin == Decimal("60.00")
    assert row.margin_pct == Decimal("66.67")


def test_abc_skips_cancelled_items(
    restaurant, waiter, cashier, items, printer,
):
    from apps.analytics.services import compute_abc_report
    from apps.orders.services import (
        cancel_item,
        close_order,
        create_order,
    )

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[
            {"menu_item_id": items["plov"].id, "qty": 1},
            {"menu_item_id": items["tea"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )
    # Отменяем чай
    tea_item = o.items.get(menu_item=items["tea"])
    cancel_item(
        order_id=o.id, item_id=tea_item.id, user=cashier,
        reason="Гость передумал",
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    names = [r.name for r in rep.rows]
    assert "Плов" in names
    assert "Чай" not in names  # отменён


def test_abc_skips_non_closed_orders(
    restaurant, waiter, cashier, items, printer,
):
    """Незакрытый заказ не должен попадать в ABC."""
    from apps.analytics.services import compute_abc_report
    from apps.orders.services import create_order

    create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 5}],
        idempotency_key=uuid4(),
    )
    # close НЕ вызываем
    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    assert rep.rows == []
    assert rep.total_revenue == Decimal("0.00")


def test_abc_counts_modifier_revenue(
    restaurant, waiter, cashier, items, printer,
):
    """Модификатор с price_delta попадает в revenue, но не в cogs."""
    from apps.analytics.services import compute_abc_report
    from apps.menu.models import Modifier, ModifierGroup
    from apps.orders.services import close_order, create_order

    g = ModifierGroup.objects.create(
        restaurant=restaurant, name="Размер",
        min_select=1, max_select=1, is_required=True,
    )
    big = Modifier.objects.create(
        group=g, name="Большая", price_delta=Decimal("10"),
    )
    items["plov"].modifier_groups.add(g)

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": items["plov"].id, "qty": 2,
            "modifier_ids": [big.id],
        }],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant, period_from=today, period_to=today,
    )
    plov = next(r for r in rep.rows if r.name == "Плов")
    # (45 + 10) × 2 = 110
    assert plov.revenue == Decimal("110.00")
    # cogs = 15 × 2 = 30, margin = 80
    assert plov.cogs_total == Decimal("30.00")
    assert plov.margin == Decimal("80.00")


def test_abc_filters_by_period(
    restaurant, waiter, cashier, items, printer,
):
    """Заказы вне периода не учитываются."""
    from apps.analytics.services import compute_abc_report

    o = _close(restaurant, waiter, cashier, items["plov"], 1)
    # Сдвинуть closed_at на 60 дней назад
    from django.utils import timezone
    o.closed_at = timezone.now() - timedelta(days=60)
    o.save(update_fields=["closed_at"])

    today = date.today()
    rep = compute_abc_report(
        restaurant=restaurant,
        period_from=today - timedelta(days=7),
        period_to=today,
    )
    assert rep.rows == []


# -------- Endpoint --------


def test_abc_endpoint(
    api_client, restaurant, cashier, waiter, items, printer,
):
    _close(restaurant, waiter, cashier, items["plov"], 3)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/analytics/abc-menu/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert "period" in data
    assert "totals" in data
    assert "rows" in data
    assert data["totals"]["items_count"] == 1
    assert data["rows"][0]["name"] == "Плов"
    assert data["rows"][0]["abc_class"] == "A"


def test_abc_endpoint_date_range(api_client, restaurant, cashier, items, printer):
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/analytics/abc-menu/?from=2026-01-01&to=2026-01-31",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["period"]["from"] == "2026-01-01"
    assert data["period"]["to"] == "2026-01-31"


def test_abc_endpoint_rejects_inverted_dates(
    api_client, restaurant, cashier
):
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/analytics/abc-menu/?from=2026-02-01&to=2026-01-01",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400


def test_abc_endpoint_rejects_invalid_date_format(
    api_client, restaurant, cashier
):
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/analytics/abc-menu/?from=junk",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400


def test_abc_cross_restaurant_isolation(
    api_client, restaurant, cashier, waiter, items, printer,
):
    """Закрытый заказ другого ресторана не попадает."""
    from apps.menu.models import Category, MenuItem
    from apps.users.models import Restaurant, User, UserRole

    other = Restaurant.objects.create(name="Чужой", currency="TJS")
    o_cat = Category.objects.create(restaurant=other, name="X")
    o_item = MenuItem.objects.create(
        restaurant=other, category=o_cat, name="Чужое блюдо",
        price=Decimal("999"), cogs=Decimal("0"),
    )
    o_waiter = User.objects.create(
        username="other_waiter", restaurant=other,
        role=UserRole.WAITER, is_active=True, full_name="Other",
    )
    o_cashier = User.objects.create(
        username="other_cashier", restaurant=other,
        role=UserRole.CASHIER, is_active=True, full_name="Other C",
    )
    _close(other, o_waiter, o_cashier, o_item, 1)

    # Своих заказов нет — пустой отчёт у текущего ресторана.
    _close(restaurant, waiter, cashier, items["plov"], 1)

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/analytics/abc-menu/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    rows = resp.json()["data"]["rows"]
    names = [r["name"] for r in rows]
    assert "Плов" in names
    assert "Чужое блюдо" not in names
