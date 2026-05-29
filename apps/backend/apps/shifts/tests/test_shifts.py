from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone

    return Zone.objects.create(restaurant=restaurant, name="Зал")


@pytest.fixture
def table(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=1, name="Стол 1", capacity=4
    )


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Горячее")


@pytest.fixture
def menu_items(restaurant, category):
    from apps.menu.models import MenuItem

    plov = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов",
        price=Decimal("45.00"),
    )
    return {"plov": plov}


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind

    return Printer.objects.create(
        restaurant=restaurant, name="Касса", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )


# ----- service-level -----


def test_open_shift_creates_one(restaurant, cashier):
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000")
    )
    assert shift.status == "open"
    assert shift.number == 1
    assert shift.opening_balance == Decimal("1000")


def test_open_second_shift_raises(restaurant, cashier):
    from apps.shifts.services import open_shift
    from common.exceptions import BusinessError

    open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000")
    )
    with pytest.raises(BusinessError) as exc:
        open_shift(
            restaurant=restaurant, cashier=cashier, opening_balance=Decimal("500")
        )
    assert exc.value.code == "SHIFT_ALREADY_OPEN"
    assert exc.value.status_code == 409


def test_shift_number_increments(restaurant, cashier):
    from apps.shifts.services import close_shift, open_shift

    s1 = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    close_shift(
        shift_id=s1.id, restaurant=restaurant, actual_balance=Decimal("100")
    )
    s2 = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("200")
    )
    assert s2.number == 2


def test_close_shift_computes_discrepancy(restaurant, cashier):
    from apps.shifts.services import close_shift, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000")
    )
    closed = close_shift(
        shift_id=shift.id, restaurant=restaurant, actual_balance=Decimal("950")
    )
    assert closed.status == "closed"
    assert closed.actual_balance == Decimal("950")
    assert closed.discrepancy == Decimal("-50")


def test_order_links_to_shift_on_close(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.orders.services import close_order, create_order
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000")
    )
    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    closed, _job = close_order(
        order_id=order.id, cashier=cashier, payment_method="cash"
    )
    assert closed.shift_id == shift.id

    shift.refresh_from_db()
    assert shift.cash_revenue == Decimal("90.00")
    assert shift.expected_balance == Decimal("1000") + Decimal("90.00")
    assert shift.orders_count == 1


def test_revenue_split_by_payment_method(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.tables.models import Table
    from apps.orders.services import close_order, create_order
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )

    # 3 заказа: cash 45, card 90, transfer 45 — разные столы
    next_num = (
        Table.objects.filter(restaurant=restaurant).order_by("-number").first().number
    )
    for i, pm in enumerate(("cash", "card", "transfer")):
        if i == 0:
            t = table
        else:
            next_num += 1
            t = Table.objects.create(
                restaurant=restaurant, zone=table.zone,
                number=next_num, name=f"Стол-{pm}",
            )
        qty = 1 if pm != "card" else 2
        order = create_order(
            restaurant=restaurant, table_id=t.id, waiter=waiter,
            guests_count=1,
            items_data=[{"menu_item_id": menu_items["plov"].id, "qty": qty}],
            idempotency_key=uuid4(),
        )
        close_order(order_id=order.id, cashier=cashier, payment_method=pm)

    shift.refresh_from_db()
    assert shift.cash_revenue == Decimal("45.00")
    assert shift.card_revenue == Decimal("90.00")
    assert shift.transfer_revenue == Decimal("45.00")
    assert shift.orders_count == 3


# ----- API-level -----


def test_open_via_api(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/shifts/open/",
        {"opening_balance": "1500.00"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()["data"]
    assert body["status"] == "open"
    assert body["opening_balance"] == "1500.00"


def test_open_409_if_already_open(api_client, restaurant, cashier):
    from apps.shifts.services import open_shift

    open_shift(restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0"))

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/shifts/open/",
        {"opening_balance": "1000.00"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SHIFT_ALREADY_OPEN"


def test_get_current_returns_open_shift(api_client, restaurant, cashier):
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/shifts/current/", HTTP_AUTHORIZATION=f"PIN {pin}"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == shift.id


def test_get_current_returns_null_when_no_shift(api_client, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/shifts/current/", HTTP_AUTHORIZATION=f"PIN {pin}"
    )
    assert resp.status_code == 200
    assert resp.json()["data"] is None


def test_close_via_api(api_client, restaurant, cashier):
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("1000")
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/shifts/{shift.id}/close/",
        {"actual_balance": "950.00", "note": "вечерняя"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["status"] == "closed"
    assert body["discrepancy"] == "-50.00"


def test_close_already_closed_raises(api_client, restaurant, cashier):
    from apps.shifts.services import close_shift, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    close_shift(
        shift_id=shift.id, restaurant=restaurant, actual_balance=Decimal("0")
    )

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/shifts/{shift.id}/close/",
        {"actual_balance": "0"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SHIFT_ALREADY_CLOSED"


def test_report_returns_aggregations(
    api_client, restaurant, cashier, waiter, table, menu_items, printer
):
    """GET /shifts/{id}/report/ возвращает KPI + sales_by_*."""
    from apps.tables.models import Table
    from apps.orders.services import close_order, create_order
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    o1 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o1.id, cashier=cashier, payment_method="cash")
    t2 = Table.objects.create(
        restaurant=restaurant, zone=table.zone, number=99, name="Стол 99"
    )
    o2 = create_order(
        restaurant=restaurant, table_id=t2.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o2.id, cashier=cashier, payment_method="card")

    pin = _pin(api_client, cashier)
    resp = api_client.get(
        f"/api/v1/shifts/{shift.id}/report/",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]

    assert data["kpi"]["orders_count"] == 2
    assert data["kpi"]["guests_count"] == 3
    assert data["kpi"]["revenue"] == "135.00"

    assert data["sales_by_payment"]["cash"] == "90.00"
    assert data["sales_by_payment"]["card"] == "45.00"
    assert data["sales_by_payment"]["transfer"] == "0.00"

    cats = {r["name"]: r for r in data["sales_by_category"]}
    assert "Горячее" in cats
    assert cats["Горячее"]["qty"] == 3
    assert cats["Горячее"]["total"] == "135.00"

    waiters = {r["id"]: r for r in data["sales_by_waiter"]}
    assert waiter.id in waiters
    assert waiters[waiter.id]["orders_count"] == 2
    assert waiters[waiter.id]["total"] == "135.00"


def test_waiter_cannot_open_shift(api_client, waiter):
    """Только кассир открывает/закрывает смены."""
    access = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()["data"]["access"]

    resp = api_client.post(
        "/api/v1/shifts/open/",
        {"opening_balance": "0"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403
