"""License: модель, middleware, heartbeat, status."""
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def license_obj(restaurant):
    """Лицензия для restaurant — создаётся auto-trial сигналом, но в тестах
    проверяем, что есть; иначе создаём вручную."""
    from apps.licensing.models import License, LicensePlan

    lic, _ = License.objects.get_or_create(
        restaurant=restaurant,
        defaults={
            "plan": LicensePlan.TRIAL,
            "started_at": timezone.now(),
            "expires_at": timezone.now() + timedelta(days=30),
        },
    )
    return lic


# -------- Auto-trial signal --------


def test_new_restaurant_auto_gets_trial_license(db):
    from apps.licensing.models import License
    from apps.users.models import Restaurant

    r = Restaurant.objects.create(name="Auto", currency="TJS")
    lic = License.objects.get(restaurant=r)
    assert lic.plan == "trial"
    assert lic.expires_at > timezone.now()
    assert lic.is_writable


# -------- Status / properties --------


def test_status_active_when_in_window(license_obj):
    license_obj.expires_at = timezone.now() + timedelta(days=10)
    license_obj.save()
    assert license_obj.status == "active"
    assert license_obj.is_writable


def test_status_grace_after_expires(license_obj):
    license_obj.expires_at = timezone.now() - timedelta(days=2)
    license_obj.save()
    assert license_obj.status == "grace"
    assert license_obj.is_writable


def test_status_expired_after_grace(license_obj):
    license_obj.expires_at = timezone.now() - timedelta(days=10)  # > 7d grace
    license_obj.save()
    assert license_obj.status == "expired"
    assert not license_obj.is_writable


def test_status_blocked_overrides_grace(license_obj):
    license_obj.expires_at = timezone.now() + timedelta(days=10)
    license_obj.is_blocked = True
    license_obj.save()
    assert license_obj.status == "blocked"
    assert not license_obj.is_writable


def test_renew_extends_from_expires_when_active(license_obj):
    license_obj.expires_at = timezone.now() + timedelta(days=5)
    license_obj.save()
    license_obj.renew(days=30)
    delta = license_obj.expires_at - timezone.now()
    assert 33 <= delta.days <= 36  # ~5+30 = 35


def test_renew_extends_from_now_when_expired(license_obj):
    license_obj.expires_at = timezone.now() - timedelta(days=15)
    license_obj.save()
    license_obj.renew(days=30)
    delta = license_obj.expires_at - timezone.now()
    assert 28 <= delta.days <= 32


def test_renew_clears_block(license_obj):
    license_obj.is_blocked = True
    license_obj.block_reason = "Неуплата"
    license_obj.save()
    license_obj.renew(days=30)
    assert not license_obj.is_blocked
    assert license_obj.block_reason == ""


# -------- Middleware: writes blocked when expired --------


def test_writes_allowed_when_active(
    api_client, restaurant, cashier, license_obj,
):
    """POST/PATCH работают на active-лицензии."""
    license_obj.expires_at = timezone.now() + timedelta(days=10)
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200


def test_writes_allowed_in_grace(
    api_client, restaurant, cashier, license_obj,
):
    """В grace-периоде writes ещё работают."""
    license_obj.expires_at = timezone.now() - timedelta(days=2)
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200


def test_writes_blocked_when_expired(
    api_client, restaurant, cashier, license_obj,
):
    """После grace-периода — 402 LICENSE_EXPIRED."""
    license_obj.expires_at = timezone.now() - timedelta(days=10)
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 402
    body = resp.json()["error"]
    assert body["code"] == "LICENSE_EXPIRED"
    assert body["detail"]["status"] == "expired"


def test_writes_blocked_when_blocked(
    api_client, restaurant, cashier, license_obj,
):
    """is_blocked=True блокирует writes мгновенно (даже в активный период)."""
    license_obj.expires_at = timezone.now() + timedelta(days=10)
    license_obj.is_blocked = True
    license_obj.block_reason = "Неуплата"
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "LICENSE_BLOCKED"


def test_reads_allowed_even_when_expired(
    api_client, restaurant, cashier, license_obj,
):
    """GET-запросы пропускаются всегда (read-only режим)."""
    license_obj.expires_at = timezone.now() - timedelta(days=30)
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/restaurant/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200


def test_auth_endpoints_allowed_when_expired(
    api_client, restaurant, cashier, license_obj,
):
    """PIN-логин должен работать всегда — иначе кассир не сможет даже зайти."""
    license_obj.expires_at = timezone.now() - timedelta(days=30)
    license_obj.save()

    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json",
    )
    assert resp.status_code == 200


def test_license_status_endpoint_works_when_expired(
    api_client, restaurant, cashier, license_obj,
):
    """Endpoint статуса должен отвечать даже на expired (для UI-баннера)."""
    license_obj.expires_at = timezone.now() - timedelta(days=30)
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/license/status/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "expired"
    assert body["is_writable"] is False


# -------- Heartbeat --------


def test_heartbeat_updates_last_seen(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/heartbeat/",
        {"app_version": "1.2.3"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    restaurant.refresh_from_db()
    assert restaurant.last_heartbeat_at is not None
    assert restaurant.app_version == "1.2.3"


def test_heartbeat_works_when_license_expired(
    api_client, restaurant, cashier, license_obj,
):
    """Heartbeat должен работать всегда — это write-метод, но в исключениях."""
    license_obj.expires_at = timezone.now() - timedelta(days=30)
    license_obj.save()
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/heartbeat/", {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200


# -------- License status response --------


def test_status_endpoint_returns_correct_fields(
    api_client, restaurant, cashier, license_obj,
):
    license_obj.expires_at = timezone.now() + timedelta(days=20)
    license_obj.plan = "business"
    license_obj.save()

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/license/status/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()["data"]
    assert body["plan"] == "business"
    assert body["status"] == "active"
    assert body["is_writable"] is True
    assert "expires_at" in body
    assert "grace_until" in body
    assert "days_to_expiry" in body
