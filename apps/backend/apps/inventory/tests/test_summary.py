"""Phase 8D — KPI-агрегат /inventory/ingredients/summary/."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def stock(restaurant, cashier):
    from apps.inventory.models import Ingredient, StockMovementKind
    from apps.inventory.services import record_movement

    beef = Ingredient.objects.create(
        restaurant=restaurant, name="Говядина", unit="kg",
        avg_cost_per_unit=Decimal("100.00"), is_food=True,
        low_stock_threshold=Decimal("0.5"),
    )
    salt = Ingredient.objects.create(
        restaurant=restaurant, name="Соль", unit="g",
        avg_cost_per_unit=Decimal("0.01"), is_food=True,
        low_stock_threshold=Decimal("100"),
    )
    potato = Ingredient.objects.create(
        restaurant=restaurant, name="Картофель", unit="kg",
        avg_cost_per_unit=Decimal("8.00"), is_food=True,
    )
    old = Ingredient.objects.create(
        restaurant=restaurant, name="Старый", unit="kg",
        avg_cost_per_unit=Decimal("0"), is_food=True, is_active=False,
    )
    towels = Ingredient.objects.create(
        restaurant=restaurant, name="Полотенца", unit="pack",
        avg_cost_per_unit=Decimal("15.00"), is_food=False,
    )

    # Beef: 2 кг — в наличии, не низкий
    record_movement(ingredient=beef, kind=StockMovementKind.PURCHASE,
                    qty_delta=Decimal("2"), unit_cost=Decimal("100"), user=cashier)
    # Salt: 50 г — низкий (порог 100)
    record_movement(ingredient=salt, kind=StockMovementKind.PURCHASE,
                    qty_delta=Decimal("50"), unit_cost=Decimal("0.01"), user=cashier)
    # Картофель: 0 (нет движений) — out_of_stock
    # Towels: 5 уп
    record_movement(ingredient=towels, kind=StockMovementKind.PURCHASE,
                    qty_delta=Decimal("5"), unit_cost=Decimal("15"), user=cashier)
    return {"beef": beef, "salt": salt, "potato": potato, "old": old, "towels": towels}


def test_summary_for_food(api_client, restaurant, cashier, stock):
    pin = _pin(api_client, cashier)
    resp = api_client.get("/api/v1/inventory/ingredients/summary/?kind=food",
                          HTTP_AUTHORIZATION=f"PIN {pin}")
    assert resp.status_code == 200, resp.content
    d = resp.json()["data"]
    # Всего food: 4 (beef, salt, potato, old)
    assert d["total"] == 4
    assert d["inactive"] == 1  # old
    assert d["in_stock"] == 2  # beef + salt (salt > 0)
    assert d["out_of_stock"] == 1  # potato
    assert d["low_stock"] == 1  # salt
    # total_value = beef(2 × 100) + salt(50 × 0.01) = 200 + 0.50 = 200.50
    assert d["total_value"] == "200.50"


def test_summary_for_household(api_client, restaurant, cashier, stock):
    pin = _pin(api_client, cashier)
    resp = api_client.get("/api/v1/inventory/ingredients/summary/?kind=household",
                          HTTP_AUTHORIZATION=f"PIN {pin}")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["total"] == 1
    assert d["in_stock"] == 1
    # 5 уп × 15 = 75.00
    assert d["total_value"] == "75.00"


def test_summary_empty(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.get("/api/v1/inventory/ingredients/summary/?kind=food",
                          HTTP_AUTHORIZATION=f"PIN {pin}")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["total"] == 0
    assert d["total_value"] == "0.00"
