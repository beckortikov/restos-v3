"""Печать копий чека: Restaurant.receipt_copies + N PrintJob-ов."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, cashier):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()["data"]["session_token"]


# -------- Service --------


def test_default_receipt_copies_is_one(restaurant):
    assert restaurant.receipt_copies == 1


def test_close_order_creates_one_print_job_by_default(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order, create_order
    from apps.printing.models import PrintJob, PrintJobKind

    o = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    jobs = PrintJob.objects.filter(
        order=o, kind=PrintJobKind.GUEST_RECEIPT,
    )
    assert jobs.count() == 1


def test_close_order_creates_n_print_jobs_when_copies_2(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order, create_order
    from apps.printing.models import PrintJob, PrintJobKind

    restaurant.receipt_copies = 2
    restaurant.save(update_fields=["receipt_copies"])

    o = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    jobs = list(PrintJob.objects.filter(
        order=o, kind=PrintJobKind.GUEST_RECEIPT,
    ).order_by("id"))
    assert len(jobs) == 2
    # Каждая job помечена индексом копии
    assert jobs[0].payload.get("copy") == {"index": 1, "total": 2}
    assert jobs[1].payload.get("copy") == {"index": 2, "total": 2}


def test_close_order_creates_three_copies(
    restaurant, waiter, cashier, table, menu_items, printer,
):
    from apps.orders.services import close_order, create_order
    from apps.printing.models import PrintJob

    restaurant.receipt_copies = 3
    restaurant.save(update_fields=["receipt_copies"])

    o = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    assert PrintJob.objects.filter(order=o).count() == 3


def test_receipt_template_shows_copy_marker():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе"},
        "order": {
            "id": 1, "table": "1", "guests": 1,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T12:00:00",
            "payment_method": "cash",
            "subtotal": "10", "service_charge_amount": "0",
            "discount_amount": "0", "tip_amount": "0", "total": "10",
        },
        "items": [{"name": "Чай", "qty": 1, "price": "10", "subtotal": "10"}],
        "copy": {"index": 2, "total": 3},
    }
    text = render_text_preview(payload, width=48)
    assert "КОПИЯ 2 из 3" in text


def test_receipt_template_no_copy_marker_when_single():
    from apps.printing.templates.receipt import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе"},
        "order": {
            "id": 1, "table": "1", "guests": 1,
            "waiter": "X", "cashier": "Y",
            "closed_at": "2026-05-09T12:00:00",
            "payment_method": "cash",
            "subtotal": "10", "service_charge_amount": "0",
            "discount_amount": "0", "tip_amount": "0", "total": "10",
        },
        "items": [{"name": "Чай", "qty": 1, "price": "10", "subtotal": "10"}],
    }
    text = render_text_preview(payload, width=48)
    assert "КОПИЯ" not in text


# -------- API --------


def test_get_restaurant(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.get(
        "/api/v1/restaurant/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["receipt_copies"] == 1


def test_patch_receipt_copies(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 3},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["receipt_copies"] == 3
    restaurant.refresh_from_db()
    assert restaurant.receipt_copies == 3


def test_patch_validates_range(api_client, restaurant, cashier):
    pin = _pin(api_client, cashier)
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 99},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code in (400, 422)


def test_patch_writes_audit_log(api_client, restaurant, cashier):
    from apps.audit.models import AuditAction, AuditEntry

    pin = _pin(api_client, cashier)
    api_client.patch(
        "/api/v1/restaurant/",
        {"receipt_copies": 2},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    e = AuditEntry.objects.filter(action=AuditAction.SETTINGS_UPDATE).first()
    assert e is not None
    assert "receipt_copies" in e.payload["changed"]
