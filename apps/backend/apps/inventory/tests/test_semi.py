"""Phase 7B: SemiFinishedType + Recipe + produce_semi."""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, user):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def beef(restaurant):
    """Говядина — сырьё для фарша."""
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Говядина", unit="kg",
    )


@pytest.fixture
def onion(restaurant):
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Лук", unit="kg",
    )


@pytest.fixture
def salt(restaurant):
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Соль", unit="kg",
    )


@pytest.fixture
def farsh(restaurant, beef, onion, salt, cashier):
    """Фарш говяжий: рецепт на 1 кг готового фарша + yield 80%.

    На 1 кг готового нужно (с учётом yield=80%, делим на 0.8):
      Говядина: 0.8 кг сырого × 1/0.8 = 1.0 кг (per_output=0.8)
      Лук:       0.1 кг × 1/0.8 = 0.125 кг (per_output=0.1)
      Соль:      0.015 кг × 1/0.8 = 0.01875 кг (per_output=0.015)
    """
    from apps.inventory.models import SemiFinishedRecipeLine, SemiFinishedType
    from apps.inventory.services import record_movement

    semi = SemiFinishedType.objects.create(
        restaurant=restaurant, name="Фарш говяжий", output_unit="kg",
        yield_percent=Decimal("80"),
    )
    SemiFinishedRecipeLine.objects.create(
        semi_type=semi, ingredient=beef, qty_per_output=Decimal("0.8"),
    )
    SemiFinishedRecipeLine.objects.create(
        semi_type=semi, ingredient=onion, qty_per_output=Decimal("0.1"),
    )
    SemiFinishedRecipeLine.objects.create(
        semi_type=semi, ingredient=salt, qty_per_output=Decimal("0.015"),
    )
    # Наполняем склад
    record_movement(
        ingredient=beef, kind="purchase", qty_delta=10,
        unit_cost=Decimal("100"), user=cashier,
    )
    record_movement(
        ingredient=onion, kind="purchase", qty_delta=5,
        unit_cost=Decimal("20"), user=cashier,
    )
    record_movement(
        ingredient=salt, kind="purchase", qty_delta=2,
        unit_cost=Decimal("5"), user=cashier,
    )
    return semi


# -------- produce_semi: математика + списания --------


def test_produce_semi_consumes_ingredients_with_yield(
    farsh, beef, onion, salt, cashier,
):
    """Варим 1 кг фарша при yield=80% → расход 1.25 × per_output."""
    from apps.inventory.services import produce_semi

    mv = produce_semi(semi_type=farsh, qty=Decimal("1"), user=cashier)
    assert mv.qty_delta == Decimal("1.000")

    # Говядина: 1 × 0.8 / 0.8 = 1.0
    assert beef.current_qty == Decimal("9.000")
    # Лук: 1 × 0.1 / 0.8 = 0.125
    assert onion.current_qty == Decimal("4.875")
    # Соль: 1 × 0.015 / 0.8 = 0.01875 → округлено до 3 знаков
    assert abs(salt.current_qty - Decimal("1.98125")) < Decimal("0.001")
    # П/ф появился
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("1.000")


def test_produce_semi_calculates_unit_cost(
    farsh, beef, onion, salt, cashier,
):
    """unit_cost партии = (Σ component_qty × component_cost) / qty."""
    from apps.inventory.services import produce_semi

    mv = produce_semi(semi_type=farsh, qty=Decimal("2"), user=cashier)
    # Расход на 2 кг при yield=80%:
    #   Говядина 2 × 0.8 / 0.8 = 2.0 × 100 = 200
    #   Лук      2 × 0.1 / 0.8 = 0.25 × 20 = 5
    #   Соль     2 × 0.015 / 0.8 = 0.0375 × 5 = 0.1875
    # batch_cost ≈ 205.1875, unit_cost = 102.5938
    assert abs(mv.unit_cost - Decimal("102.59")) < Decimal("0.10")
    farsh.refresh_from_db()
    assert abs(farsh.avg_cost_per_unit - Decimal("102.59")) < Decimal("0.10")


def test_produce_semi_updates_avg_cost_weighted(
    farsh, beef, onion, salt, cashier,
):
    """Две партии с разной себестоимостью → weighted average."""
    from apps.inventory.services import produce_semi, record_movement

    produce_semi(semi_type=farsh, qty=Decimal("1"), user=cashier)
    farsh.refresh_from_db()
    first_cost = farsh.avg_cost_per_unit
    # Допускаем новую закупку дороже
    record_movement(
        ingredient=beef, kind="purchase", qty_delta=Decimal("10"),
        unit_cost=Decimal("200"), user=cashier,
    )
    beef.refresh_from_db()
    produce_semi(semi_type=farsh, qty=Decimal("1"), user=cashier)
    farsh.refresh_from_db()
    # avg должен поднялся (но не до уровня второй партии — это weighted)
    assert farsh.avg_cost_per_unit > first_cost


