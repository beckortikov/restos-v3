"""SA-7 — Machine binding (hardware_uuid) тесты."""
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def license_obj(restaurant):
    """Auto-trial signal создаёт License при создании Restaurant — обновляем её."""
    from apps.licensing.models import License, LicensePlan
    lic, _ = License.objects.update_or_create(
        restaurant=restaurant,
        defaults={
            "plan": LicensePlan.BUSINESS,
            "license_key": "TESTKEY-12345-ABCDE",
            "started_at": timezone.now(),
            "expires_at": timezone.now() + timedelta(days=30),
            "hardware_uuid": "",
            "activated_at": None,
            "is_blocked": False,
        },
    )
    return lic


VALID_HWID = "4C4C4544-0058-5A10-8048-CAC04F595633"
OTHER_HWID = "DEADBEEF-1234-5678-9ABC-DEF012345678"


def test_activate_first_time_saves_hwid(api_client, license_obj):
    resp = api_client.post(
        "/api/v1/license/activate/",
        {"license_key": "TESTKEY-12345-ABCDE", "hardware_uuid": VALID_HWID},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["ok"] is True
    assert body["first_activation"] is True
    license_obj.refresh_from_db()
    assert license_obj.hardware_uuid == VALID_HWID
    assert license_obj.activated_at is not None


def test_activate_same_machine_again_ok(api_client, license_obj):
    license_obj.hardware_uuid = VALID_HWID
    license_obj.activated_at = timezone.now()
    license_obj.save()

    resp = api_client.post(
        "/api/v1/license/activate/",
        {"license_key": "TESTKEY-12345-ABCDE", "hardware_uuid": VALID_HWID},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["first_activation"] is False


def test_activate_other_machine_blocked(api_client, license_obj):
    license_obj.hardware_uuid = VALID_HWID
    license_obj.save()

    resp = api_client.post(
        "/api/v1/license/activate/",
        {"license_key": "TESTKEY-12345-ABCDE", "hardware_uuid": OTHER_HWID},
        format="json",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MACHINE_MISMATCH"
    license_obj.refresh_from_db()
    assert license_obj.hardware_uuid == VALID_HWID


def test_activate_blocked_license(api_client, license_obj):
    license_obj.is_blocked = True
    license_obj.block_reason = "Неуплата"
    license_obj.save()

    resp = api_client.post(
        "/api/v1/license/activate/",
        {"license_key": "TESTKEY-12345-ABCDE", "hardware_uuid": VALID_HWID},
        format="json",
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "LICENSE_BLOCKED"


def test_activate_unknown_key(api_client):
    resp = api_client.post(
        "/api/v1/license/activate/",
        {"license_key": "NOTHING", "hardware_uuid": VALID_HWID},
        format="json",
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "LICENSE_NOT_FOUND"


def test_activate_invalid_hwid_all_zeros(api_client, license_obj):
    resp = api_client.post(
        "/api/v1/license/activate/",
        {
            "license_key": "TESTKEY-12345-ABCDE",
            "hardware_uuid": "00000000-0000-0000-0000-000000000000",
        },
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_VALUE"


def test_activate_short_hwid(api_client, license_obj):
    resp = api_client.post(
        "/api/v1/license/activate/",
        {"license_key": "TESTKEY-12345-ABCDE", "hardware_uuid": "short"},
        format="json",
    )
    assert resp.status_code == 400


def test_middleware_blocks_wrong_machine_on_write(
    api_client, cashier, restaurant, license_obj,
):
    license_obj.hardware_uuid = VALID_HWID
    license_obj.save()
    pin = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]
    from apps.menu.models import Category
    cat = Category.objects.create(restaurant=restaurant, name="X", sort_order=1)
    resp = api_client.post(
        "/api/v1/menu/items/",
        {"category": cat.id, "name": "Test", "price": "10.00"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_X_MACHINE_UUID=OTHER_HWID,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MACHINE_MISMATCH"


def test_middleware_allows_correct_machine(
    api_client, cashier, restaurant, license_obj,
):
    license_obj.hardware_uuid = VALID_HWID
    license_obj.save()
    pin = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]
    from apps.menu.models import Category
    cat = Category.objects.create(restaurant=restaurant, name="X", sort_order=1)
    resp = api_client.post(
        "/api/v1/menu/items/",
        {"category": cat.id, "name": "Test", "price": "10.00"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_X_MACHINE_UUID=VALID_HWID,
    )
    assert resp.status_code in (200, 201)


def test_middleware_skips_check_when_not_bound(
    api_client, cashier, restaurant, license_obj,
):
    """Если License.hardware_uuid пуст — пускаем."""
    assert license_obj.hardware_uuid == ""
    pin = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]
    from apps.menu.models import Category
    cat = Category.objects.create(restaurant=restaurant, name="X", sort_order=1)
    resp = api_client.post(
        "/api/v1/menu/items/",
        {"category": cat.id, "name": "Test", "price": "10.00"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code in (200, 201)


def test_middleware_read_methods_skip_check(api_client, cashier, license_obj):
    license_obj.hardware_uuid = VALID_HWID
    license_obj.save()
    pin = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]
    resp = api_client.get(
        "/api/v1/menu/items/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_X_MACHINE_UUID=OTHER_HWID,
    )
    assert resp.status_code == 200


def test_reset_binding_allows_reactivation(license_obj):
    license_obj.hardware_uuid = VALID_HWID
    license_obj.activated_at = timezone.now()
    license_obj.save()
    # имитация admin action
    license_obj.hardware_uuid = ""
    license_obj.activated_at = None
    license_obj.save()
    license_obj.refresh_from_db()
    assert license_obj.hardware_uuid == ""
    assert license_obj.activated_at is None
