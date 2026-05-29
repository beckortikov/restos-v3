"""Резервации: create / confirm / seat / cancel / no_show + API."""
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def _future(minutes: int = 60):
    return timezone.now() + timedelta(minutes=minutes)


# -------- Service --------


def test_create_reservation_basic(restaurant, cashier, table):
    from apps.reservations.services import create_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="Иван Иванов",
        customer_phone="+7900",
        party_size=4,
        scheduled_at=_future(60),
        duration_min=120,
        notes="День рождения",
        user=cashier,
    )
    assert r.status == "pending"
    assert r.party_size == 4
    assert r.duration_min == 120
    assert r.notes == "День рождения"


def test_create_rejects_past_time(restaurant, cashier, table):
    from apps.reservations.services import create_reservation
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        create_reservation(
            restaurant=restaurant, table=table,
            customer_name="Х",
            scheduled_at=timezone.now() - timedelta(hours=2),
            user=cashier,
        )
    assert exc.value.code == "RESERVATION_IN_PAST"


def test_create_rejects_overlap(restaurant, cashier, table):
    from apps.reservations.services import create_reservation
    from common.exceptions import BusinessError

    create_reservation(
        restaurant=restaurant, table=table,
        customer_name="Иван", scheduled_at=_future(60),
        duration_min=120, user=cashier,
    )
    # 90 минут спустя — попадает в окно [60, 180]
    with pytest.raises(BusinessError) as exc:
        create_reservation(
            restaurant=restaurant, table=table,
            customer_name="Пётр", scheduled_at=_future(90),
            user=cashier,
        )
    assert exc.value.code == "RESERVATION_CONFLICT"


def test_create_allows_after_window(restaurant, cashier, table):
    from apps.reservations.services import create_reservation

    r1 = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="A", scheduled_at=_future(60),
        duration_min=60, user=cashier,
    )
    # 130 минут — после окна [60, 120]
    r2 = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="B", scheduled_at=_future(130),
        duration_min=60, user=cashier,
    )
    assert r1.id != r2.id


def test_create_rejects_table_from_other_restaurant(restaurant, cashier):
    """Стол из чужого ресторана — TABLE_NOT_FOUND."""
    from apps.reservations.services import create_reservation
    from apps.tables.models import Table, Zone
    from apps.users.models import Restaurant
    from common.exceptions import BusinessError

    other = Restaurant.objects.create(name="Чужой", currency="TJS")
    z = Zone.objects.create(restaurant=other, name="Z")
    other_table = Table.objects.create(
        restaurant=other, zone=z, number=1, name="X", capacity=2,
    )
    with pytest.raises(BusinessError) as exc:
        create_reservation(
            restaurant=restaurant, table=other_table,
            customer_name="X", scheduled_at=_future(60),
            user=cashier,
        )
    assert exc.value.code == "TABLE_NOT_FOUND"


def test_confirm_pending_reservation(restaurant, cashier, table):
    from apps.reservations.services import confirm_reservation, create_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    r2 = confirm_reservation(
        reservation_id=r.id, restaurant=restaurant, user=cashier,
    )
    assert r2.status == "confirmed"


def test_cannot_confirm_cancelled(restaurant, cashier, table):
    from apps.reservations.services import (
        cancel_reservation, confirm_reservation, create_reservation,
    )
    from common.exceptions import BusinessError

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    cancel_reservation(
        reservation_id=r.id, restaurant=restaurant, user=cashier,
    )
    with pytest.raises(BusinessError):
        confirm_reservation(
            reservation_id=r.id, restaurant=restaurant, user=cashier,
        )


def test_seat_changes_status_and_sets_seated_at(restaurant, cashier, table):
    from apps.reservations.services import create_reservation, seat_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    r2 = seat_reservation(
        reservation_id=r.id, restaurant=restaurant, user=cashier,
    )
    assert r2.status == "seated"
    assert r2.seated_at is not None


def test_cancel_with_reason(restaurant, cashier, table):
    from apps.reservations.services import cancel_reservation, create_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    r2 = cancel_reservation(
        reservation_id=r.id, restaurant=restaurant, user=cashier,
        reason="Гость отменил",
    )
    assert r2.status == "cancelled"
    assert r2.cancel_reason == "Гость отменил"
    assert r2.cancelled_at is not None


def test_mark_no_show(restaurant, cashier, table):
    from apps.reservations.services import create_reservation, mark_no_show

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    r2 = mark_no_show(
        reservation_id=r.id, restaurant=restaurant, user=cashier,
    )
    assert r2.status == "no_show"


