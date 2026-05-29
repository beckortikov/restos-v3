import pytest

pytestmark = pytest.mark.django_db


URL = "/api/v1/auth/pin/"


def test_pin_login_success(api_client, cashier):
    resp = api_client.post(URL, {"pin": "1234"}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "data" in body
    assert body["data"]["session_token"]
    assert body["data"]["user"]["role"] == "cashier"
    assert body["data"]["user"]["full_name"] == "Анна Кассир"
    assert body["data"]["expires_at"]


def test_pin_login_invalid(api_client, cashier):
    resp = api_client.post(URL, {"pin": "9999"}, format="json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID_PIN"


def test_pin_login_validates_format(api_client, cashier):
    resp = api_client.post(URL, {"pin": "abc"}, format="json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID_PIN"


def test_pin_lockout_after_5_attempts(api_client, cashier, settings):
    settings.PIN_LOCK_THRESHOLD = 5
    for _ in range(5):
        resp = api_client.post(URL, {"pin": "9999"}, format="json")
        assert resp.status_code == 401

    # 6-я попытка с правильным PIN всё равно отклонена — locked_until стоит
    resp = api_client.post(URL, {"pin": "1234"}, format="json")
    assert resp.status_code == 401
    cashier.refresh_from_db()
    assert cashier.locked_until is not None


def test_pin_login_resets_failed_attempts_on_success(api_client, cashier):
    api_client.post(URL, {"pin": "9999"}, format="json")
    api_client.post(URL, {"pin": "9999"}, format="json")
    cashier.refresh_from_db()
    assert cashier.failed_pin_attempts == 2

    resp = api_client.post(URL, {"pin": "1234"}, format="json")
    assert resp.status_code == 200
    cashier.refresh_from_db()
    assert cashier.failed_pin_attempts == 0
    assert cashier.locked_until is None
