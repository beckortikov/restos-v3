"""Phase 7 — аналитика: snapshots, peak-hours, food-cost, waiters."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Кухня")


@pytest.fixture
def cold_category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Холодные")


@pytest.fixture
def items(restaurant, category, cold_category):
    from apps.menu.models import MenuItem

    return {
        "plov": MenuItem.objects.create(
            restaurant=restaurant, category=category, name="Плов",
            price=Decimal("45.00"), cogs=Decimal("15.00"),
        ),
        "tea": MenuItem.objects.create(
            restaurant=restaurant, category=cold_category, name="Чай",
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


def _close(restaurant, waiter, cashier, mi, qty=1):
    from apps.orders.services import close_order, create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": mi.id, "qty": qty}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    return o


# ─── ABC snapshot persistence ───────────────────────────────────────────────


def test_save_abc_snapshot_creates_records(restaurant, waiter, cashier, items, printer):
    from apps.analytics.models import AbcSnapshot, AbcSnapshotLine
    from apps.analytics.services import compute_abc_report, save_abc_snapshot

    for _ in range(5):
        _close(restaurant, waiter, cashier, items["plov"])
    for _ in range(2):
        _close(restaurant, waiter, cashier, items["tea"])

    today = date.today()
    report = compute_abc_report(
        restaurant=restaurant,
        period_from=today - timedelta(days=1), period_to=today,
    )
    snap = save_abc_snapshot(
        restaurant=restaurant, report=report, kind="menu", created_by=cashier,
    )
    assert AbcSnapshot.objects.filter(restaurant=restaurant).count() == 1
    assert snap.lines.count() == 2  # plov + tea
    lines = list(snap.lines.order_by("rank"))
    assert lines[0].rank == 1
    assert lines[0].name_snapshot == "Плов"  # топ по revenue
    assert lines[0].abc_class == "A"


def test_abc_snapshots_api_create_and_list(
    api_client, cashier, restaurant, waiter, items, printer,
):
    for _ in range(3):
        _close(restaurant, waiter, cashier, items["plov"])

    api_client.force_authenticate(user=cashier)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    resp = api_client.post(
        "/api/v1/analytics/abc-snapshots/",
        {"kind": "menu", "from": yesterday, "to": today}, format="json",
    )
    assert resp.status_code == 201, resp.content
    sid = resp.json()["data"]["id"]

    resp_list = api_client.get("/api/v1/analytics/abc-snapshots/")
    assert resp_list.status_code == 200
    assert any(s["id"] == sid for s in resp_list.json()["data"])

    resp_detail = api_client.get(f"/api/v1/analytics/abc-snapshots/{sid}/")
    assert resp_detail.status_code == 200
    detail = resp_detail.json()["data"]
    assert detail["kind"] == "menu"
    assert len(detail["rows"]) >= 1


# ─── Peak hours ─────────────────────────────────────────────────────────────


def test_peak_hours_buckets_by_dow_hour(
    api_client, cashier, restaurant, waiter, items, printer,
):
    _close(restaurant, waiter, cashier, items["plov"])
    _close(restaurant, waiter, cashier, items["tea"])

    api_client.force_authenticate(user=cashier)
    today = date.today().isoformat()
    resp = api_client.get(f"/api/v1/analytics/peak-hours/?from={today}&to={today}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Все заказы попадают в одну (dow, hour) ячейку, у которой count == 2
    assert sum(b["count"] for b in data) == 2
    assert all(set(b.keys()) >= {"dow", "hour", "count", "revenue"} for b in data)


# ─── Food cost ──────────────────────────────────────────────────────────────


def test_food_cost_groups_by_category(
    api_client, cashier, restaurant, waiter, items, printer,
):
    for _ in range(2):
        _close(restaurant, waiter, cashier, items["plov"])  # cogs=15, price=45 → fc=33.33%
    _close(restaurant, waiter, cashier, items["tea"])  # cogs=1, price=8 → fc=12.5%

    api_client.force_authenticate(user=cashier)
    today = date.today().isoformat()
    resp = api_client.get(f"/api/v1/analytics/food-cost/?from={today}&to={today}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    cats = {c["name"]: c for c in body["categories"]}
    assert "Кухня" in cats and "Холодные" in cats
    # Плов: 2 × 15 / (2 × 45) = 33.33%
    assert Decimal(cats["Кухня"]["food_cost_pct"]) == Decimal("33.33")
    assert Decimal(cats["Холодные"]["food_cost_pct"]) == Decimal("12.50")
    # Общий FC > 0
    assert Decimal(body["totals"]["food_cost_pct"]) > 0


# ─── Waiter analytics ───────────────────────────────────────────────────────


def test_waiter_analytics_returns_summary(
    api_client, cashier, restaurant, waiter, items, printer,
):
    for _ in range(3):
        _close(restaurant, waiter, cashier, items["plov"])

    api_client.force_authenticate(user=cashier)
    today = date.today().isoformat()
    resp = api_client.get(f"/api/v1/analytics/waiters/?from={today}&to={today}")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["user_id"] == waiter.id
    assert rows[0]["orders_count"] == 3
    assert Decimal(rows[0]["revenue"]) > 0
    assert Decimal(rows[0]["average_check"]) > 0


# ─── Cross-restaurant isolation ─────────────────────────────────────────────


def test_snapshot_isolated_per_restaurant(
    restaurant, waiter, cashier, items, printer,
):
    from apps.analytics.models import AbcSnapshot
    from apps.analytics.services import compute_abc_report, save_abc_snapshot
    from apps.users.models import Restaurant

    _close(restaurant, waiter, cashier, items["plov"])
    today = date.today()
    report = compute_abc_report(
        restaurant=restaurant,
        period_from=today - timedelta(days=1), period_to=today,
    )
    save_abc_snapshot(restaurant=restaurant, report=report, kind="menu")

    other = Restaurant.objects.create(name="Other", currency="TJS")
    assert AbcSnapshot.objects.filter(restaurant=other).count() == 0
    assert AbcSnapshot.objects.filter(restaurant=restaurant).count() == 1
