"""Расширенные поля MenuItem: kind, unit, batch, purchased, COGS, cook_time."""
from decimal import Decimal

import pytest
from django.db.utils import IntegrityError

pytestmark = pytest.mark.django_db


def _pin(api_client, user):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Меню")


# -------- Defaults --------


def test_menu_item_defaults(restaurant, category):
    from apps.menu.models import MenuItem, MenuItemKind, MenuItemUnit

    mi = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов",
        price=Decimal("45.00"),
    )
    assert mi.kind == MenuItemKind.HOT_KITCHEN
    assert mi.unit == MenuItemUnit.PIECE
    assert mi.unit_size == 1
    assert mi.sale_step == 0
    assert mi.cogs == Decimal("0")
    assert mi.cook_time_min is None
    assert mi.is_purchased is False
    assert mi.is_batch_cooking is False
    assert mi.prepared_qty == 0
    assert mi.is_low_stock is False  # не batch → low_stock = False


# -------- Constraints --------


def test_cannot_be_purchased_and_batch_simultaneously(restaurant, category):
    from apps.menu.models import MenuItem

    with pytest.raises(IntegrityError):
        MenuItem.objects.create(
            restaurant=restaurant, category=category, name="X",
            price=Decimal("10"),
            is_purchased=True, is_batch_cooking=True,
        )


def test_unit_size_must_be_positive(restaurant, category):
    from apps.menu.models import MenuItem

    with pytest.raises(IntegrityError):
        MenuItem.objects.create(
            restaurant=restaurant, category=category, name="X",
            price=Decimal("10"), unit_size=0,
        )


# -------- Batch low-stock signal --------


def test_is_low_stock_true_when_prepared_le_threshold(restaurant, category):
    from apps.menu.models import MenuItem

    mi = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов утренний",
        price=Decimal("45"),
        is_batch_cooking=True, prepared_qty=3, low_stock_threshold=5,
    )
    assert mi.is_low_stock is True
    mi.prepared_qty = 6
    mi.save()
    assert mi.is_low_stock is False


def test_is_low_stock_default_threshold_5_when_none(restaurant, category):
    from apps.menu.models import MenuItem

    mi = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="X",
        price=Decimal("10"),
        is_batch_cooking=True, prepared_qty=4, low_stock_threshold=None,
    )
    # Без явного threshold — дефолт 5
    assert mi.is_low_stock is True


# -------- Serializer / API --------


def test_create_menu_item_with_extended_fields_via_api(
    api_client, restaurant, cashier, category
):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/items/",
        {
            "category": category.id,
            "name": "Шашлык бараний",
            "price": "25.00",
            "kind": "grill",
            "cogs": "12.00",
            "cook_time_min": 20,
            "unit": "g",
            "unit_size": 100,
            "sale_step": 50,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    # POST /menu/items/ возвращает плоский ответ (не wrapped в {"data": ...}).
    data = body.get("data") if "data" in body else body
    assert data["kind"] == "grill"
    assert data["unit"] == "g"
    assert data["unit_size"] == 100
    assert data["sale_step"] == 50
    assert data["cook_time_min"] == 20


def test_serializer_rejects_purchased_and_batch_combo(
    api_client, restaurant, cashier, category
):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/items/",
        {
            "category": category.id,
            "name": "Бракованное",
            "price": "10",
            "is_purchased": True,
            "is_batch_cooking": True,
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400
    body = resp.json()
    # DRF validation error in error envelope or non_field_errors — ищем подстроку
    assert "покупным" in str(body).lower() or "validation" in str(body).lower()


def test_list_includes_is_low_stock_flag(
    api_client, restaurant, cashier, category
):
    from apps.menu.models import MenuItem

    MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов",
        price=Decimal("45"),
        is_batch_cooking=True, prepared_qty=2, low_stock_threshold=5,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/menu/items/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    items = resp.json()["data"]
    plov = next(it for it in items if it["name"] == "Плов")
    assert plov["is_low_stock"] is True
    assert plov["prepared_qty"] == 2


# -------- Cross-restaurant isolation (sanity) --------


def test_kind_filtering_safety(restaurant, category):
    """Запретов на kind нет, но проверяем что enum принимает все 7 значений."""
    from apps.menu.models import MenuItem, MenuItemKind

    for k in MenuItemKind.values:
        mi = MenuItem.objects.create(
            restaurant=restaurant, category=category,
            name=f"Test-{k}", price=Decimal("1"),
            kind=k,
        )
        assert mi.kind == k
