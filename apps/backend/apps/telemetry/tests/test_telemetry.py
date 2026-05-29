"""Telemetry: сбор → буфер → push → cloud-приём."""
from datetime import date, timedelta
from decimal import Decimal
from importlib import reload
from uuid import uuid4

import pytest
import responses
from django.test import override_settings
from django.urls import clear_url_caches
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _refresh_urlconf():
    from config import urls as cfg_urls

    clear_url_caches()
    reload(cfg_urls)


# -------- collect_telemetry --------


def test_collect_telemetry_no_orders(restaurant):
    from apps.telemetry.collector import collect_telemetry

    payload = collect_telemetry(restaurant=restaurant)
    assert payload["daily_revenue"] == "0.00"
    assert payload["daily_orders_count"] == 0
    assert payload["mtd_revenue"] == "0.00"
    assert payload["last_order_at"] is None
    assert payload["open_shifts_count"] == 0
    assert "business_date" in payload
    assert "captured_at" in payload


def test_collect_telemetry_with_orders(
    restaurant, waiter, cashier,
):
    from apps.menu.models import Category, MenuItem
    from apps.orders.services import close_order, create_order
    from apps.telemetry.collector import collect_telemetry

    cat = Category.objects.create(restaurant=restaurant, name="X")
    item = MenuItem.objects.create(
        restaurant=restaurant, category=cat, name="Плов",
        price=Decimal("45"),
    )
    # Закрытый заказ сегодня
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": item.id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    payload = collect_telemetry(restaurant=restaurant)
    assert Decimal(payload["daily_revenue"]) == Decimal("90.00")  # 45 × 2
    assert payload["daily_orders_count"] == 1
    assert Decimal(payload["mtd_revenue"]) >= Decimal("90.00")
    assert payload["last_order_at"] is not None


def test_collect_telemetry_open_shift(restaurant, cashier):
    from apps.shifts.services import open_shift
    from apps.telemetry.collector import collect_telemetry

    open_shift(
        restaurant=restaurant, cashier=cashier,
        opening_balance=Decimal("100"),
    )
    payload = collect_telemetry(restaurant=restaurant)
    assert payload["open_shifts_count"] == 1


# -------- queue + push --------


def test_queue_telemetry_upserts_by_date(restaurant):
    from apps.telemetry.collector import collect_telemetry
    from apps.telemetry.models import PendingTelemetrySnapshot
    from apps.telemetry.sender import queue_telemetry

    p1 = collect_telemetry(restaurant=restaurant)
    queue_telemetry(restaurant=restaurant, payload=p1)
    queue_telemetry(restaurant=restaurant, payload=p1)
    # Один день — одна запись
    assert PendingTelemetrySnapshot.objects.count() == 1


@responses.activate
def test_push_pending_to_cloud_success(settings, restaurant):
    from apps.telemetry.collector import collect_telemetry
    from apps.telemetry.models import PendingTelemetrySnapshot
    from apps.telemetry.sender import push_pending_to_cloud, queue_telemetry

    settings.CLOUD_BASE_URL = "https://cloud.example.com"
    settings.RESTAURANT_API_KEY = "test-key"

    payload = collect_telemetry(restaurant=restaurant)
    queue_telemetry(restaurant=restaurant, payload=payload)
    assert PendingTelemetrySnapshot.objects.count() == 1

    responses.add(
        responses.POST,
        "https://cloud.example.com/api/v1/telemetry/push/",
        json={"data": {"ok": True, "snapshot_id": 1}},
        status=200,
    )
    sent, failed = push_pending_to_cloud()
    assert sent == 1
    assert failed == 0
    # При успехе snapshot удалён из буфера
    assert PendingTelemetrySnapshot.objects.count() == 0


@responses.activate
def test_push_keeps_pending_on_failure(settings, restaurant):
    from apps.telemetry.collector import collect_telemetry
    from apps.telemetry.models import PendingTelemetrySnapshot
    from apps.telemetry.sender import push_pending_to_cloud, queue_telemetry

    settings.CLOUD_BASE_URL = "https://cloud.example.com"
    settings.RESTAURANT_API_KEY = "test-key"
    queue_telemetry(restaurant=restaurant, payload=collect_telemetry(restaurant=restaurant))

    responses.add(
        responses.POST,
        "https://cloud.example.com/api/v1/telemetry/push/",
        json={"error": {"code": "AUTH_INVALID", "message": "Неизвестный api_key"}},
        status=401,
    )
    sent, failed = push_pending_to_cloud()
    assert sent == 0
    assert failed == 1
    # Запись осталась в буфере
    pending = PendingTelemetrySnapshot.objects.get()
    assert pending.attempts == 1
    assert "AUTH_INVALID" in pending.last_error


