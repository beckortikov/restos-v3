"""Модификаторы блюд: каталог + интеграция в Order + чек."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, user):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Горячее")


@pytest.fixture
def steak(restaurant, category):
    from apps.menu.models import MenuItem

    return MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Стейк",
        price=Decimal("100.00"),
    )


@pytest.fixture
def doneness_group(restaurant, steak):
    """Required single-select группа «Прожарка»."""
    from apps.menu.models import Modifier, ModifierGroup

    g = ModifierGroup.objects.create(
        restaurant=restaurant, name="Прожарка",
        min_select=1, max_select=1, is_required=True, sort_order=1,
    )
    Modifier.objects.create(group=g, name="Medium", price_delta=Decimal("0"))
    Modifier.objects.create(group=g, name="Well-done", price_delta=Decimal("0"))
    steak.modifier_groups.add(g)
    return g


@pytest.fixture
def sauces_group(restaurant, steak):
    """Optional multi-select группа «Соусы»."""
    from apps.menu.models import Modifier, ModifierGroup

    g = ModifierGroup.objects.create(
        restaurant=restaurant, name="Соусы",
        min_select=0, max_select=2, is_required=False, sort_order=2,
    )
    Modifier.objects.create(group=g, name="Чесночный", price_delta=Decimal("3"))
    Modifier.objects.create(group=g, name="Острый", price_delta=Decimal("2"))
    Modifier.objects.create(
        group=g, name="Без соли", price_delta=Decimal("-1"),
    )
    steak.modifier_groups.add(g)
    return g


# -------- Каталог --------


def test_modifier_group_crud_endpoint(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/modifier-groups/",
        {
            "name": "Размер пиццы",
            "min_select": 1, "max_select": 1, "is_required": True,
            "modifiers": [
                {"name": "30см", "price_delta": "0", "sort_order": 1},
                {"name": "35см", "price_delta": "10", "sort_order": 2},
                {"name": "45см", "price_delta": "25", "sort_order": 3},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["name"] == "Размер пиццы"
    assert len(data["modifiers"]) == 3

    # GET
    resp_list = api_client.get(
        "/api/v1/menu/modifier-groups/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp_list.status_code == 200
    assert len(resp_list.json()["data"]) == 1


def test_modifier_group_min_le_max_validation(
    api_client, restaurant, cashier
):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/menu/modifier-groups/",
        {"name": "X", "min_select": 3, "max_select": 1},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 400


def test_modifier_group_isolation_per_restaurant(
    api_client, restaurant, cashier, doneness_group
):
    """Группа другого ресторана не видна."""
    from apps.menu.models import ModifierGroup
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Другой", currency="TJS")
    ModifierGroup.objects.create(
        restaurant=other, name="Чужая группа",
        min_select=0, max_select=1,
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/menu/modifier-groups/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    names = [g["name"] for g in resp.json()["data"]]
    assert "Чужая группа" not in names
    assert "Прожарка" in names


# -------- Order integration --------


def test_create_order_with_modifiers(
    restaurant, waiter, category, steak, doneness_group, sauces_group,
):
    from apps.orders.services import create_order

    medium = doneness_group.modifiers.get(name="Medium")
    spicy = sauces_group.modifiers.get(name="Острый")
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": steak.id, "qty": 2,
            "modifier_ids": [medium.id, spicy.id],
        }],
        idempotency_key=uuid4(),
    )
    item = o.items.first()
    # 2 модификатора прикреплены
    assert item.modifiers.count() == 2
    # subtotal = (100 + 0 + 2) * 2 = 204
    assert item.subtotal == Decimal("204.00")


def test_required_modifier_missing_raises(
    restaurant, waiter, steak, doneness_group,
):
    from apps.orders.services import create_order
    from common.exceptions import BusinessError

    with pytest.raises(BusinessError) as exc:
        create_order(
            restaurant=restaurant, waiter=waiter,
            order_type="takeaway", guests_count=1,
            items_data=[{"menu_item_id": steak.id, "qty": 1}],  # без modifier_ids
            idempotency_key=uuid4(),
        )
    assert exc.value.code == "MODIFIER_REQUIRED"


def test_modifier_too_many_raises(
    restaurant, waiter, steak, doneness_group, sauces_group,
):
    from apps.orders.services import create_order
    from common.exceptions import BusinessError

    medium = doneness_group.modifiers.get(name="Medium")
    sauces = list(sauces_group.modifiers.all())
    # max_select=2, передаём 3
    with pytest.raises(BusinessError) as exc:
        create_order(
            restaurant=restaurant, waiter=waiter,
            order_type="takeaway", guests_count=1,
            items_data=[{
                "menu_item_id": steak.id, "qty": 1,
                "modifier_ids": [medium.id] + [s.id for s in sauces],
            }],
            idempotency_key=uuid4(),
        )
    assert exc.value.code == "MODIFIER_TOO_MANY"


def test_modifier_not_belonging_to_item_raises(
    restaurant, waiter, category, steak, doneness_group,
):
    """Модификатор из группы, не привязанной к блюду — отклоняется."""
    from apps.menu.models import MenuItem, Modifier, ModifierGroup
    from apps.orders.services import create_order
    from common.exceptions import BusinessError

    other_group = ModifierGroup.objects.create(
        restaurant=restaurant, name="Чужая",
        min_select=0, max_select=1,
    )
    other_mod = Modifier.objects.create(
        group=other_group, name="X", price_delta=Decimal("0"),
    )
    medium = doneness_group.modifiers.get(name="Medium")

    with pytest.raises(BusinessError) as exc:
        create_order(
            restaurant=restaurant, waiter=waiter,
            order_type="takeaway", guests_count=1,
            items_data=[{
                "menu_item_id": steak.id, "qty": 1,
                "modifier_ids": [medium.id, other_mod.id],
            }],
            idempotency_key=uuid4(),
        )
    assert exc.value.code == "MODIFIER_NOT_ALLOWED"


def test_modifiers_are_snapshot(
    restaurant, waiter, steak, doneness_group, sauces_group,
):
    """После переименования/изменения цены — snapshot в OrderItem не меняется."""
    from apps.orders.services import create_order

    medium = doneness_group.modifiers.get(name="Medium")
    spicy = sauces_group.modifiers.get(name="Острый")
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [medium.id, spicy.id],
        }],
        idempotency_key=uuid4(),
    )
    spicy.name = "ИЗМЕНЕНО"
    spicy.price_delta = Decimal("999")
    spicy.save()

    item = o.items.first()
    snap = item.modifiers.get(modifier=spicy)
    assert snap.name_at_order == "Острый"
    assert snap.price_delta_at_order == Decimal("2.00")


def test_receipt_payload_contains_modifiers(
    restaurant, waiter, cashier, steak, doneness_group, sauces_group,
):
    from apps.orders.services import close_order, create_order
    from apps.printing.services import build_receipt_payload

    medium = doneness_group.modifiers.get(name="Medium")
    garlic = sauces_group.modifiers.get(name="Чесночный")
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [medium.id, garlic.id],
        }],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    payload = build_receipt_payload(o)
    item = payload["items"][0]
    names = [m["name"] for m in item["modifiers"]]
    assert "Medium" in names
    assert "Чесночный" in names


def test_receipt_text_renders_modifiers(
    restaurant, waiter, cashier, steak, doneness_group, sauces_group,
):
    from apps.orders.services import close_order, create_order
    from apps.printing.services import build_receipt_payload
    from apps.printing.templates.receipt import render_text_preview

    medium = doneness_group.modifiers.get(name="Medium")
    garlic = sauces_group.modifiers.get(name="Чесночный")
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [medium.id, garlic.id],
        }],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    text = render_text_preview(build_receipt_payload(o))
    assert "+ Medium" in text
    assert "+ Чесночный" in text
    # Цена дельты отображается со знаком
    assert "(+3" in text


def test_hall_order_with_modifiers_includes_service_charge(
    restaurant, waiter, steak, doneness_group, sauces_group,
):
    """Зал: модификаторы попадают в subtotal, service_charge берётся от него."""
    from apps.orders.services import create_order
    from apps.tables.models import Table, Zone

    zone = Zone.objects.create(restaurant=restaurant, name="Зал")
    table = Table.objects.create(
        restaurant=restaurant, zone=zone, number=1,
        name="Стол 1", capacity=4,
    )
    # 10% сервис — Discount(type="service", is_active=True)
    from apps.orders.models import Discount

    Discount.objects.create(
        restaurant=restaurant, name="Обслуживание",
        type="service", kind="percent", value=Decimal("10"),
        is_active=True, sort_order=1,
    )

    medium = doneness_group.modifiers.get(name="Medium")
    spicy = sauces_group.modifiers.get(name="Острый")
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", table_id=table.id, guests_count=2,
        items_data=[{
            "menu_item_id": steak.id, "qty": 2,
            "modifier_ids": [medium.id, spicy.id],
        }],
        idempotency_key=uuid4(),
    )
    # subtotal позиции = (100 + 0 + 2) * 2 = 204
    item = o.items.first()
    assert item.modifiers.count() == 2
    assert item.subtotal == Decimal("204.00")
    # subtotal заказа = 204 (только одна позиция)
    assert o.subtotal == Decimal("204.00")
    # service_charge_amount = 204 * 10% = 20.40
    assert o.service_charge_amount == Decimal("20.40")
    # total = 204 + 20.40 = 224.40
    assert o.total == Decimal("224.40")


def test_takeaway_has_no_service_charge_even_when_configured(
    restaurant, waiter, steak, doneness_group,
):
    """С собой / доставка не должны облагаться сервисом — он только для зала."""
    from apps.orders.models import Discount
    from apps.orders.services import create_order

    Discount.objects.create(
        restaurant=restaurant, name="Обслуживание",
        type="service", kind="percent", value=Decimal("10"),
        is_active=True, sort_order=1,
    )
    medium = doneness_group.modifiers.get(name="Medium")

    o_takeaway = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [medium.id],
        }],
        idempotency_key=uuid4(),
    )
    assert o_takeaway.service_charge_pct == Decimal("0.00")
    assert o_takeaway.service_charge_amount == Decimal("0.00")
    assert o_takeaway.total == Decimal("100.00")

    o_delivery = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="delivery", guests_count=1,
        customer_phone="+992900000000",
        customer_address="ул. Рудаки 10",
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [medium.id],
        }],
        idempotency_key=uuid4(),
    )
    assert o_delivery.service_charge_pct == Decimal("0.00")
    assert o_delivery.total == Decimal("100.00")


def test_add_items_does_not_merge_when_modifiers_present(
    restaurant, waiter, steak, doneness_group, sauces_group,
):
    """Добавление того же блюда с другими модификаторами — отдельная позиция."""
    from apps.orders.services import add_items_to_order, create_order

    medium = doneness_group.modifiers.get(name="Medium")
    well = doneness_group.modifiers.get(name="Well-done")
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [medium.id],
        }],
        idempotency_key=uuid4(),
    )
    add_items_to_order(
        order_id=o.id, waiter=waiter,
        items_data=[{
            "menu_item_id": steak.id, "qty": 1,
            "modifier_ids": [well.id],
        }],
    )
    # Две разных позиции (medium и well-done)
    assert o.items.count() == 2
