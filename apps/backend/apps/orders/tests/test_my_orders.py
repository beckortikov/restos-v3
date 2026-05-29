"""GET /orders/me/ — короткий алиас для waiter."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category
    return Category.objects.create(restaurant=restaurant, name="Кухня")


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
        restaurant=restaurant, name="Касса",
        kind=PrinterKind.VIRTUAL, is_default=True, is_active=True,
    )


def test_my_orders_returns_only_my_active(
    api_client, waiter, cashier, restaurant, plov, cashier_printer,
):
    """waiter видит только свои new/bill_requested заказы."""
    from apps.orders.services import close_order, create_order, request_bill

    # Свой new
    o1 = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    # Свой bill_requested
    o2 = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    request_bill(order_id=o2.id, waiter=waiter)
    # Свой done — не должен попадать в /me/
    o3 = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o3.id, cashier=cashier, payment_method="cash")

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/orders/me/")
    assert resp.status_code == 200, resp.content
    ids = {item["id"] for item in resp.json()["data"]}
    assert ids == {o1.id, o2.id}


def test_my_orders_excludes_other_waiters(
    api_client, waiter, restaurant, plov, cashier_printer,
):
    """waiter не видит заказы другого официанта."""
    from apps.orders.services import create_order
    from apps.users.models import User, UserRole

    other = User.objects.create_user(
        username="other_waiter", password="p",
        role=UserRole.WAITER, restaurant=restaurant, full_name="Другой",
    )
    other_order = create_order(
        restaurant=restaurant, waiter=other,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/orders/me/")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["data"]}
    assert other_order.id not in ids


def test_my_orders_cross_restaurant_isolation(
    api_client, waiter, plov, cashier_printer,
):
    """waiter из ресторана A не видит заказы ресторана B."""
    from apps.orders.services import create_order
    from apps.users.models import Restaurant, User, UserRole

    other_resto = Restaurant.objects.create(name="Other", currency="TJS")
    from apps.menu.models import Category, MenuItem
    other_cat = Category.objects.create(restaurant=other_resto, name="x")
    other_item = MenuItem.objects.create(
        restaurant=other_resto, category=other_cat, name="X", price=Decimal("10"),
    )
    other_waiter = User.objects.create_user(
        username="ow", password="p",
        role=UserRole.WAITER, restaurant=other_resto, full_name="Ow",
    )
    from apps.printing.models import Printer, PrinterKind
    Printer.objects.create(
        restaurant=other_resto, name="cp", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )
    create_order(
        restaurant=other_resto, waiter=other_waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": other_item.id, "qty": 1}],
        idempotency_key=uuid4(),
    )

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/orders/me/")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_my_history_returns_only_done_and_cancelled(
    api_client, waiter, cashier, restaurant, plov, cashier_printer,
):
    """GET /orders/me/history/ — закрытые/отменённые заказы текущего юзера."""
    from apps.orders.services import (
        cancel_order,
        close_order,
        create_order,
    )

    # Активный (new) — не должен попасть в /me/history/
    active = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    # Done
    done = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=done.id, cashier=cashier, payment_method="cash")
    # Cancelled
    cancelled = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    cancel_order(order_id=cancelled.id, user=waiter, reason="тест")

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/orders/me/history/")
    assert resp.status_code == 200, resp.content
    ids = {item["id"] for item in resp.json()["data"]}
    assert ids == {done.id, cancelled.id}
    assert active.id not in ids


def test_my_history_respects_limit(
    api_client, waiter, cashier, restaurant, plov, cashier_printer,
):
    from apps.orders.services import close_order, create_order

    for _ in range(3):
        o = create_order(
            restaurant=restaurant, waiter=waiter,
            order_type="takeaway", guests_count=1,
            items_data=[{"menu_item_id": plov.id, "qty": 1}],
            idempotency_key=uuid4(),
        )
        close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/orders/me/history/?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2


def test_my_history_excludes_other_waiters(
    api_client, waiter, cashier, restaurant, plov, cashier_printer,
):
    from apps.orders.services import close_order, create_order
    from apps.users.models import User, UserRole

    other = User.objects.create_user(
        username="ow2", password="p",
        role=UserRole.WAITER, restaurant=restaurant, full_name="O",
    )
    other_order = create_order(
        restaurant=restaurant, waiter=other,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=other_order.id, cashier=cashier, payment_method="cash")

    api_client.force_authenticate(user=waiter)
    resp = api_client.get("/api/v1/orders/me/history/")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["data"]}
    assert other_order.id not in ids
