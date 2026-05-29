from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Горячее", sort_order=1)


@pytest.fixture
def items(restaurant, category):
    from apps.menu.models import MenuItem

    plov = MenuItem.objects.create(
        restaurant=restaurant,
        category=category,
        name="Плов",
        price=Decimal("45.00"),
        emoji="🍚",
        sort_order=1,
    )
    chai = MenuItem.objects.create(
        restaurant=restaurant,
        category=category,
        name="Чай",
        price=Decimal("8.00"),
        sort_order=2,
        is_available=False,
    )
    return [plov, chai]


def _pin_token(api_client, cashier):
    return api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()[
        "data"
    ]["session_token"]


def _jwt(api_client, waiter):
    return api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]


def test_menu_requires_auth(api_client, items):
    resp = api_client.get("/api/v1/menu/items/")
    assert resp.status_code == 401


def test_categories_list(api_client, cashier, category):
    token = _pin_token(api_client, cashier)
    resp = api_client.get(
        "/api/v1/menu/categories/", HTTP_AUTHORIZATION=f"PIN {token}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["name"] == "Горячее"


def test_menu_items_list(api_client, waiter, items):
    access = _jwt(api_client, waiter)
    resp = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert resp.headers["ETag"].startswith('W/"')
    assert resp.headers["Cache-Control"] == "max-age=300"
    plov = next(i for i in body["data"] if i["name"] == "Плов")
    assert plov["price"] == "45.00"
    assert plov["emoji"] == "🍚"
    assert plov["is_available"] is True


def test_menu_filter_is_available(api_client, waiter, items):
    access = _jwt(api_client, waiter)
    resp = api_client.get(
        "/api/v1/menu/items/?is_available=true",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 200
    names = [i["name"] for i in resp.json()["data"]]
    assert names == ["Плов"]


def test_menu_etag_returns_304(api_client, waiter, items):
    access = _jwt(api_client, waiter)
    first = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    etag = first.headers["ETag"]

    second = api_client.get(
        "/api/v1/menu/items/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IF_NONE_MATCH=etag,
    )
    assert second.status_code == 304
    assert second.content == b""


def test_menu_etag_changes_after_update(api_client, waiter, items):
    access = _jwt(api_client, waiter)
    first_etag = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"Bearer {access}"
    ).headers["ETag"]

    items[0].price = Decimal("50.00")
    items[0].save()

    new_etag = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"Bearer {access}"
    ).headers["ETag"]

    assert new_etag != first_etag


def test_menu_isolated_by_restaurant(api_client, waiter, items):
    from apps.menu.models import Category, MenuItem
    from apps.users.models import Restaurant

    other_resto = Restaurant.objects.create(name="Other", currency="TJS")
    other_cat = Category.objects.create(restaurant=other_resto, name="Other cat")
    MenuItem.objects.create(
        restaurant=other_resto,
        category=other_cat,
        name="Foreign dish",
        price=Decimal("100"),
    )

    access = _jwt(api_client, waiter)
    body = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"Bearer {access}"
    ).json()
    names = [i["name"] for i in body["data"]]
    assert "Foreign dish" not in names
    assert body["meta"]["total"] == 2


def test_category_with_print_station(api_client, cashier, restaurant):
    """Категория может быть привязана к PrintStation через API."""
    from apps.printing.models import PrintStation

    station = PrintStation.objects.filter(
        restaurant=restaurant, name="Горячий цех"
    ).first()
    assert station is not None
    token = _pin_token(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/categories/",
        {"name": "Шашлыки", "sort_order": 5, "print_station": station.id},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["print_station"] == station.id
    assert body["print_station_name"] == "Горячий цех"


def test_category_print_station_nullable(api_client, cashier):
    """Категория может быть без цеха."""
    token = _pin_token(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/categories/",
        {"name": "Десерты", "sort_order": 6, "print_station": None},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {token}",
    )
    assert resp.status_code == 201
    assert resp.json()["print_station"] is None
