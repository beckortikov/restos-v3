"""MenuItemNote: модель, авто-сидер, CRUD, OrderItem.note."""
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


# -------- Auto-seed --------


def test_new_restaurant_seeds_item_notes(db):
    from apps.menu.defaults import DEFAULT_ITEM_NOTES
    from apps.menu.models import MenuItemNote
    from apps.users.models import Restaurant

    resto = Restaurant.objects.create(name="Notes seed", currency="TJS")
    seeded = set(
        MenuItemNote.objects.filter(restaurant=resto)
        .values_list("label", flat=True)
    )
    assert seeded == set(DEFAULT_ITEM_NOTES)


# -------- API --------


def test_list_notes(api_client, cashier_token, restaurant):
    resp = api_client.get(
        "/api/v1/menu/notes/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 8


def test_create_note(api_client, cashier_token):
    resp = api_client.post(
        "/api/v1/menu/notes/",
        {"label": "Без помидоров", "sort_order": 99, "is_active": True},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["label"] == "Без помидоров"


def test_update_note(api_client, cashier_token, restaurant):
    from apps.menu.models import MenuItemNote

    n = MenuItemNote.objects.filter(restaurant=restaurant).first()
    resp = api_client.patch(
        f"/api/v1/menu/notes/{n.id}/",
        {"is_active": False},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    n.refresh_from_db()
    assert n.is_active is False


def test_destroy_note(api_client, cashier_token, restaurant):
    from apps.menu.models import MenuItemNote

    n = MenuItemNote.objects.filter(restaurant=restaurant).first()
    nid = n.id
    resp = api_client.delete(
        f"/api/v1/menu/notes/{nid}/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 204
    assert not MenuItemNote.objects.filter(id=nid).exists()


def test_waiter_can_read_notes(api_client, cashier, waiter):
    """Официант может читать список (для chip-picker в waiter PWA)."""
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]
    resp = api_client.get(
        "/api/v1/menu/notes/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 200


def test_waiter_cannot_write_notes(api_client, cashier, waiter):
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]
    resp = api_client.post(
        "/api/v1/menu/notes/",
        {"label": "x"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403


# -------- OrderItem.note flow --------


def test_order_item_stores_note(restaurant, waiter, table, menu_items):
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1,
             "note": "Без лука"},
        ],
        comment="", idempotency_key=uuid4(),
    )
    item = order.items.first()
    assert item.note == "Без лука"


def test_add_items_separates_by_note(restaurant, waiter, table, menu_items):
    """Добавление того же блюда с разным note → две позиции."""
    from apps.orders.services import add_items_to_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1,
             "note": "Без лука"},
        ],
        comment="", idempotency_key=uuid4(),
    )
    add_items_to_order(
        order_id=order.id, waiter=waiter,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2,
             "note": "Острее"},
        ],
    )
    items = list(order.items.filter(menu_item=menu_items["plov"]))
    assert len(items) == 2
    by_note = {it.note: it.qty for it in items}
    assert by_note["Без лука"] == 1
    assert by_note["Острее"] == 2


def test_add_items_merges_same_note(restaurant, waiter, table, menu_items):
    """Тот же note + то же блюдо → qty увеличивается."""
    from apps.orders.services import add_items_to_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1,
             "note": "Без лука"},
        ],
        comment="", idempotency_key=uuid4(),
    )
    add_items_to_order(
        order_id=order.id, waiter=waiter,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2,
             "note": "Без лука"},
        ],
    )
    items = list(order.items.filter(menu_item=menu_items["plov"]))
    assert len(items) == 1
    assert items[0].qty == 3


def test_receipt_payload_includes_note(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order, create_order
    from apps.printing.services import build_receipt_payload

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1,
             "note": "Хорошо прожарить"},
        ],
        comment="", idempotency_key=uuid4(),
    )
    closed, _job = close_order(
        order_id=order.id, cashier=cashier, payment_method="cash"
    )
    payload = build_receipt_payload(closed)
    assert payload["items"][0]["note"] == "Хорошо прожарить"


def test_receipt_template_renders_note():
    """Текстовый чек содержит строку '* note' под названием блюда."""
    from apps.printing.templates.receipt import render_text_preview

    text = render_text_preview({
        "restaurant": {"name": "X", "currency": "TJS"},
        "order": {
            "id": 1, "table": "1", "guests": 1,
            "waiter": "А", "closed_at": "",
            "payment_method": "cash", "total": "45.00",
        },
        "items": [
            {"name": "Плов", "qty": 1, "price": "45.00",
             "subtotal": "45.00", "note": "Без лука"},
        ],
    })
    assert "* Без лука" in text
