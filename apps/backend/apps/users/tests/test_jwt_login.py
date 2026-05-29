import pytest

pytestmark = pytest.mark.django_db


def test_jwt_login_success(api_client, waiter):
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["data"]["access"]
    assert body["data"]["refresh"]
    assert body["data"]["user"]["role"] == "waiter"


def test_jwt_login_invalid(api_client, waiter):
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "wrong"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_jwt_refresh(api_client, waiter):
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    refresh = login["data"]["refresh"]

    resp = api_client.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["access"]
