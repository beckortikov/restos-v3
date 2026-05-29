"""Phase 8D: авто-стоп блюд при нехватке ингредиентов + override."""
import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def beef(restaurant):
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Говядина", unit="kg",
        avg_cost_per_unit=Decimal("60.00"),
    )


@pytest.fixture
def plov_with_techcard(menu_items, beef):
    """«Плов» с техкартой 0.2 кг говядины на 1 порцию."""
    from apps.menu.models import MenuItemTechCardLine
    plov = menu_items["plov"]
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )
    return plov


def _purchase(beef, qty: Decimal, user=None):
    from apps.inventory.models import StockMovementKind
    from apps.inventory.services import record_movement
    return record_movement(
        ingredient=beef, kind=StockMovementKind.PURCHASE,
        qty_delta=qty, unit_cost=Decimal("60.00"), user=user,
    )


def _consume(beef, qty: Decimal, user=None):
    from apps.inventory.models import StockMovementKind
    from apps.inventory.services import record_movement
    return record_movement(
        ingredient=beef, kind=StockMovementKind.CONSUME,
        qty_delta=-qty, reason="test consume", user=user,
    )


def test_autostop_triggers_when_stock_drops_below_one_portion(
    restaurant, plov_with_techcard, beef, cashier,
):
    # Приходуем 0.5 кг — хватит на 2 порции (по 0.2 кг)
    _purchase(beef, Decimal("0.5"), user=cashier)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is True
    assert plov_with_techcard.auto_stopped is False

    # Списываем 0.4 кг — остаётся 0.1, на 1 порцию (0.2) уже не хватает
    _consume(beef, Decimal("0.4"), user=cashier)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is False
    assert plov_with_techcard.auto_stopped is True
    assert "Говядина" in plov_with_techcard.stop_reason


def test_autostop_restores_on_purchase(
    restaurant, plov_with_techcard, beef, cashier,
):
    _purchase(beef, Decimal("0.1"), user=cashier)  # < 0.2 → стоп
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.auto_stopped is True

    _purchase(beef, Decimal("1.0"), user=cashier)  # теперь 1.1 кг
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is True
    assert plov_with_techcard.auto_stopped is False
    assert plov_with_techcard.stop_reason == ""


def test_manual_stop_not_cleared_by_autostop_logic(
    restaurant, plov_with_techcard, beef, cashier,
):
    # Ставим ручной стоп
    plov_with_techcard.is_available = False
    plov_with_techcard.stop_reason = "Сами решили снять"
    plov_with_techcard.auto_stopped = False
    plov_with_techcard.save()

    # Приходуем — авто-логика не должна вернуть в продажу
    _purchase(beef, Decimal("10.0"), user=cashier)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is False
    assert plov_with_techcard.stop_reason == "Сами решили снять"
    assert plov_with_techcard.auto_stopped is False


def test_allow_oversell_skips_autostop(
    restaurant, plov_with_techcard, beef, cashier,
):
    plov_with_techcard.allow_oversell = True
    plov_with_techcard.save()

    _purchase(beef, Decimal("0.05"), user=cashier)  # совсем мало
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is True
    assert plov_with_techcard.auto_stopped is False


def test_auto_consume_false_skips_autostop(
    restaurant, plov_with_techcard, beef, cashier,
):
    plov_with_techcard.auto_consume = False
    plov_with_techcard.save()

    _purchase(beef, Decimal("0.05"), user=cashier)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is True
    assert plov_with_techcard.auto_stopped is False


def test_allow_oversell_endpoint(
    api_client, restaurant, cashier, plov_with_techcard, beef,
):
    # Загоняем в авто-стоп
    _purchase(beef, Decimal("0.05"), user=cashier)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.auto_stopped is True

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{plov_with_techcard.id}/allow_oversell/",
        {"enabled": True}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["allow_oversell"] is True
    assert data["is_available"] is True
    assert data["auto_stopped"] is False


def test_toggle_tech_card_endpoint(
    api_client, restaurant, cashier, plov_with_techcard,
):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/menu/items/{plov_with_techcard.id}/toggle_tech_card/",
        {"enabled": False}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["auto_consume"] is False


def test_auto_stopped_list_endpoint(
    api_client, restaurant, cashier, plov_with_techcard, beef,
):
    _purchase(beef, Decimal("0.05"), user=cashier)
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/menu/items/auto_stopped/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(d["id"] == plov_with_techcard.id for d in data)


def test_order_blocked_when_autostopped(
    api_client, restaurant, cashier, plov_with_techcard, beef, table,
):
    # Загоняем в авто-стоп
    _purchase(beef, Decimal("0.05"), user=cashier)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.auto_stopped is True

    from apps.orders.services import create_order
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc_info:
        create_order(
            restaurant=restaurant, waiter=cashier,
            order_type="hall", table_id=table.id,
            items_data=[{"menu_item_id": plov_with_techcard.id, "qty": 1}],
            idempotency_key=str(uuid.uuid4()),
        )
    assert exc_info.value.code == "STOCK_INSUFFICIENT"


def test_order_allowed_when_oversell_on(
    api_client, restaurant, cashier, plov_with_techcard, beef, table,
):
    _purchase(beef, Decimal("0.05"), user=cashier)
    plov_with_techcard.allow_oversell = True
    plov_with_techcard.save()
    # reconcile вручную (allow_oversell на модели не триггерит, нужно либо
    # вызвать endpoint, либо явно)
    from apps.menu.services_autostop import reconcile_menu_item_stop
    reconcile_menu_item_stop(plov_with_techcard)
    plov_with_techcard.refresh_from_db()
    assert plov_with_techcard.is_available is True

    from apps.orders.services import create_order
    order = create_order(
        restaurant=restaurant, waiter=cashier,
        order_type="hall", table_id=table.id,
        items_data=[{"menu_item_id": plov_with_techcard.id, "qty": 1}],
        idempotency_key=str(uuid.uuid4()),
    )
    assert order.id > 0
