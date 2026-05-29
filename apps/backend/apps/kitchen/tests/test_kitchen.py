"""Кухня / KDS: переходы статусов + endpoints + permissions."""
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, user, pin: str):
    """Логин с уникальным MVP_RESTAURANT_ID — ставим на cook'а."""
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": pin}, format="json"
    ).json()["data"]["session_token"]


def _create_order(restaurant, waiter, table, menu_items):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2},
            {"menu_item_id": menu_items["chai"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )


# -------- Service: lifecycle --------


def test_new_item_starts_in_status_new(restaurant, waiter, table, menu_items):
    order = _create_order(restaurant, waiter, table, menu_items)
    for item in order.items.all():
        assert item.kitchen_status == "new"


def test_start_cooking_transitions_to_cooking(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    item2 = start_cooking(
        item_id=item.id, restaurant=restaurant, user=cook,
    )
    assert item2.kitchen_status == "cooking"
    assert item2.started_cooking_at is not None
    assert item2.cooked_by_id == cook.id


def test_mark_ready_after_cooking(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import mark_ready, start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    item2 = mark_ready(item_id=item.id, restaurant=restaurant, user=cook)
    assert item2.kitchen_status == "ready"
    assert item2.ready_at is not None


def test_mark_served_after_ready(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import mark_ready, mark_served, start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    mark_ready(item_id=item.id, restaurant=restaurant, user=cook)
    item2 = mark_served(item_id=item.id, restaurant=restaurant, user=cook)
    assert item2.kitchen_status == "served"
    assert item2.served_at is not None


def test_mark_served_can_skip_ready_from_cooking(
    restaurant, waiter, cook, table, menu_items,
):
    """Официант жмёт «Выдано» сразу после «Готовится» — это разрешено."""
    from apps.kitchen.services import mark_served, start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    item2 = mark_served(item_id=item.id, restaurant=restaurant, user=cook)
    assert item2.kitchen_status == "served"
    assert item2.ready_at is not None  # автозаполнено


def test_cannot_mark_ready_from_new(
    restaurant, waiter, cook, table, menu_items,
):
    """Нельзя прыгнуть NEW → READY минуя COOKING."""
    from apps.kitchen.services import mark_ready
    from common.exceptions import BusinessError

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    with pytest.raises(BusinessError) as exc:
        mark_ready(item_id=item.id, restaurant=restaurant, user=cook)
    assert exc.value.code == "INVALID_TRANSITION"


def test_cannot_start_cooking_cancelled_item(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import start_cooking
    from apps.orders.services import cancel_item
    from common.exceptions import BusinessError

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    cancel_item(
        order_id=order.id, item_id=item.id, user=waiter,
        reason="test",
    )
    with pytest.raises(BusinessError):
        start_cooking(item_id=item.id, restaurant=restaurant, user=cook)


def test_idempotent_when_already_in_target(
    restaurant, waiter, cook, table, menu_items,
):
    """Повторный start_cooking когда уже в COOKING — не падает."""
    from apps.kitchen.services import start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    item2 = start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    assert item2.kitchen_status == "cooking"


def test_audit_log_on_status_change(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.kitchen.services import start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    e = AuditEntry.objects.filter(
        action=AuditAction.KITCHEN_START_COOKING, target_id=item.id,
    ).first()
    assert e is not None
    assert e.payload["from_status"] == "new"
    assert e.payload["to_status"] == "cooking"


# -------- list_kitchen_items --------


def test_list_kitchen_items_default_excludes_served(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import (
        list_kitchen_items, mark_ready, mark_served, start_cooking,
    )

    order = _create_order(restaurant, waiter, table, menu_items)
    items = list(order.items.all())
    # Один станет served
    start_cooking(item_id=items[0].id, restaurant=restaurant, user=cook)
    mark_ready(item_id=items[0].id, restaurant=restaurant, user=cook)
    mark_served(item_id=items[0].id, restaurant=restaurant, user=cook)

    qs = list(list_kitchen_items(restaurant))
    ids = {i.id for i in qs}
    assert items[0].id not in ids  # served — не в списке
    assert items[1].id in ids


def test_list_kitchen_items_excludes_cancelled(
    restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import list_kitchen_items
    from apps.orders.services import cancel_item

    order = _create_order(restaurant, waiter, table, menu_items)
    items = list(order.items.all())
    cancel_item(
        order_id=order.id, item_id=items[0].id, user=waiter, reason="x",
    )
    qs = list(list_kitchen_items(restaurant))
    ids = {i.id for i in qs}
    assert items[0].id not in ids


# -------- API endpoints --------


def test_kitchen_list_endpoint_for_cook(
    api_client, restaurant, waiter, cook, table, menu_items,
):
    _create_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, cook, "5555")
    resp = api_client.get(
        "/api/v1/kitchen/items/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert len(data) >= 2  # 2 позиции, обе NEW


def test_kitchen_list_filter_by_status(
    api_client, restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    items = list(order.items.all())
    start_cooking(item_id=items[0].id, restaurant=restaurant, user=cook)

    pin = _pin(api_client, cook, "5555")
    resp = api_client.get(
        "/api/v1/kitchen/items/?status=cooking",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()["data"]
    statuses = {i["kitchen_status"] for i in body}
    assert statuses == {"cooking"}


def test_start_cooking_endpoint(
    api_client, restaurant, waiter, cook, table, menu_items,
):
    order = _create_order(restaurant, waiter, table, menu_items)
    item_id = order.items.first().id
    pin = _pin(api_client, cook, "5555")
    resp = api_client.post(
        f"/api/v1/kitchen/items/{item_id}/start_cooking/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["kitchen_status"] == "cooking"


def test_mark_ready_endpoint(
    api_client, restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)

    pin = _pin(api_client, cook, "5555")
    resp = api_client.post(
        f"/api/v1/kitchen/items/{item.id}/mark_ready/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["kitchen_status"] == "ready"


def test_mark_served_endpoint(
    api_client, restaurant, waiter, cook, table, menu_items,
):
    from apps.kitchen.services import mark_ready, start_cooking

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    mark_ready(item_id=item.id, restaurant=restaurant, user=cook)

    pin = _pin(api_client, cook, "5555")
    resp = api_client.post(
        f"/api/v1/kitchen/items/{item.id}/mark_served/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["kitchen_status"] == "served"


def test_kitchen_endpoint_forbidden_for_waiter(
    api_client, restaurant, waiter, table, menu_items,
):
    """Официант не имеет доступа к KDS — 403."""
    _create_order(restaurant, waiter, table, menu_items)
    access = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]
    resp = api_client.get(
        "/api/v1/kitchen/items/", HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403


def test_kitchen_endpoint_works_for_cashier(
    api_client, restaurant, waiter, cashier, table, menu_items,
):
    """Кассир тоже видит KDS — для контроля выдачи."""
    _create_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, cashier, "1234")
    resp = api_client.get(
        "/api/v1/kitchen/items/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200


def test_serializer_includes_table_and_station(
    api_client, restaurant, waiter, cook, table, menu_items,
):
    """KitchenItemSerializer denormalizes table_name + waiter_name + station."""
    _create_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, cook, "5555")
    resp = api_client.get(
        "/api/v1/kitchen/items/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    assert all("table_name" in i for i in data)
    assert all("waiter_name" in i for i in data)
    assert all("category_name" in i for i in data)