def test_active_reservations_for_table_in_window(restaurant, cashier, table):
    from apps.reservations.services import (
        active_reservations_for_table, create_reservation,
    )

    # В будущем (через 30 мин) — попадёт в lookahead 60 мин
    r1 = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="A", scheduled_at=_future(30),
        duration_min=60, user=cashier,
    )
    # Через 200 минут — НЕ попадёт в lookahead 60
    create_reservation(
        restaurant=restaurant, table=table,
        customer_name="B", scheduled_at=_future(200),
        duration_min=60, user=cashier,
    )
    qs = list(active_reservations_for_table(table, lookahead_min=60))
    assert len(qs) == 1
    assert qs[0].id == r1.id


def test_audit_log_for_create(restaurant, cashier, table):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.reservations.services import create_reservation

    create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    e = AuditEntry.objects.filter(
        action=AuditAction.RESERVATION_CREATED
    ).first()
    assert e is not None


# -------- API --------


def test_create_endpoint(api_client, restaurant, cashier, table):
    from apps.reservations.models import Reservation

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/reservations/",
        {
            "table": table.id,
            "customer_name": "Иван",
            "customer_phone": "+7900",
            "party_size": 4,
            "scheduled_at": _future(60).isoformat(),
            "duration_min": 90,
            "notes": "Окно у входа",
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()["data"]
    assert body["status"] == "pending"
    assert body["customer_name"] == "Иван"
    assert Reservation.objects.count() == 1


def test_list_endpoint_filter_active(api_client, restaurant, cashier, table):
    from apps.reservations.services import (
        cancel_reservation, create_reservation,
    )

    r1 = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="A", scheduled_at=_future(30), user=cashier,
    )
    r2 = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="B", scheduled_at=_future(180), user=cashier,
    )
    cancel_reservation(
        reservation_id=r1.id, restaurant=restaurant, user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/reservations/?active=true",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()
    ids = {r["id"] for r in body["data"]}
    assert r2.id in ids
    assert r1.id not in ids


def test_confirm_endpoint(api_client, restaurant, cashier, table):
    from apps.reservations.services import create_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/reservations/{r.id}/confirm/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "confirmed"


def test_cancel_endpoint(api_client, restaurant, cashier, table):
    from apps.reservations.services import create_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/reservations/{r.id}/cancel/",
        {"reason": "Гость не отвечает"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Гость не отвечает"


def test_seat_endpoint(api_client, restaurant, cashier, table):
    from apps.reservations.services import create_reservation

    r = create_reservation(
        restaurant=restaurant, table=table,
        customer_name="X", scheduled_at=_future(60), user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/reservations/{r.id}/seat/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "seated"


def test_table_serializer_includes_next_reservation(
    api_client, restaurant, cashier, table,
):
    """TableSerializer.next_reservation для бейджа на TableCard."""
    from apps.reservations.services import create_reservation

    create_reservation(
        restaurant=restaurant, table=table,
        customer_name="Гость", scheduled_at=_future(15),
        user=cashier, party_size=3,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    by_id = {t["id"]: t for t in data}
    assert by_id[table.id]["next_reservation"] is not None
    assert by_id[table.id]["next_reservation"]["customer_name"] == "Гость"
    assert by_id[table.id]["next_reservation"]["party_size"] == 3


def test_table_serializer_no_next_reservation_when_far_future(
    api_client, restaurant, cashier, table,
):
    """Резервация через >24ч — за пределами окна (24ч) — бейдж не показывается."""
    from apps.reservations.services import create_reservation

    create_reservation(
        restaurant=restaurant, table=table,
        customer_name="Гость",
        scheduled_at=_future(25 * 60),  # 25 часов в будущее
        user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    by_id = {t["id"]: t for t in resp.json()["data"]}
    assert by_id[table.id]["next_reservation"] is None


def test_table_serializer_shows_today_reservation(
    api_client, restaurant, cashier, table,
):
    """Регрессия: бронь забронированная сегодня на сегодняшний вечер
    должна показываться на TableCard как «next_reservation» (24ч окно)."""
    from apps.reservations.services import create_reservation

    create_reservation(
        restaurant=restaurant, table=table,
        customer_name="Иван",
        scheduled_at=_future(8 * 60),  # 8 часов вперёд (типичный «утром на вечер»)
        user=cashier,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    by_id = {t["id"]: t for t in resp.json()["data"]}
    assert by_id[table.id]["next_reservation"] is not None
    assert by_id[table.id]["next_reservation"]["customer_name"] == "Иван"
