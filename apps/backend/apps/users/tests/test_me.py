import pytest

pytestmark = pytest.mark.django_db


def test_me_unauthorized(api_client):
    resp = api_client.get("/api/v1/auth/me/")
    assert resp.status_code == 401


def test_me_with_pin_session(api_client, cashier):
    login = api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()
    token = login["data"]["session_token"]

    resp = api_client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"PIN {token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["user"]["username"] == "cashier1"
    assert body["data"]["restaurant"]["currency"] == "TJS"


def test_me_with_jwt(api_client, waiter):
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]

    resp = api_client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["role"] == "waiter"


def test_pin_session_extends_on_use(api_client, cashier):
    from apps.users.models import PinSession

    login = api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()
    token = login["data"]["session_token"]

    session = PinSession.objects.get(token=token)
    expires_before = session.expires_at

    api_client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"PIN {token}")

    session.refresh_from_db()
    assert session.expires_at >= expires_before


def test_pin_logout(api_client, cashier):
    from apps.users.models import PinSession

    login = api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()
    token = login["data"]["session_token"]

    resp = api_client.post(
        "/api/v1/auth/pin/logout/", HTTP_AUTHORIZATION=f"PIN {token}"
    )
    assert resp.status_code == 200
    assert not PinSession.objects.filter(token=token).exists()


def test_expired_pin_session_returns_401(api_client, cashier):
    from datetime import timedelta

    from django.utils import timezone

    from apps.users.models import PinSession

    session = PinSession.objects.create(
        user=cashier,
        token="expired-token-fixture",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    resp = api_client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"PIN {session.token}")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_TOKEN_EXPIRED"
