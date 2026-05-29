from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _jwt(api_client, waiter):
    return api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]


def _pin_token(api_client, cashier):
    return api_client.post("/api/v1/auth/pin/", {"pin": "1234"}, format="json").json()[
        "data"
    ]["session_token"]


def test_create_order_via_api_requires_idempotency_key(
    api_client, waiter, table, menu_items
):
    access = _jwt(api_client, waiter)
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "table_id": table.id,
            "guests_count": 2,
            "items": [{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_create_order_via_api_happy(api_client, waiter, table, menu_items):
    access = _jwt(api_client, waiter)
    key = str(uuid4())
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "table_id": table.id,
            "guests_count": 3,
            "items": [
                {"menu_item_id": menu_items["plov"].id, "qty": 2},
                {"menu_item_id": menu_items["chai"].id, "qty": 1},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["status"] == "new"
    assert data["total"] == "98.00"
    assert data["table"] == table.id
    assert data["waiter_name"] == "Карим Официант"
    assert len(data["items"]) == 2


def test_create_order_idempotency_replay(api_client, waiter, table, menu_items):
    access = _jwt(api_client, waiter)
    key = str(uuid4())
    payload = {
        "table_id": table.id,
        "guests_count": 1,
        "items": [{"menu_item_id": menu_items["plov"].id, "qty": 1}],
    }
    r1 = api_client.post(
        "/api/v1/orders/", payload, format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}", HTTP_IDEMPOTENCY_KEY=key,
    )
    r2 = api_client.post(
        "/api/v1/orders/", payload, format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}", HTTP_IDEMPOTENCY_KEY=key,
    )
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]


def test_full_lifecycle_via_api(
    api_client, waiter, cashier, table, menu_items, printer
):
    access = _jwt(api_client, waiter)
    pin = _pin_token(api_client, cashier)

    create = api_client.post(
        "/api/v1/orders/",
        {
            "table_id": table.id,
            "guests_count": 2,
            "items": [
                {"menu_item_id": menu_items["plov"].id, "qty": 2},
                {"menu_item_id": menu_items["chai"].id, "qty": 1},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert create.status_code == 201
    oid = create.json()["data"]["id"]

    # request_bill
    rb = api_client.post(
        f"/api/v1/orders/{oid}/request_bill/",
        {}, format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert rb.status_code == 200
    assert rb.json()["data"]["status"] == "bill_requested"

    # close (cashier)
    close = api_client.post(
        f"/api/v1/orders/{oid}/close/",
        {"payment_method": "cash"}, format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert close.status_code == 200, close.content
    body = close.json()["data"]
    assert body["order"]["status"] == "done"
    assert body["order"]["payment_method"] == "cash"
    assert body["print_job"]["status"] == "pending"


def test_cashier_can_create_order(api_client, cashier, table, menu_items):
    """В POS-моноблоке кассир тоже создаёт заказы (как waiter)."""
    pin = _pin_token(api_client, cashier)
    resp = api_client.post(
        "/api/v1/orders/",
        {"table_id": table.id, "guests_count": 1,
         "items": [{"menu_item_id": menu_items["plov"].id, "qty": 1}]},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 201, resp.content


def test_takeaway_order_no_table(api_client, waiter, menu_items):
    access = _jwt(api_client, waiter)
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "order_type": "takeaway",
            "items": [{"menu_item_id": menu_items["plov"].id, "qty": 1}],
            "customer_name": "Иван",
            "customer_phone": "+992 90 000 00 00",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["order_type"] == "takeaway"
    assert data["table"] is None
    assert data["customer_name"] == "Иван"


def test_delivery_requires_address(api_client, waiter, menu_items):
    access = _jwt(api_client, waiter)
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "order_type": "delivery",
            "items": [{"menu_item_id": menu_items["plov"].id, "qty": 1}],
            "customer_name": "Иван",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code in (400, 422)


def test_hall_order_requires_table(api_client, waiter, menu_items):
    access = _jwt(api_client, waiter)
    resp = api_client.post(
        "/api/v1/orders/",
        {
            "order_type": "hall",
            "items": [{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code in (400, 422)


def test_waiter_cannot_close_order(
    api_client, waiter, table, menu_items
):
    from apps.orders.services import create_order, request_bill

    order = create_order(
        restaurant=waiter.restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )
    request_bill(order_id=order.id, waiter=waiter)

    access = _jwt(api_client, waiter)
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/close/",
        {"payment_method": "cash"}, format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 403


def test_all_roles_see_all_orders(
    api_client, waiter, restaurant, table, menu_items, db
):
    """В POS-моноблоке кассир и официанты видят весь список заказов ресторана."""
    from apps.orders.services import create_order
    from apps.users.models import User, UserRole

    other_waiter = User.objects.create_user(
        username="waiter2", password="x", full_name="Другой",
        role=UserRole.WAITER, restaurant=restaurant,
    )
    other_table = type(table).objects.create(
        restaurant=restaurant, zone=table.zone, number=2, name="Стол 2"
    )

    create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    create_order(
        restaurant=restaurant, table_id=other_table.id, waiter=other_waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )

    access = _jwt(api_client, waiter)
    resp = api_client.get(
        "/api/v1/orders/", HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    body = resp.json()
    assert body["meta"]["total"] == 2
