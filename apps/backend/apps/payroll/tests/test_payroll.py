"""Phase 6 — Payroll & TimeEntry tests."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def waiter_with_rate(restaurant):
    from apps.users.models import User, UserRole

    u = User.objects.create_user(
        username="w1", password="p", role=UserRole.WAITER, restaurant=restaurant,
        full_name="Карим",
    )
    u.hourly_rate = Decimal("30.00")
    u.save(update_fields=["hourly_rate"])
    return u


# ─── TimeEntry ──────────────────────────────────────────────────────────────


def test_clock_in_creates_open_entry(restaurant, waiter_with_rate):
    from apps.payroll.models import TimeEntryStatus
    from apps.payroll.services import clock_in

    e = clock_in(user=waiter_with_rate, restaurant=restaurant)
    assert e.status == TimeEntryStatus.OPEN
    assert e.clock_in is not None
    assert e.clock_out is None
    assert e.hourly_rate_snapshot == Decimal("30.00")


def test_clock_in_rejects_when_already_open(restaurant, waiter_with_rate):
    from apps.payroll.services import clock_in
    from common.exceptions import BusinessError

    clock_in(user=waiter_with_rate, restaurant=restaurant)
    with pytest.raises(BusinessError) as exc:
        clock_in(user=waiter_with_rate, restaurant=restaurant)
    assert exc.value.code == "ALREADY_CLOCKED_IN"


def test_clock_out_closes_entry_and_computes_hours(restaurant, waiter_with_rate):
    from apps.payroll.models import TimeEntry, TimeEntryStatus
    from apps.payroll.services import clock_in, clock_out

    e = clock_in(user=waiter_with_rate, restaurant=restaurant)
    # Виртуально сдвигаем clock_in на 5 часов назад
    e.clock_in = timezone.now() - timedelta(hours=5)
    e.save(update_fields=["clock_in"])

    closed = clock_out(user=waiter_with_rate, restaurant=restaurant)
    assert closed.status == TimeEntryStatus.CLOSED
    assert closed.clock_out is not None
    # ~5 часов
    assert Decimal("4.99") <= closed.hours_worked <= Decimal("5.01")


def test_clock_out_without_open_entry_fails(restaurant, waiter_with_rate):
    from apps.payroll.services import clock_out
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        clock_out(user=waiter_with_rate, restaurant=restaurant)
    assert exc.value.code == "NOT_CLOCKED_IN"


def test_auto_close_stale_entries(restaurant, waiter_with_rate):
    from apps.payroll.models import TimeEntry, TimeEntryStatus
    from apps.payroll.services import auto_close_stale_entries, clock_in

    e = clock_in(user=waiter_with_rate, restaurant=restaurant)
    e.clock_in = timezone.now() - timedelta(hours=20)
    e.save(update_fields=["clock_in"])

    closed_count = auto_close_stale_entries(restaurant=restaurant, max_hours=16)
    assert closed_count == 1
    e.refresh_from_db()
    assert e.status == TimeEntryStatus.AUTO_CLOSED
    assert e.clock_out is not None


# ─── PayrollPeriod ──────────────────────────────────────────────────────────


def test_calculate_period_sums_hours(restaurant, waiter_with_rate):
    from apps.payroll.models import TimeEntry, TimeEntryStatus
    from apps.payroll.services import calculate_period

    today = date.today()
    # 2 закрытые смены по 4 часа
    for _ in range(2):
        TimeEntry.objects.create(
            restaurant=restaurant, user=waiter_with_rate,
            clock_in=timezone.now() - timedelta(hours=10),
            clock_out=timezone.now() - timedelta(hours=6),
            status=TimeEntryStatus.CLOSED,
            hourly_rate_snapshot=Decimal("30.00"),
        )

    period = calculate_period(
        user=waiter_with_rate, restaurant=restaurant,
        period_start=today - timedelta(days=1),
        period_end=today,
    )
    assert period.hours_worked == Decimal("8.00")
    assert period.hourly_rate == Decimal("30.00")
    assert period.base_salary == Decimal("240.00")
    assert period.total == Decimal("240.00")


def test_calculate_period_applies_bonuses_and_deductions(restaurant, waiter_with_rate):
    from apps.payroll.services import calculate_period

    period = calculate_period(
        user=waiter_with_rate, restaurant=restaurant,
        period_start=date.today(), period_end=date.today(),
        bonuses=Decimal("100"), deductions=Decimal("20"),
    )
    # 0 часов × 30 + 100 - 20 = 80
    assert period.total == Decimal("80.00")


def test_finalize_then_pay(restaurant, waiter_with_rate):
    from apps.payroll.models import PayrollPeriodStatus
    from apps.payroll.services import calculate_period, finalize_period, pay_period

    p = calculate_period(
        user=waiter_with_rate, restaurant=restaurant,
        period_start=date.today(), period_end=date.today(),
    )
    assert p.status == PayrollPeriodStatus.DRAFT
    finalize_period(period=p)
    assert p.status == PayrollPeriodStatus.FINALIZED
    pay_period(period=p, paid_operation_id=42)
    assert p.status == PayrollPeriodStatus.PAID
    assert p.paid_at is not None
    assert p.paid_operation_id == 42


def test_finalize_rejects_non_draft(restaurant, waiter_with_rate):
    from apps.payroll.services import calculate_period, finalize_period
    from common.exceptions import BusinessError

    p = calculate_period(
        user=waiter_with_rate, restaurant=restaurant,
        period_start=date.today(), period_end=date.today(),
    )
    finalize_period(period=p)
    with pytest.raises(BusinessError) as exc:
        finalize_period(period=p)
    assert exc.value.code == "INVALID_STATE"


# ─── API ────────────────────────────────────────────────────────────────────


def test_clock_in_api(api_client, cashier):
    api_client.force_authenticate(user=cashier)
    resp = api_client.post("/api/v1/payroll/time/clock_in/", {}, format="json")
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["status"] == "open"
    assert data["clock_out"] is None


def test_clock_out_api(api_client, cashier):
    api_client.force_authenticate(user=cashier)
    api_client.post("/api/v1/payroll/time/clock_in/", {}, format="json")
    resp = api_client.post("/api/v1/payroll/time/clock_out/", {}, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["status"] == "closed"


def test_current_returns_open_entry(api_client, cashier):
    api_client.force_authenticate(user=cashier)
    # Без открытой
    resp = api_client.get("/api/v1/payroll/time/current/")
    assert resp.json()["data"] is None
    # С открытой
    api_client.post("/api/v1/payroll/time/clock_in/", {}, format="json")
    resp = api_client.get("/api/v1/payroll/time/current/")
    assert resp.json()["data"] is not None


def test_calculate_period_api(api_client, cashier, waiter_with_rate):
    api_client.force_authenticate(user=cashier)
    today = date.today().isoformat()
    resp = api_client.post(
        "/api/v1/payroll/periods/calculate/",
        {
            "user_id": waiter_with_rate.id,
            "from": today, "to": today,
            "bonuses": "50",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert Decimal(data["bonuses"]) == Decimal("50")
    assert data["status"] == "draft"


def test_finalize_pay_api(api_client, cashier, waiter_with_rate):
    api_client.force_authenticate(user=cashier)
    today = date.today().isoformat()
    period = api_client.post(
        "/api/v1/payroll/periods/calculate/",
        {"user_id": waiter_with_rate.id, "from": today, "to": today},
        format="json",
    ).json()["data"]

    pid = period["id"]
    resp = api_client.post(f"/api/v1/payroll/periods/{pid}/finalize/", {}, format="json")
    assert resp.json()["data"]["status"] == "finalized"

    resp = api_client.post(
        f"/api/v1/payroll/periods/{pid}/pay/",
        {"paid_operation_id": 100}, format="json",
    )
    assert resp.json()["data"]["status"] == "paid"
    assert resp.json()["data"]["paid_operation_id"] == 100


def test_cross_restaurant_isolation(api_client, cashier, restaurant):
    """Зарплата другого ресторана не видна."""
    from apps.payroll.models import PayrollPeriodStatus
    from apps.payroll.services import calculate_period
    from apps.users.models import Restaurant, User, UserRole

    other_resto = Restaurant.objects.create(name="Other", currency="TJS")
    other_user = User.objects.create_user(
        username="x", password="p", role=UserRole.WAITER, restaurant=other_resto,
        full_name="Чужой",
    )
    calculate_period(
        user=other_user, restaurant=other_resto,
        period_start=date.today(), period_end=date.today(),
    )

    api_client.force_authenticate(user=cashier)
    resp = api_client.get("/api/v1/payroll/periods/")
    body = resp.json()
    items = body if isinstance(body, list) else body.get("data") or body.get("results") or []
    # Cashier из restaurant НЕ должен видеть периоды other_resto
    for it in items:
        # У cashier периодов нет — список пуст
        assert it.get("user") != other_user.id
