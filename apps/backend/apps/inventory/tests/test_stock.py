"""Phase 7A: Ingredient + StockMovement event-stream + CRUD."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, user):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def ing(restaurant):
    from apps.inventory.models import Ingredient

    return Ingredient.objects.create(
        restaurant=restaurant, name="Говядина", unit="kg",
        low_stock_threshold=Decimal("2"),
    )


# -------- Model: current_qty as event-sum --------


def test_current_qty_is_sum_of_movements(ing, cashier):
    from apps.inventory.services import record_movement

    assert ing.current_qty == Decimal("0")
    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    assert ing.current_qty == Decimal("10.000")
    record_movement(ingredient=ing, kind="purchase", qty_delta=5, user=cashier)
    assert ing.current_qty == Decimal("15.000")
    record_movement(ingredient=ing, kind="waste", qty_delta=-2, user=cashier)
    assert ing.current_qty == Decimal("13.000")


def test_is_low_stock_uses_threshold(ing, cashier):
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    assert ing.is_low_stock is False
    record_movement(ingredient=ing, kind="waste", qty_delta=-9, user=cashier)
    # 10 - 9 = 1, threshold = 2 → low
    assert ing.is_low_stock is True


# -------- Service: sign validation --------


def test_purchase_must_be_positive(ing, cashier):
    from apps.inventory.services import record_movement
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        record_movement(ingredient=ing, kind="purchase", qty_delta=-5, user=cashier)
    assert exc.value.code == "INVALID_SIGN"


def test_consume_must_be_negative(ing, cashier):
    from apps.inventory.services import record_movement
    from common.exceptions import BusinessError

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    with pytest.raises(BusinessError) as exc:
        record_movement(ingredient=ing, kind="consume", qty_delta=5, user=cashier)
    assert exc.value.code == "INVALID_SIGN"


def test_zero_qty_rejected(ing, cashier):
    from apps.inventory.services import record_movement
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        record_movement(ingredient=ing, kind="purchase", qty_delta=0, user=cashier)
    assert "0" in exc.value.message


def test_inventory_correct_accepts_any_sign(ing, cashier):
    """inventory_correct может быть положительным (нашли) или отрицательным (списали)."""
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    # Минус — недостача
    record_movement(ingredient=ing, kind="inventory_correct", qty_delta=-1, user=cashier)
    # Плюс — пересчитали, нашли больше
    record_movement(ingredient=ing, kind="inventory_correct", qty_delta=2, user=cashier)
    assert ing.current_qty == Decimal("11.000")


# -------- Service: prevent negative stock --------


def test_consume_more_than_have_rejected(ing, cashier):
    from apps.inventory.services import record_movement
    from common.exceptions import BusinessError

    record_movement(ingredient=ing, kind="purchase", qty_delta=5, user=cashier)
    with pytest.raises(BusinessError) as exc:
        record_movement(ingredient=ing, kind="consume", qty_delta=-10, user=cashier)
    assert exc.value.code == "INSUFFICIENT_STOCK"


def test_negative_stock_allowed_when_setting_disabled(ing, cashier, settings):
    from apps.inventory.services import record_movement

    settings.INVENTORY_PREVENT_NEGATIVE = False
    record_movement(ingredient=ing, kind="consume", qty_delta=-10, user=cashier)
    assert ing.current_qty == Decimal("-10.000")


# -------- Service: weighted average cost --------


def test_avg_cost_weighted_after_purchases(ing, cashier):
    from apps.inventory.services import record_movement

    # Первая партия: 10 кг по 100 → avg = 100
    record_movement(
        ingredient=ing, kind="purchase",
        qty_delta=10, unit_cost=Decimal("100"), user=cashier,
    )
    ing.refresh_from_db()
    assert ing.avg_cost_per_unit == Decimal("100.0000")

    # Вторая партия: 10 кг по 200 → avg = 150
    record_movement(
        ingredient=ing, kind="purchase",
        qty_delta=10, unit_cost=Decimal("200"), user=cashier,
    )
    ing.refresh_from_db()
    assert ing.avg_cost_per_unit == Decimal("150.0000")


# -------- API: CRUD --------


def test_create_ingredient_via_api(api_client, cashier, restaurant):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/inventory/ingredients/",
        {
            "name": "Мука",
            "unit": "kg",
            "low_stock_threshold": "5",
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    from apps.inventory.models import Ingredient
    assert Ingredient.objects.filter(name="Мука", restaurant=restaurant).exists()


def test_list_ingredients_returns_current_qty(api_client, cashier, ing):
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=7, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/inventory/ingredients/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    item = data[0]
    assert Decimal(item["current_qty"]) == Decimal("7.000")
    assert item["is_low_stock"] is False


def test_purchase_action_records_movement(api_client, cashier, ing):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/inventory/ingredients/{ing.id}/purchase/",
        {"qty": "10", "unit_cost": "85.50", "reason": "Накладная #4521"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    ing.refresh_from_db()
    assert ing.current_qty == Decimal("10.000")
    assert ing.avg_cost_per_unit == Decimal("85.5000")


def test_waste_action(api_client, cashier, ing):
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/inventory/ingredients/{ing.id}/waste/",
        {"qty": "3", "reason": "Истёк срок"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201
    ing.refresh_from_db()
    assert ing.current_qty == Decimal("7.000")


def test_inventory_correct_aligns_stock(api_client, cashier, ing):
    from apps.inventory.services import record_movement

    # По данным БД у нас 10, по факту насчитали 8
    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/inventory/ingredients/{ing.id}/inventory_correct/",
        {"actual_qty": "8", "reason": "Подсчёт за неделю"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201
    ing.refresh_from_db()
    assert ing.current_qty == Decimal("8.000")


def test_inventory_correct_no_change_when_matches(api_client, cashier, ing):
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/inventory/ingredients/{ing.id}/inventory_correct/",
        {"actual_qty": "10"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    # Никаких новых движений
    assert ing.movements.count() == 1


def test_movements_history(api_client, cashier, ing):
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    record_movement(ingredient=ing, kind="waste", qty_delta=-2, user=cashier)
    record_movement(ingredient=ing, kind="purchase", qty_delta=5, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        f"/api/v1/inventory/ingredients/{ing.id}/movements/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 3


def test_destroy_soft_deletes_when_has_history(api_client, cashier, ing):
    """Удаление ингредиента с историей движений → soft-delete (is_active=False)."""
    from apps.inventory.models import Ingredient
    from apps.inventory.services import record_movement

    record_movement(ingredient=ing, kind="purchase", qty_delta=10, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/inventory/ingredients/{ing.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    # Запись осталась, но неактивна
    ing.refresh_from_db()
    assert ing.is_active is False
    assert Ingredient.objects.filter(id=ing.id).exists()


def test_destroy_hard_when_no_movements(api_client, cashier, ing):
    """Без истории движений — можно физически удалить."""
    from apps.inventory.models import Ingredient

    pin = _pin(api_client, cashier)
    resp = api_client.delete(
        f"/api/v1/inventory/ingredients/{ing.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    assert not Ingredient.objects.filter(id=ing.id).exists()


def test_low_stock_helper(restaurant, cashier):
    from apps.inventory.models import Ingredient
    from apps.inventory.services import (
        get_low_stock_ingredients,
        record_movement,
    )

    a = Ingredient.objects.create(
        restaurant=restaurant, name="Соль", unit="g",
        low_stock_threshold=Decimal("100"),
    )
    b = Ingredient.objects.create(
        restaurant=restaurant, name="Сахар", unit="g",
        low_stock_threshold=Decimal("100"),
    )
    record_movement(ingredient=a, kind="purchase", qty_delta=50, user=cashier)   # low
    record_movement(ingredient=b, kind="purchase", qty_delta=500, user=cashier)  # ok

    low = get_low_stock_ingredients(restaurant)
    names = {i.name for i in low}
    assert "Соль" in names
    assert "Сахар" not in names


def test_cross_restaurant_isolation(api_client, cashier, restaurant):
    """Кассир видит только ингредиенты своего ресторана."""
    from apps.inventory.models import Ingredient
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Чужой", currency="TJS")
    Ingredient.objects.create(restaurant=other, name="Чужая мука", unit="kg")

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/inventory/ingredients/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    names = [i["name"] for i in resp.json()["data"]]
    assert "Чужая мука" not in names
