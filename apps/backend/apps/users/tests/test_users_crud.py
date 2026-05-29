"""UserAdminViewSet — frame 20 «Настройки / Пользователи»."""
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()
    return resp["data"]["session_token"]


@pytest.fixture
def auth(cashier_token):
    return {"HTTP_AUTHORIZATION": f"PIN {cashier_token}"}


def test_list_users(api_client, cashier, waiter, auth):
    resp = api_client.get("/api/v1/users/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    usernames = {u["username"] for u in body["data"]}
    assert {"cashier1", "waiter1"} <= usernames
    # has_pin: cashier — да (1234), waiter — нет (PIN не установлен)
    by_name = {u["username"]: u for u in body["data"]}
    assert by_name["cashier1"]["has_pin"] is True
    assert by_name["waiter1"]["has_pin"] is False


def test_create_user_with_pin(api_client, cashier, auth):
    resp = api_client.post(
        "/api/v1/users/",
        {
            "username": "cashier_new",
            "full_name": "Новый Кассир",
            "role": "cashier",
            "is_active": True,
            "pin": "5678",
        },
        format="json",
        **auth,
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["username"] == "cashier_new"
    assert body["has_pin"] is True
    assert "pin" not in body  # PIN — write_only

    # Логин нового кассира под новым PIN'ом работает
    login = api_client.post("/api/v1/auth/pin/", {"pin": "5678"}, format="json")
    assert login.status_code == 200


def test_create_user_invalid_role(api_client, cashier, auth):
    resp = api_client.post(
        "/api/v1/users/",
        {
            "username": "u1",
            "full_name": "Test",
            "role": "owner",  # запрещено
            "is_active": True,
        },
        format="json",
        **auth,
    )
    assert resp.status_code == 400


def test_update_user(api_client, cashier, waiter, auth):
    resp = api_client.patch(
        f"/api/v1/users/{waiter.id}/",
        {"full_name": "Карим Updated", "is_active": False},
        format="json",
        **auth,
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["full_name"] == "Карим Updated"
    assert body["is_active"] is False


def test_set_pin_action(api_client, cashier, waiter, auth):
    resp = api_client.post(
        f"/api/v1/users/{waiter.id}/set_pin/",
        {"pin": "9999"},
        format="json",
        **auth,
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["has_pin"] is True

    waiter.refresh_from_db()
    assert waiter.check_pin("9999")


def test_set_pin_invalid(api_client, cashier, waiter, auth):
    resp = api_client.post(
        f"/api/v1/users/{waiter.id}/set_pin/",
        {"pin": "12"},
        format="json",
        **auth,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PIN_INVALID"


def test_destroy_user(api_client, cashier, waiter, auth):
    resp = api_client.delete(f"/api/v1/users/{waiter.id}/", **auth)
    assert resp.status_code == 204


def test_cannot_destroy_self(api_client, cashier, auth):
    resp = api_client.delete(f"/api/v1/users/{cashier.id}/", **auth)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "USER_SELF_DELETE"


def test_waiter_can_list_users_but_not_write(api_client, cashier, waiter):
    """Waiter может GET /users/ (для assignWaiter-диалога и отображения имён),
    но не может создавать/обновлять/удалять — только cashier+."""
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]
    # GET — разрешено
    resp = api_client.get(
        "/api/v1/users/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert resp.status_code == 200

    # POST — запрещено
    resp = api_client.post(
        "/api/v1/users/",
        {"username": "x", "full_name": "X", "role": "waiter"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403


def test_cross_restaurant_isolation(api_client, cashier, auth):
    """Пользователи другого ресторана не видны и не доступны для CRUD."""
    from apps.users.models import Restaurant, User, UserRole

    other_resto = Restaurant.objects.create(name="Other", currency="USD")
    other_user = User.objects.create_user(
        username="other1",
        password="x",
        full_name="Другой",
        role=UserRole.WAITER,
        restaurant=other_resto,
    )

    resp = api_client.get("/api/v1/users/", **auth)
    ids = {u["id"] for u in resp.json()["data"]}
    assert other_user.id not in ids

    resp = api_client.get(f"/api/v1/users/{other_user.id}/", **auth)
    assert resp.status_code == 404
