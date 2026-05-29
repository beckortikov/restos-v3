"""Split bill — frame 6 backend (печать N пре-чеков)."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [
        {"menu_item_id": menu_items["plov"].id, "qty": 2},
        {"menu_item_id": menu_items["chai"].id, "qty": 1},
    ]


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def test_split_print_creates_n_jobs(
    api_client, cashier_token, restaurant, waiter, table, menu_items, printer
):
    from apps.orders.services import create_order
    from apps.printing.models import PrintJob

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=4, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    # Total: 2*45 + 1*8 = 98.00, split на 4 по 24.50 (последняя 24.50)
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/split_print/",
        {"parts": 4},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["parts"] == 4
    assert Decimal(body["share"]) == Decimal("24.50")
    assert len(body["print_jobs"]) == 4
    assert PrintJob.objects.filter(order=order).count() == 4

    # Каждый job содержит split metadata
    jobs = list(PrintJob.objects.filter(order=order).order_by("id"))
    for i, j in enumerate(jobs, start=1):
        assert j.payload.get("split", {}).get("index") == i
        assert j.payload["split"]["count"] == 4


def test_split_print_rounding_remainder_in_last(
    api_client, cashier_token, restaurant, waiter, table, menu_items, printer
):
    """3 части от 98.00: 32.67 + 32.67 + 32.66 = 98.00."""
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=3, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/split_print/",
        {"parts": 3},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    body = resp.json()["data"]
    share = Decimal(body["share"])
    last = Decimal(body["last_share"])
    assert share + share + last == Decimal("98.00")


def test_split_print_invalid_parts(
    api_client, cashier_token, restaurant, waiter, table, menu_items, printer
):
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    for parts in (0, 1, 51):
        resp = api_client.post(
            f"/api/v1/orders/{order.id}/split_print/",
            {"parts": parts},
            format="json",
            HTTP_AUTHORIZATION=f"PIN {cashier_token}",
        )
        assert resp.status_code == 422
