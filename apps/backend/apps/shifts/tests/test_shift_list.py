"""GET /shifts/ — список смен с фильтрами и пагинацией."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def _seed_shifts(restaurant, cashier, n: int = 3):
    """Создаёт n closed-смен в разные дни."""
    from apps.shifts.models import CashShift, ShiftStatus

    shifts = []
    now = timezone.now()
    for i in range(n):
        s = CashShift.objects.create(
            restaurant=restaurant, cashier=cashier,
            number=i + 1, opening_balance=Decimal("100"),
            status=ShiftStatus.CLOSED,
            opened_at=now - timedelta(days=i),
            closed_at=now - timedelta(days=i, hours=-8),
        )
        shifts.append(s)
    return shifts


def test_list_returns_paginated(api_client, restaurant, cashier):
    _seed_shifts(restaurant, cashier, n=3)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/shifts/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert body["meta"]["total"] == 3
    assert len(body["data"]) == 3


def test_list_orders_by_opened_at_desc(api_client, restaurant, cashier):
    _seed_shifts(restaurant, cashier, n=3)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/shifts/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    opened = [s["opened_at"] for s in resp.json()["data"]]
    # Самая свежая первой (desc по opened_at)
    assert opened == sorted(opened, reverse=True)


def test_list_filter_by_date_range(api_client, restaurant, cashier):
    _seed_shifts(restaurant, cashier, n=5)
    today = timezone.now().date().isoformat()
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        f"/api/v1/shifts/?from={today}&to={today}",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()
    # Только сегодняшняя (i=0)
    assert body["meta"]["total"] == 1


def test_list_filter_by_status(api_client, restaurant, cashier):
    from apps.shifts.models import CashShift, ShiftStatus

    _seed_shifts(restaurant, cashier, n=2)
    # Открытая
    CashShift.objects.create(
        restaurant=restaurant, cashier=cashier,
        number=99, opening_balance=Decimal("0"),
        status=ShiftStatus.OPEN,
        opened_at=timezone.now(),
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/shifts/?status=open",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["status"] == "open"


def test_list_isolates_restaurants(
    api_client, restaurant, cashier, api_client_factory=None
):
    """Cross-restaurant изоляция: чужие смены не видны."""
    from apps.shifts.models import CashShift, ShiftStatus
    from apps.users.models import Restaurant, User

    other_rest = Restaurant.objects.create(name="Другой", currency="TJS")
    other_cashier = User.objects.create_user(
        username="other-cashier", password="x",
        full_name="Другой Кассир", role="cashier",
        restaurant=other_rest,
    )
    other_cashier.set_pin("9999")
    other_cashier.save(update_fields=["pin_hash"])
    CashShift.objects.create(
        restaurant=other_rest, cashier=other_cashier,
        number=1, opening_balance=Decimal("0"),
        status=ShiftStatus.CLOSED,
        opened_at=timezone.now(), closed_at=timezone.now(),
    )

    _seed_shifts(restaurant, cashier, n=2)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/shifts/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()
    assert body["meta"]["total"] == 2  # не 3