# -------- Cloud endpoint --------


def test_cloud_telemetry_push_success(api_client, settings, restaurant):
    settings.SUPERADMIN_ENABLED = True
    restaurant.api_key = "test-key-abc"
    restaurant.save(update_fields=["api_key"])

    payload = {
        "business_date": date.today().isoformat(),
        "captured_at": timezone.now().isoformat(),
        "daily_revenue": "850.50",
        "daily_orders_count": 12,
        "mtd_revenue": "12450.00",
        "last_order_at": timezone.now().isoformat(),
        "open_shifts_count": 1,
        "app_version": "1.2.3",
    }
    resp = api_client.post(
        "/api/v1/telemetry/push/", payload, format="json",
        HTTP_X_RESTAURANT_KEY="test-key-abc",
    )
    assert resp.status_code == 200
    from apps.telemetry.models import TelemetrySnapshot

    snap = TelemetrySnapshot.objects.get()
    assert snap.daily_revenue == Decimal("850.50")
    assert snap.daily_orders_count == 12
    # Heartbeat обновился
    restaurant.refresh_from_db()
    assert restaurant.last_heartbeat_at is not None
    assert restaurant.app_version == "1.2.3"


def test_cloud_telemetry_push_upserts_same_day(api_client, settings, restaurant):
    """Повторный push в тот же день обновляет snapshot, не создаёт новый."""
    settings.SUPERADMIN_ENABLED = True
    restaurant.api_key = "test-key-up"
    restaurant.save(update_fields=["api_key"])

    today = date.today().isoformat()
    for revenue in ("100.00", "250.00", "500.00"):
        api_client.post(
            "/api/v1/telemetry/push/",
            {
                "business_date": today,
                "captured_at": timezone.now().isoformat(),
                "daily_revenue": revenue,
                "daily_orders_count": 5,
            },
            format="json",
            HTTP_X_RESTAURANT_KEY="test-key-up",
        )
    from apps.telemetry.models import TelemetrySnapshot

    assert TelemetrySnapshot.objects.count() == 1
    assert TelemetrySnapshot.objects.get().daily_revenue == Decimal("500.00")


def test_cloud_telemetry_push_missing_key(api_client, settings, restaurant):
    settings.SUPERADMIN_ENABLED = True
    resp = api_client.post(
        "/api/v1/telemetry/push/",
        {"business_date": date.today().isoformat(),
         "captured_at": timezone.now().isoformat()},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_REQUIRED"


def test_cloud_telemetry_push_unknown_key(api_client, settings, restaurant):
    settings.SUPERADMIN_ENABLED = True
    resp = api_client.post(
        "/api/v1/telemetry/push/",
        {"business_date": date.today().isoformat(),
         "captured_at": timezone.now().isoformat()},
        format="json",
        HTTP_X_RESTAURANT_KEY="not-in-db",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID"


def test_cloud_telemetry_push_404_in_restaurant_mode(api_client, restaurant):
    """На restaurant-инстансе endpoint недоступен."""
    restaurant.api_key = "k-resto"
    restaurant.save(update_fields=["api_key"])
    with override_settings(SUPERADMIN_ENABLED=False):
        _refresh_urlconf()
        try:
            resp = api_client.post(
                "/api/v1/telemetry/push/",
                {"business_date": date.today().isoformat(),
                 "captured_at": timezone.now().isoformat()},
                format="json",
                HTTP_X_RESTAURANT_KEY="k-resto",
            )
            assert resp.status_code == 404
        finally:
            _refresh_urlconf()


# -------- Management command --------


def test_push_telemetry_command_skips_on_cloud(db, settings):
    from django.core.management import call_command

    settings.SUPERADMIN_ENABLED = True
    # Не должно упасть и ничего не сделать
    call_command("push_telemetry", verbosity=0)
