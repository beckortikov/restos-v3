"""Multi-group per table: несколько активных заказов на одном столе одновременно."""
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _create_order(restaurant, waiter, table, menu_items, qty=1, guests=2):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=guests,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": qty}],
        idempotency_key=uuid4(),
    )


# -------- Service: multi-group create --------


def test_can_open_second_group_on_occupied_table(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    """На уже занятом столе можно открыть вторую группу."""
    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=3)
    assert o1.id != o2.id
    assert o1.table_id == o2.table_id

    table.refresh_from_db()
    # Стол всё ещё занят, primary current_order — первая группа
    assert table.status == "occupied"
    assert table.current_order_id == o1.id
    # guests_count = сумма обеих групп
    assert table.guests_count == 5


def test_three_groups_on_one_table(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=1)
    o3 = _create_order(restaurant, waiter, table, menu_items, guests=4)
    table.refresh_from_db()
    assert table.guests_count == 7
    # primary остаётся первой группой
    assert table.current_order_id == o1.id


def test_cannot_open_order_on_merged_table(
    restaurant, waiter, cashier, menu_items, printer,
):
    """На столе со status=MERGED (не primary в группе) заказ запрещён."""
    from apps.tables.models import Table, TableStatus, Zone
    from apps.orders.services import create_order
    from common.exceptions import BusinessError

    z = Zone.objects.create(restaurant=restaurant, name="Z")
    merged_table = Table.objects.create(
        restaurant=restaurant, zone=z, number=66, name="Стол 66",
        status=TableStatus.MERGED,
    )
    with pytest.raises(BusinessError) as exc:
        create_order(
            restaurant=restaurant, table_id=merged_table.id, waiter=waiter,
            guests_count=1,
            items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
            idempotency_key=uuid4(),
        )
    assert exc.value.code == "TABLE_OCCUPIED"


# -------- Service: free_table with multi-group --------


def test_close_first_group_keeps_table_occupied_when_second_active(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    """Закрыли первую группу — стол остаётся занят, вторая активна."""
    from apps.orders.services import close_order

    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=3)

    close_order(order_id=o1.id, cashier=cashier, payment_method="cash")
    table.refresh_from_db()
    assert table.status == "occupied"
    # primary переключился на вторую группу
    assert table.current_order_id == o2.id
    # guests = только оставшаяся группа
    assert table.guests_count == 3


def test_close_last_group_frees_table(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order

    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=3)

    close_order(order_id=o1.id, cashier=cashier, payment_method="cash")
    close_order(order_id=o2.id, cashier=cashier, payment_method="cash")
    table.refresh_from_db()
    assert table.status == "free"
    assert table.current_order_id is None
    assert table.guests_count == 0


def test_bill_requested_propagates_to_table_when_some_group_requests(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    """Если одна из групп в bill_requested — стол показывает bill_requested."""
    from apps.orders.services import close_order, request_bill

    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=3)

    request_bill(order_id=o2.id, waiter=waiter)

    # Закроем первую — должна остаться вторая в bill_requested
    close_order(order_id=o1.id, cashier=cashier, payment_method="cash")
    table.refresh_from_db()
    assert table.status == "bill_requested"
    assert table.current_order_id == o2.id


# -------- Serializer: active_orders --------


def test_table_serializer_returns_active_orders(
    api_client, restaurant, waiter, cashier, table, menu_items, printer,
):
    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=3)

    pin = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]
    resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    by_id = {t["id"]: t for t in resp.json()["data"]}
    assert table.id in by_id
    active = by_id[table.id]["active_orders"]
    assert len(active) == 2
    ids = {o["id"] for o in active}
    assert ids == {o1.id, o2.id}
    # Проверяем что есть guests/total/waiter_name
    for o in active:
        assert "guests_count" in o
        assert "total" in o
        assert "waiter_name" in o


def test_table_serializer_active_orders_empty_when_table_free(
    api_client, restaurant, cashier, table,
):
    pin = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]
    resp = api_client.get(
        "/api/v1/tables/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    by_id = {t["id"]: t for t in resp.json()["data"]}
    assert by_id[table.id]["active_orders"] == []


# -------- cancel_item across groups --------


def test_cancel_item_only_affects_its_group(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    """Отмена позиции в одной группе не трогает другую."""
    from apps.orders.services import cancel_item

    o1 = _create_order(restaurant, waiter, table, menu_items, guests=2)
    o2 = _create_order(restaurant, waiter, table, menu_items, guests=3)
    item1 = o1.items.first()
    cancel_item(
        order_id=o1.id, item_id=item1.id, user=waiter, reason="t",
    )
    o1.refresh_from_db()
    o2.refresh_from_db()
    # o1 ушёл в cancelled (была единственная позиция → cancel_order)
    assert o1.status == "cancelled"
    # o2 не тронут
    assert o2.status == "new"
    # Стол ещё занят — есть o2
    table.refresh_from_db()
    assert table.status == "occupied"
    assert table.current_order_id == o2.id
