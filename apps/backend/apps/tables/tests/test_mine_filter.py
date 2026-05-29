"""GET /tables/?mine=true — фильтр «мои столы» для waiter PWA."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone
    return Zone.objects.create(restaurant=restaurant, name="Зал")


@pytest.fixture
def tables(restaurant, zone):
    from apps.tables.models import Table
    return [
        Table.objects.create(
            restaurant=restaurant, zone=zone, number=i, name=f"Стол {i}", capacity=4,
        )
        for i in range(1, 4)
    ]


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category
    return Category.objects.create(restaurant=restaurant, name="Меню")


@pytest.fixture
def plov(restaurant, category):
    from apps.menu.models import MenuItem
    return MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов", price=Decimal("45"),
    )


@pytest.fixture
def cashier_printer(restaurant):
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="cp", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )


def test_mine_filter_returns_only_my_tables(
    api_client, waiter, cashier_printer, restaurant, tables, plov,
):
    """waiter с заказом на 1 столе видит только этот стол при mine=true."""
    from apps.orders.services import create_order

    create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=tables[0].id,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/tables/?mine=true")
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()["data"]}
    assert ids == {tables[0].id}


def test_mine_filter_excludes_other_waiters_tables(
    api_client, waiter, cashier_printer, restaurant, tables, plov,
):
    """Стол другого официанта не попадает в mine=true."""
    from apps.orders.services import create_order
    from apps.users.models import User, UserRole

    other = User.objects.create_user(
        username="other", password="p",
        role=UserRole.WAITER, restaurant=restaurant, full_name="Other",
    )
    create_order(
        restaurant=restaurant, waiter=other,
        order_type="hall", guests_count=1, table_id=tables[0].id,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/tables/?mine=true")
    assert resp.json()["data"] == []


def test_no_mine_returns_all_tables(api_client, waiter, tables):
    """Без ?mine — все столы ресторана."""
    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/tables/")
    ids = {t["id"] for t in resp.json()["data"]}
    assert ids == {t.id for t in tables}


def test_tables_returns_status_display(api_client, waiter, tables):
    """Сериализатор отдаёт status_display."""
    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/tables/")
    for t in resp.json()["data"]:
        assert "status_display" in t
        assert isinstance(t["status_display"], str)


def test_orders_returns_status_display(
    api_client, waiter, cashier_printer, restaurant, tables, plov,
):
    """OrderSerializer отдаёт status_display."""
    from apps.orders.services import create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=tables[0].id,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    api_client.force_authenticate(user=waiter)
    resp = api_client.get(f"/api/v1/orders/{o.id}/")
    body = resp.json()["data"]
    assert "status_display" in body
    assert body["status_display"]  # not empty


def test_order_items_excludes_cancelled(
    api_client, waiter, cashier, cashier_printer, restaurant, tables, plov,
):
    """Order.items не содержит отменённых позиций."""
    from apps.orders.services import cancel_item, create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=tables[0].id,
        items_data=[
            {"menu_item_id": plov.id, "qty": 1},
            {"menu_item_id": plov.id, "qty": 1, "note": "будет отменён"},
        ],
        idempotency_key=uuid4(),
    )
    item_to_cancel = o.items.filter(note="будет отменён").first()
    cancel_item(
        order_id=o.id, item_id=item_to_cancel.id,
        user=cashier, reason="test",
    )

    api_client.force_authenticate(user=waiter)
    resp = api_client.get(f"/api/v1/orders/{o.id}/")
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["note"] == ""
