"""Super-admin: auth + restaurants management + license operations."""
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa_user(db):
    """Создаёт super-admin без ресторана."""
    from apps.users.models import User, UserRole

    user = User.objects.create_user(
        username="vendor1",
        password="vendor-secret-123",
        full_name="Vendor Admin",
        role=UserRole.MANAGER,
        restaurant=None,
        is_active=True,
    )
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    return user


@pytest.fixture
def sa_token(api_client, sa_user):
    resp = api_client.post(
        "/api/v1/superadmin/auth/login/",
        {"username": "vendor1", "password": "vendor-secret-123"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["token"]


# -------- Auth --------


def test_login_success(api_client, sa_user):
    resp = api_client.post(
        "/api/v1/superadmin/auth/login/",
        {"username": "vendor1", "password": "vendor-secret-123"},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "token" in data
    assert data["user"]["username"] == "vendor1"


def test_login_wrong_password(api_client, sa_user):
    resp = api_client.post(
        "/api/v1/superadmin/auth/login/",
        {"username": "vendor1", "password": "wrong"},
        format="json",
    )
    assert resp.status_code == 401


def test_login_non_superuser_rejected(api_client, cashier):
    """Обычный кассир с паролем не может получить SA-токен."""
    resp = api_client.post(
        "/api/v1/superadmin/auth/login/",
        {"username": "cashier1", "password": "cashier-pass"},
        format="json",
    )
    assert resp.status_code == 401


def test_endpoint_without_token_rejected(api_client):
    resp = api_client.get("/api/v1/superadmin/restaurants/")
    assert resp.status_code in (401, 403)


def test_endpoint_with_invalid_token_rejected(api_client):
    resp = api_client.get(
        "/api/v1/superadmin/restaurants/",
        HTTP_AUTHORIZATION="SA invalid.token.here",
    )
    assert resp.status_code in (401, 403)


def test_endpoint_with_cashier_pin_rejected(api_client, cashier):
    """PIN-сессия НЕ даёт доступа к SA-API даже если у юзера is_superuser=False."""
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json",
    )
    pin = resp.json()["data"]["session_token"]
    resp2 = api_client.get(
        "/api/v1/superadmin/restaurants/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp2.status_code in (401, 403)


# -------- Restaurants --------


def test_list_restaurants(api_client, sa_token, restaurant):
    resp = api_client.get(
        "/api/v1/superadmin/restaurants/",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    names = [r["name"] for r in rows]
    assert restaurant.name in names
    # У ресторана-фикстуры есть активная лицензия (auto-trial)
    me = next(r for r in rows if r["name"] == restaurant.name)
    assert me["license_status"] in ("active", "grace", "expired", "blocked")
    assert "today_revenue" in me


def test_create_restaurant(api_client, sa_token):
    from apps.licensing.models import License
    from apps.users.models import Restaurant

    resp = api_client.post(
        "/api/v1/superadmin/restaurants/create/",
        {
            "name": "Кафе Анвар", "currency": "TJS",
            "address": "Душанбе", "phone": "+992900000000",
        },
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["name"] == "Кафе Анвар"
    r = Restaurant.objects.get(id=data["id"])
    # Auto-trial signal выдал лицензию
    assert License.objects.filter(restaurant=r).exists()


def test_create_restaurant_duplicate_name(api_client, sa_token, restaurant):
    resp = api_client.post(
        "/api/v1/superadmin/restaurants/create/",
        {"name": restaurant.name, "currency": "TJS"},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 400


def test_restaurant_detail(api_client, sa_token, restaurant):
    resp = api_client.get(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == restaurant.name


def test_restaurant_update(api_client, sa_token, restaurant):
    resp = api_client.patch(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/",
        {"address": "Душанбе, Рудаки 100"},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    restaurant.refresh_from_db()
    assert restaurant.address == "Душанбе, Рудаки 100"


def test_restaurant_update_disallowed_field(api_client, sa_token, restaurant):
    """SA не редактирует через PATCH last_heartbeat_at и т.д."""
    resp = api_client.patch(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/",
        {"last_heartbeat_at": "2026-01-01T00:00:00Z"},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 400


# -------- License --------


def test_license_detail(api_client, sa_token, restaurant):
    resp = api_client.get(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan"] == "trial"
    assert "expires_at" in data
    assert data["status"] in ("active", "grace", "expired", "blocked")


def test_license_extend(api_client, sa_token, restaurant):
    lic = restaurant.license
    before = lic.expires_at
    resp = api_client.post(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/extend/",
        {"days": 90},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    lic.refresh_from_db()
    assert lic.expires_at > before + timedelta(days=89)


def test_license_extend_from_expired(api_client, sa_token, restaurant):
    """Продление после истечения = now + days, не from past expires."""
    lic = restaurant.license
    lic.expires_at = timezone.now() - timedelta(days=30)
    lic.save(update_fields=["expires_at"])
    resp = api_client.post(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/extend/",
        {"days": 30},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    lic.refresh_from_db()
    assert lic.expires_at > timezone.now() + timedelta(days=29)


def test_license_change_plan(api_client, sa_token, restaurant):
    resp = api_client.post(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/change_plan/",
        {"plan": "pro"},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    restaurant.license.refresh_from_db()
    assert restaurant.license.plan == "pro"


def test_license_change_plan_invalid(api_client, sa_token, restaurant):
    resp = api_client.post(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/change_plan/",
        {"plan": "ultra-mega"},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 400


def test_license_block_and_unblock(api_client, sa_token, restaurant):
    resp = api_client.post(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/block/",
        {"reason": "Не оплачено"},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    restaurant.license.refresh_from_db()
    assert restaurant.license.is_blocked is True
    assert "Не оплачено" in restaurant.license.block_reason

    resp2 = api_client.post(
        f"/api/v1/superadmin/restaurants/{restaurant.id}/license/unblock/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp2.status_code == 200
    restaurant.license.refresh_from_db()
    assert restaurant.license.is_blocked is False


# -------- Stats --------


def test_stats(api_client, sa_token, restaurant):
    resp = api_client.get(
        "/api/v1/superadmin/stats/",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_restaurants"] >= 1
    assert "license_status" in data
    assert "plan_counts" in data
    # trial есть в plan_counts (наш restaurant ведь имеет триал)
    assert data["plan_counts"].get("trial", 0) >= 1


# -------- 404 --------


def test_extend_nonexistent_restaurant(api_client, sa_token):
    resp = api_client.post(
        "/api/v1/superadmin/restaurants/99999/license/extend/",
        {"days": 30},
        format="json",
        HTTP_AUTHORIZATION=f"SA {sa_token}",
    )
    assert resp.status_code == 404


# -------- Management command --------


def test_create_superadmin_command(db):
    from django.core.management import call_command

    from apps.users.models import User

    call_command(
        "create_superadmin",
        "--username", "vendor2",
        "--password", "supersecret",
        "--full-name", "Vendor Two",
    )
    u = User.objects.get(username="vendor2")
    assert u.is_superuser is True
    assert u.is_staff is True
    assert u.restaurant is None
    assert u.check_password("supersecret")


def test_create_superadmin_command_updates_existing(db, cashier):
    """Повторный запуск с существующим username — поднимает is_superuser."""
    from django.core.management import call_command

    from apps.users.models import User

    cashier.refresh_from_db()
    assert cashier.is_superuser is False
    call_command(
        "create_superadmin",
        "--username", cashier.username,
        "--password", "newsupersecret",
    )
    cashier.refresh_from_db()
    assert cashier.is_superuser is True
    assert cashier.restaurant is None
    assert cashier.check_password("newsupersecret")
