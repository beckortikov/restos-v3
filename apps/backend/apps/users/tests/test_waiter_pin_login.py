import pytest

pytestmark = pytest.mark.django_db


URL = "/api/v1/auth/waiter/pin/"


@pytest.fixture
def waiter_with_pin(waiter):
    waiter.set_pin("5678")
    waiter.save(update_fields=["pin_hash"])
    return waiter


def test_waiter_pin_login_success(api_client, waiter_with_pin):
    resp = api_client.post(URL, {"pin": "5678"}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["access"]
    assert body["refresh"]
    assert body["user"]["role"] == "waiter"
    assert body["user"]["full_name"] == "Карим Официант"


def test_waiter_pin_login_returns_jwt_usable_for_me(api_client, waiter_with_pin):
    resp = api_client.post(URL, {"pin": "5678"}, format="json")
    access = resp.json()["data"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    me = api_client.get("/api/v1/auth/me/")
    assert me.status_code == 200
    assert me.json()["data"]["user"]["role"] == "waiter"


def test_waiter_pin_login_invalid(api_client, waiter_with_pin):
    resp = api_client.post(URL, {"pin": "0000"}, format="json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID_PIN"


def test_waiter_pin_login_validates_format(api_client, waiter_with_pin):
    resp = api_client.post(URL, {"pin": "ab"}, format="json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID_PIN"


def test_waiter_pin_does_not_accept_cashier(api_client, cashier):
    # У кассира PIN 1234, но эндпоинт /auth/waiter/pin/ ищет только role=waiter
    resp = api_client.post(URL, {"pin": "1234"}, format="json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID_PIN"


def test_cashier_pin_endpoint_does_not_accept_waiter(api_client, waiter_with_pin):
    # И наоборот — официант не может зайти через касс. /auth/pin/
    resp = api_client.post("/api/v1/auth/pin/", {"pin": "5678"}, format="json")
    assert resp.status_code == 401


def test_waiter_pin_lockout_after_threshold(api_client, waiter_with_pin, settings):
    settings.PIN_LOCK_THRESHOLD = 5
    for _ in range(5):
        resp = api_client.post(URL, {"pin": "0000"}, format="json")
        assert resp.status_code == 401

    resp = api_client.post(URL, {"pin": "5678"}, format="json")
    assert resp.status_code == 401
    waiter_with_pin.refresh_from_db()
    assert waiter_with_pin.locked_until is not None


def test_waiter_pin_resets_failed_attempts_on_success(api_client, waiter_with_pin):
    api_client.post(URL, {"pin": "0000"}, format="json")
    api_client.post(URL, {"pin": "0000"}, format="json")
    waiter_with_pin.refresh_from_db()
    assert waiter_with_pin.failed_pin_attempts == 2

    resp = api_client.post(URL, {"pin": "5678"}, format="json")
    assert resp.status_code == 200
    waiter_with_pin.refresh_from_db()
    assert waiter_with_pin.failed_pin_attempts == 0
    assert waiter_with_pin.locked_until is None


def test_waiter_pin_cross_restaurant_isolation(api_client, waiter_with_pin, settings):
    from apps.users.models import Restaurant, User, UserRole

    other = Restaurant.objects.create(name="Other", currency="TJS", pin_lock_timeout_min=30)
    other_waiter = User.objects.create_user(
        username="w2", password="x", full_name="Other Waiter",
        role=UserRole.WAITER, restaurant=other,
    )
    other_waiter.set_pin("5678")
    other_waiter.save(update_fields=["pin_hash"])

    # settings.MVP_RESTAURANT_ID указывает на restaurant из fixture — заходит он
    resp = api_client.post(URL, {"pin": "5678"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["full_name"] == "Карим Официант"