def test_produce_semi_insufficient_stock(farsh, beef, cashier):
    """Не хватает ингредиента → атомарный откат."""
    from apps.inventory.services import produce_semi
    from common.exceptions import BusinessError

    # Истратим говядину: останется только 2 кг
    from apps.inventory.services import record_movement
    record_movement(ingredient=beef, kind="waste", qty_delta=Decimal("-8"), user=cashier)
    beef.refresh_from_db()
    assert beef.current_qty == Decimal("2.000")

    # Попробуем сварить 5 кг фарша — нужно 6.25 кг говядины (yield 80%)
    with pytest.raises(BusinessError) as exc:
        produce_semi(semi_type=farsh, qty=Decimal("5"), user=cashier)
    assert exc.value.code == "INSUFFICIENT_STOCK"
    # Остатки НЕ изменились — атомарность
    beef.refresh_from_db()
    assert beef.current_qty == Decimal("2.000")
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("0")


def test_produce_semi_empty_recipe(restaurant, cashier):
    """П/ф без рецепта → 422 EMPTY_RECIPE."""
    from apps.inventory.models import SemiFinishedType
    from apps.inventory.services import produce_semi
    from common.exceptions import BusinessError

    semi = SemiFinishedType.objects.create(
        restaurant=restaurant, name="Тесто пустое", output_unit="kg",
    )
    with pytest.raises(BusinessError) as exc:
        produce_semi(semi_type=semi, qty=Decimal("1"), user=cashier)
    assert exc.value.code == "EMPTY_RECIPE"


def test_produce_semi_zero_qty(farsh, cashier):
    from apps.inventory.services import produce_semi
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError):
        produce_semi(semi_type=farsh, qty=Decimal("0"), user=cashier)


# -------- nested semi: п/ф из п/ф --------


def test_produce_semi_using_nested_semi(restaurant, farsh, cashier):
    """«Манты» использует Фарш (п/ф) как компонент."""
    from apps.inventory.models import SemiFinishedRecipeLine, SemiFinishedType
    from apps.inventory.services import produce_semi

    # Сначала наработаем фарша
    produce_semi(semi_type=farsh, qty=Decimal("2"), user=cashier)
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("2.000")

    # Создаём «Манты-смесь» — на 1 кг идёт 0.5 кг фарша
    manty = SemiFinishedType.objects.create(
        restaurant=restaurant, name="Манты-смесь", output_unit="kg",
    )
    SemiFinishedRecipeLine.objects.create(
        semi_type=manty, nested_semi=farsh, qty_per_output=Decimal("0.5"),
    )
    # Варим 1 кг манты-смеси
    produce_semi(semi_type=manty, qty=Decimal("1"), user=cashier)
    # Фарш списан: 2 - 0.5 = 1.5
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("1.500")
    # Манты-смесь появилась
    manty.refresh_from_db()
    assert manty.current_qty == Decimal("1.000")


# -------- waste / inventory_correct --------


def test_semi_waste(farsh, cashier):
    from apps.inventory.services import produce_semi, record_semi_movement

    produce_semi(semi_type=farsh, qty=Decimal("3"), user=cashier)
    record_semi_movement(
        semi_type=farsh, kind="waste", qty_delta=Decimal("-0.5"), user=cashier,
    )
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("2.500")


def test_semi_inventory_correct(farsh, cashier):
    from apps.inventory.services import produce_semi, record_semi_movement

    produce_semi(semi_type=farsh, qty=Decimal("5"), user=cashier)
    # Реально насчитали 4.8 — списываем 0.2
    record_semi_movement(
        semi_type=farsh, kind="inventory_correct",
        qty_delta=Decimal("-0.2"), user=cashier,
    )
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("4.800")


# -------- API --------


def test_create_semi_with_recipe(api_client, cashier, beef, onion):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/inventory/semi/",
        {
            "name": "Тесто",
            "output_unit": "kg",
            "yield_percent": "95",
            "recipe_lines": [
                {"ingredient": beef.id, "qty_per_output": "0.5"},
                {"ingredient": onion.id, "qty_per_output": "0.05"},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    data = body.get("data") if "data" in body else body
    assert data["name"] == "Тесто"
    assert len(data["recipe_lines"]) == 2


def test_api_produce_action(api_client, cashier, farsh, beef):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/inventory/semi/{farsh.id}/produce/",
        {"qty": "1", "reason": "Утренняя варка"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("1.000")
    beef.refresh_from_db()
    assert beef.current_qty == Decimal("9.000")


def test_api_produce_insufficient_stock(api_client, cashier, farsh, beef):
    """Через API недостаток ингредиентов → 422."""
    from apps.inventory.services import record_movement

    record_movement(ingredient=beef, kind="waste", qty_delta=-9, user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/inventory/semi/{farsh.id}/produce/",
        {"qty": "5"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_STOCK"


def test_api_movements_history(api_client, cashier, farsh):
    from apps.inventory.services import produce_semi

    produce_semi(semi_type=farsh, qty=Decimal("1"), user=cashier)
    produce_semi(semi_type=farsh, qty=Decimal("2"), user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        f"/api/v1/inventory/semi/{farsh.id}/movements/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2


def test_api_recipe_one_component_constraint(
    api_client, cashier, beef, restaurant,
):
    """Должен быть указан ingredient ИЛИ nested_semi, не оба и не ни один."""
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/inventory/semi/",
        {
            "name": "Бракованный",
            "output_unit": "kg",
            "recipe_lines": [
                # ничего не выбрано
                {"qty_per_output": "1"},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400
