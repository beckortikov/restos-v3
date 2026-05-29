"""Повторная печать чека из истории (frame 12 — История заказов)."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [
        {"menu_item_id": menu_items["plov"].id, "qty": 1},
    ]


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


@pytest.fixture
def closed_order(restaurant, waiter, table, menu_items, printer):
    from apps.orders.models import OrderStatus
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(
        order_id=order.id, payment_method="cash", cashier=waiter,
    )
    order.refresh_from_db()
    assert order.status == OrderStatus.DONE
    return order


def test_reprint_creates_print_job(
    api_client, cashier_token, closed_order
):
    from apps.printing.models import PrintJob

    before = PrintJob.objects.filter(order=closed_order).count()
    resp = api_client.post(
        f"/api/v1/orders/{closed_order.id}/reprint_receipt/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content
    after_jobs = PrintJob.objects.filter(order=closed_order)
    assert after_jobs.count() == before + 1
    j = after_jobs.order_by("-id").first()
    assert j.payload.get("duplicate") is True


def test_reprint_marks_duplicate_in_text(
    api_client, cashier_token, closed_order
):
    from apps.printing.models import PrintJob
    from apps.printing.templates.receipt import render_text_preview

    api_client.post(
        f"/api/v1/orders/{closed_order.id}/reprint_receipt/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    j = PrintJob.objects.filter(order=closed_order).order_by("-id").first()
    text = render_text_preview(j.payload)
    assert "ДУБЛИКАТ" in text


def test_reprint_rejects_open_order(
    api_client, cashier_token, restaurant, waiter, table, menu_items, printer
):
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/reprint_receipt/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"


def test_reprint_404_other_restaurant(api_client, cashier_token, closed_order):
    """Повторная печать чужого заказа → 404."""
    resp = api_client.post(
        f"/api/v1/orders/{closed_order.id + 99999}/reprint_receipt/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 404


def test_reprint_writes_audit_log(
    api_client, cashier_token, closed_order
):
    from apps.audit.models import AuditEntry

    api_client.post(
        f"/api/v1/orders/{closed_order.id}/reprint_receipt/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    e = AuditEntry.objects.filter(
        payload__action="reprint_receipt"
    ).first()
    assert e is not None
    assert e.payload["order_id"] == closed_order.id
