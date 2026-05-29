"""OrderViewSet.list — pagination + search + filters.

Закрывает A: фронт OrderHistoryScreen теперь может листать страницы и искать.
"""
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [{"menu_item_id": menu_items["plov"].id, "qty": 1}]


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def _create_n_orders(restaurant, waiter, table, menu_items, n: int):
    from apps.orders.services import create_order
    from apps.tables.services import free_table

    orders = []
    for _ in range(n):
        order = create_order(
            restaurant=restaurant, table_id=table.id, waiter=waiter,
            guests_count=1, items_data=_items(menu_items), comment="",
            idempotency_key=uuid4(),
        )
        orders.append(order)
        # Освобождаем стол чтобы можно было создать следующий
        free_table(table)
    return orders


# -------- Pagination --------


def test_list_paginated_first_page(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    _create_n_orders(restaurant, waiter, table, menu_items, n=3)

    resp = api_client.get(
        "/api/v1/orders/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "meta" in body
    assert body["meta"]["total"] == 3
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 50
    assert len(body["data"]) == 3


def test_pagination_with_small_page_size(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    _create_n_orders(restaurant, waiter, table, menu_items, n=5)

    resp = api_client.get(
        "/api/v1/orders/?page_size=2",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    body = resp.json()
    assert body["meta"]["total"] == 5
    assert body["meta"]["pages"] == 3
    assert len(body["data"]) == 2

    # Page 2
    resp = api_client.get(
        "/api/v1/orders/?page=2&page_size=2",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    body = resp.json()
    assert body["meta"]["page"] == 2
    assert len(body["data"]) == 2

    # Page 3
    resp = api_client.get(
        "/api/v1/orders/?page=3&page_size=2",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert len(resp.json()["data"]) == 1


# -------- Multi-status filter --------


def test_filter_status_csv(
    api_client, cashier_token, restaurant, waiter, cashier, table, menu_items, printer
):
    """status=new,bill_requested → IN-фильтр."""
    from apps.orders.services import close_order, create_order, request_bill
    from apps.tables.services import free_table

    o1 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    free_table(table)
    o2 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    request_bill(order_id=o2.id, waiter=waiter)
    free_table(table)
    o3 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(order_id=o3.id, cashier=cashier, payment_method="cash")

    resp = api_client.get(
        "/api/v1/orders/?status=new,bill_requested",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    statuses = {o["status"] for o in resp.json()["data"]}
    assert statuses == {"new", "bill_requested"}
    assert len(resp.json()["data"]) == 2


# -------- Date range --------


def test_filter_date_from_to(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    """from / to фильтр по created_at__date."""
    from datetime import date, timedelta

    from apps.orders.services import create_order
    from apps.tables.services import free_table

    o = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    free_table(table)
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    resp = api_client.get(
        f"/api/v1/orders/?from={today}&to={today}",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert len(resp.json()["data"]) >= 1

    resp = api_client.get(
        f"/api/v1/orders/?from={tomorrow}&to={tomorrow}",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    # Завтрашних нет
    assert resp.json()["data"] == []


# -------- Search --------


def test_search_by_id(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    o = _create_n_orders(restaurant, waiter, table, menu_items, n=1)[0]

    resp = api_client.get(
        f"/api/v1/orders/?q={o.id}",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    data = resp.json()["data"]
    assert any(it["id"] == o.id for it in data)


def test_search_by_customer_name(
    api_client, cashier_token, restaurant, waiter, menu_items
):
    from apps.orders.services import create_order

    create_order(
        restaurant=restaurant, waiter=waiter,
        items_data=_items(menu_items), comment="",
        order_type="takeaway",
        customer_name="Иван Петров",
        customer_phone="+992 900 11 22 33",
        idempotency_key=uuid4(),
    )
    resp = api_client.get(
        "/api/v1/orders/?q=Иван",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    data = resp.json()["data"]
    assert any(o.get("customer_name") == "Иван Петров" for o in data)


def test_search_by_table_name(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    _create_n_orders(restaurant, waiter, table, menu_items, n=1)
    resp = api_client.get(
        f"/api/v1/orders/?q={table.name}",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert len(resp.json()["data"]) >= 1


def test_search_by_item_name(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    _create_n_orders(restaurant, waiter, table, menu_items, n=1)
    resp = api_client.get(
        "/api/v1/orders/?q=Плов",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert len(resp.json()["data"]) >= 1


def test_search_no_match_returns_empty(
    api_client, cashier_token, restaurant, waiter, table, menu_items
):
    _create_n_orders(restaurant, waiter, table, menu_items, n=1)
    resp = api_client.get(
        "/api/v1/orders/?q=XYZ_NOT_EXISTS",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.json()["data"] == []
