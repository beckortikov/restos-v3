"""Z-отчёт: PrintJob создаётся, render правильный, есть delta к предыдущей смене."""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

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


def _close_simple_order(restaurant, waiter, cashier, table, menu_items, qty=1):
    from apps.orders.services import close_order, create_order
    from apps.tables.services import free_table

    o = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": qty}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    free_table(table)
    return o


# -------- Service: print_z_report --------


def test_print_z_report_creates_print_job(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.printing.models import PrintJob, PrintJobKind
    from apps.shifts.services import open_shift, print_z_report

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    _close_simple_order(restaurant, waiter, cashier, table, menu_items)

    job = print_z_report(shift)
    assert job.kind == PrintJobKind.Z_REPORT
    assert job.restaurant == restaurant
    assert PrintJob.objects.filter(kind=PrintJobKind.Z_REPORT).count() == 1
    # Payload содержит kpi/sales_by_payment/shift
    assert "kpi" in job.payload
    assert job.payload["kpi"]["revenue"] == "45.00"
    assert "sales_by_payment" in job.payload
    assert job.payload["shift"]["number"] == shift.number


def test_print_z_writes_audit_log(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.shifts.services import open_shift, print_z_report

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    print_z_report(shift)

    e = AuditEntry.objects.filter(
        action=AuditAction.Z_REPORT_PRINTED
    ).first()
    assert e is not None
    assert e.payload.get("shift_number") == shift.number


# -------- API endpoint --------


def test_print_z_endpoint(
    api_client, restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.printing.models import PrintJob
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    _close_simple_order(restaurant, waiter, cashier, table, menu_items)

    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/shifts/{shift.id}/print_z/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["shift_id"] == shift.id
    assert PrintJob.objects.filter(id=data["job_id"]).exists()


# -------- Template render --------


def test_z_report_text_render():
    from apps.printing.templates.z_report import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе Анвар", "currency": "TJS"},
        "shift": {
            "number": 7,
            "opened_at": "2026-05-09T08:00:00+05:00",
            "closed_at": "2026-05-09T22:00:00+05:00",
            "cashier_name": "Иван",
            "opening_balance": "100.00",
            "expected_balance": "245.00",
        },
        "kpi": {
            "revenue": "145.00",
            "orders_count": 3,
            "guests_count": 5,
            "average_check": "48.33",
            "average_per_guest": "29.00",
        },
        "sales_by_payment": {
            "cash": "100.00", "card": "45.00", "transfer": "0.00",
        },
        "sales_by_order_type": [
            {"type": "hall", "orders_count": 3, "total": "145.00"},
        ],
        "sales_by_category": [
            {"id": 1, "name": "Горячее", "qty": 4, "total": "145.00"},
        ],
    }
    text = render_text_preview(payload, width=48)
    assert "Z-ОТЧЁТ" in text
    assert "Смена №7" in text
    assert "Кафе Анвар" in text
    assert "145.00" in text
    assert "Наличные" in text
    assert "Горячее" in text


# -------- Deltas in shift report --------


def test_report_deltas_compare_to_previous_shift(
    api_client, restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.shifts.services import build_shift_report, close_shift, open_shift

    # Прошлая смена: 1 заказ × 45 TJS
    s1 = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    _close_simple_order(restaurant, waiter, cashier, table, menu_items, qty=1)
    close_shift(
        shift_id=s1.id, restaurant=restaurant,
        actual_balance=Decimal("45"), note="",
    )

    # Текущая смена: 1 заказ × 90 (+100%)
    s2 = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    _close_simple_order(restaurant, waiter, cashier, table, menu_items, qty=2)

    rep = build_shift_report(s2)
    assert rep["previous_shift"]["shift_number"] == s1.number
    assert rep["previous_shift"]["revenue"] == "45.00"
    assert rep["deltas"]["revenue_pct"] == "100.0"
    assert rep["deltas"]["orders_pct"] == "0.0"


def test_report_deltas_empty_when_no_previous_shift(
    api_client, restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.shifts.services import build_shift_report, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("0")
    )
    rep = build_shift_report(shift)
    assert rep["previous_shift"] == {}
    assert rep["deltas"] == {}
