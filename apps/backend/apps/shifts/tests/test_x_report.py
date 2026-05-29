"""X-отчёт — промежуточный snapshot открытой смены (можно печатать многократно).

В отличие от Z-отчёта, X-отчёт не закрывает смену.
"""
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


def _close_one(restaurant, waiter, cashier, table, menu_items, qty=1):
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


# -------- Service --------


def test_print_x_report_creates_print_job(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.printing.models import PrintJob, PrintJobKind
    from apps.shifts.models import ShiftStatus
    from apps.shifts.services import open_shift, print_x_report

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    _close_one(restaurant, waiter, cashier, table, menu_items)

    job = print_x_report(shift)
    assert job.kind == PrintJobKind.X_REPORT
    assert PrintJob.objects.filter(kind=PrintJobKind.X_REPORT).count() == 1
    # Смена осталась открытой
    shift.refresh_from_db()
    assert shift.status == ShiftStatus.OPEN
    assert job.payload["is_x_report"] is True
    assert job.payload["kpi"]["revenue"] == "45.00"


def test_print_x_report_can_be_called_multiple_times(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.printing.models import PrintJob, PrintJobKind
    from apps.shifts.services import open_shift, print_x_report

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    print_x_report(shift)
    print_x_report(shift)
    print_x_report(shift)
    assert PrintJob.objects.filter(kind=PrintJobKind.X_REPORT).count() == 3


def test_print_x_report_rejects_closed_shift(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.shifts.services import close_shift, open_shift, print_x_report
    from common.exceptions import BusinessError

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    close_shift(
        shift_id=shift.id, restaurant=restaurant,
        actual_balance=Decimal("100"),
    )
    shift.refresh_from_db()
    with pytest.raises(BusinessError) as exc:
        print_x_report(shift)
    assert exc.value.code == "INVALID_TRANSITION"


def test_x_report_writes_audit_log(
    restaurant, cashier, waiter, table, menu_items, printer
):
    from apps.audit.models import AuditAction, AuditEntry
    from apps.shifts.services import open_shift, print_x_report

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    print_x_report(shift)
    e = AuditEntry.objects.filter(action=AuditAction.X_REPORT_PRINTED).first()
    assert e is not None
    assert e.payload["shift_number"] == shift.number


def test_x_report_text_render_has_x_title():
    from apps.printing.templates.z_report import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе", "currency": "TJS",
                        "address": "", "phone": ""},
        "shift": {
            "number": 1, "opened_at": "2026-05-10T10:00:00+05:00",
            "closed_at": None, "cashier_name": "Анна",
            "opening_balance": "100", "expected_balance": "145",
            "actual_balance": None, "discrepancy": None,
            "cash_in_total": "0", "cash_out_total": "0",
        },
        "kpi": {
            "revenue": "45.00", "orders_count": 1, "guests_count": 1,
            "average_check": "45.00", "average_per_guest": "45.00",
        },
        "sales_by_payment": {"cash": "45.00"},
        "sales_by_order_type": [],
        "sales_by_category": [],
        "is_x_report": True,
    }
    text = render_text_preview(payload, width=48)
    assert "X-ОТЧЁТ" in text
    assert "Z-ОТЧЁТ" not in text


# -------- API --------


def test_print_x_endpoint(api_client, restaurant, cashier, printer):
    from apps.printing.models import PrintJobKind
    from apps.shifts.services import open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100")
    )
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        f"/api/v1/shifts/{shift.id}/print_x/",
        {}, format="json", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["shift_id"] == shift.id
    assert "job_id" in data
    # Реальный job создан
    from apps.printing.models import PrintJob
    j = PrintJob.objects.get(id=data["job_id"])
    assert j.kind == PrintJobKind.X_REPORT


def test_print_x_endpoint_404(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.post(
        "/api/v1/shifts/99999/print_x/",
        {}, format="json", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 404
