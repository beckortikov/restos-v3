"""GET /menu/full/ — категории + items одним запросом для waiter."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def test_menu_full_returns_categories_and_items(api_client, cashier, restaurant):
    from apps.menu.models import Category, MenuItem

    c1 = Category.objects.create(restaurant=restaurant, name="Горячее", sort_order=1)
    c2 = Category.objects.create(restaurant=restaurant, name="Напитки", sort_order=2)
    MenuItem.objects.create(
        restaurant=restaurant, category=c1, name="Плов",
        price=Decimal("45"), is_available=True,
    )
    MenuItem.objects.create(
        restaurant=restaurant, category=c2, name="Чай",
        price=Decimal("8"), is_available=True,
    )
    # Недоступное блюдо — не должно попадать
    MenuItem.objects.create(
        restaurant=restaurant, category=c1, name="Стоп",
        price=Decimal("10"), is_available=False,
    )

    api_client.force_authenticate(user=cashier)
    resp = api_client.get("/api/v1/menu/items/full/")
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert len(body["categories"]) == 2
    assert len(body["items"]) == 2  # Стоп исключён
    names = {it["name"] for it in body["items"]}
    assert names == {"Плов", "Чай"}


def test_menu_full_etag_returns_304(api_client, cashier, restaurant):
    from apps.menu.models import Category, MenuItem

    c = Category.objects.create(restaurant=restaurant, name="Кухня")
    MenuItem.objects.create(
        restaurant=restaurant, category=c, name="Х", price=Decimal("1"),
        is_available=True,
    )

    api_client.force_authenticate(user=cashier)
    r1 = api_client.get("/api/v1/menu/items/full/")
    etag = r1["ETag"]
    assert etag

    r2 = api_client.get(
        "/api/v1/menu/items/full/", HTTP_IF_NONE_MATCH=etag,
    )
    assert r2.status_code == 304


def test_menu_full_cross_restaurant_isolation(api_client, cashier, restaurant):
    """Другой ресторан не виден."""
    from apps.menu.models import Category, MenuItem
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Other", currency="TJS")
    cat = Category.objects.create(restaurant=other, name="Чужое")
    MenuItem.objects.create(
        restaurant=other, category=cat, name="Чужое блюдо",
        price=Decimal("99"), is_available=True,
    )

    api_client.force_authenticate(user=cashier)
    resp = api_client.get("/api/v1/menu/items/full/")
    names = {it["name"] for it in resp.json()["data"]["items"]}
    assert "Чужое блюдо" not in names
