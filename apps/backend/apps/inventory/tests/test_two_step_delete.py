"""Phase 8E — двухшаговое удаление ингредиентов и полуфабрикатов."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


def test_first_delete_with_movements_soft_deletes(api_client, restaurant, cashier):
    from apps.inventory.models import Ingredient, StockMovementKind
    from apps.inventory.services import record_movement
    ing = Ingredient.objects.create(
        restaurant=restaurant, name="Соль", unit="g",
        avg_cost_per_unit=Decimal("0.01"), is_food=True,
    )
    record_movement(
        ingredient=ing, kind=StockMovementKind.PURCHASE,
        qty_delta=Decimal("100"), unit_cost=Decimal("0.01"), user=cashier,
    )
    pin = _pin(api_client, cashier)

    resp = api_client.delete(
        f"/api/v1/inventory/ingredients/{ing.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    ing.refresh_from_db()
    assert ing.is_active is False  # soft-delete
    # запись осталась в БД
    assert Ingredient.objects.filter(id=ing.id).exists()


def test_second_delete_on_inactive_hard_deletes(api_client, restaurant, cashier):
    from apps.inventory.models import Ingredient, StockMovementKind
    from apps.inventory.services import record_movement
    ing = Ingredient.objects.create(
        restaurant=restaurant, name="Старая соль", unit="g",
        avg_cost_per_unit=Decimal("0.01"), is_food=True,
        is_active=False,  # уже отключён
    )
    record_movement(
        ingredient=ing, kind=StockMovementKind.PURCHASE,
        qty_delta=Decimal("10"), unit_cost=Decimal("0.01"), user=cashier,
    )
    pin = _pin(api_client, cashier)

    ing_id = ing.id
    resp = api_client.delete(
        f"/api/v1/inventory/ingredients/{ing_id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 204
    # физически удалён + cascade его движений
    assert not Ingredient.objects.filter(id=ing_id).exists()


def test_delete_protected_when_used_in_techcard(api_client, restaurant, cashier):
    """Если ingredient используется в техкарте — нельзя удалить даже после soft-delete."""
    from apps.inventory.models import Ingredient
    from apps.menu.models import Category, MenuItem, MenuItemTechCardLine
    ing = Ingredient.objects.create(
        restaurant=restaurant, name="Мука", unit="kg",
        avg_cost_per_unit=Decimal("5"), is_food=True, is_active=False,
    )
    cat = Category.objects.create(restaurant=restaurant, name="Тест", sort_order=1)
    mi = MenuItem.objects.create(
        restaurant=restaurant, category=cat,
        name="Хлеб", price=Decimal("3.00"),
    )
    MenuItemTechCardLine.objects.create(
        menu_item=mi, ingredient=ing, qty_per_unit=Decimal("0.2"),
    )
    pin = _pin(api_client, cashier)

    resp = api_client.delete(
        f"/api/v1/inventory/ingredients/{ing.id}/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "PROTECTED"
    # запись цела
    assert Ingredient.objects.filter(id=ing.id).exists()
