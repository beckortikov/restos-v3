"""User.kitchen_station: API endpoint поддерживает создание cook со станцией."""
import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, pin: str):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": pin}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def station(restaurant):
    from apps.printing.models import PrintStation

    return PrintStation.objects.create(
        restaurant=restaurant, name="Горячий цех", system_code="kitchen",
        is_active=True,
    )


def test_create_cook_with_kitchen_station(api_client, restaurant, cashier, station):
    from apps.users.models import User

    pin = _pin(api_client, "1234")
    resp = api_client.post(
        "/api/v1/users/",
        {
            "username": "newcook",
            "full_name": "Шеф",
            "role": "cook",
            "kitchen_station": station.id,
            "pin": "9999",
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    user = User.objects.get(username="newcook")
    assert user.role == "cook"
    assert user.kitchen_station_id == station.id


def test_create_cashier_ignores_kitchen_station(api_client, restaurant, cashier, station):
    from apps.users.models import User

    pin = _pin(api_client, "1234")
    resp = api_client.post(
        "/api/v1/users/",
        {
            "username": "newcashier",
            "full_name": "К",
            "role": "cashier",
            "kitchen_station": station.id,
            "pin": "8888",
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    user = User.objects.get(username="newcashier")
    assert user.role == "cashier"
    # kitchen_station должна быть очищена
    assert user.kitchen_station_id is None


def test_change_role_from_cook_to_cashier_clears_station(
    api_client, restaurant, cashier, station,
):
    from apps.users.models import User, UserRole

    cook = User.objects.create_user(
        username="x", password="x", full_name="X", role=UserRole.COOK,
        restaurant=restaurant, kitchen_station=station,
    )
    pin = _pin(api_client, "1234")
    resp = api_client.patch(
        f"/api/v1/users/{cook.id}/",
        {"role": "cashier"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    cook.refresh_from_db()
    assert cook.role == "cashier"
    assert cook.kitchen_station_id is None


def test_user_serializer_includes_kitchen_station(
    api_client, restaurant, cashier, station,
):
    from apps.users.models import User, UserRole

    cook = User.objects.create_user(
        username="x", password="x", full_name="X", role=UserRole.COOK,
        restaurant=restaurant, kitchen_station=station,
    )
    pin = _pin(api_client, "1234")
    resp = api_client.get(
        f"/api/v1/users/{cook.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()["data"]
    assert body["kitchen_station"] == station.id


def test_create_cook_role_via_api(api_client, restaurant, cashier):
    """Регрессия: API должен принимать role=cook (раньше только cashier/waiter)."""
    pin = _pin(api_client, "1234")
    resp = api_client.post(
        "/api/v1/users/",
        {
            "username": "cook2", "full_name": "C", "role": "cook", "pin": "7777",
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
