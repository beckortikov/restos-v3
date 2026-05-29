"""Manager-override flow при cancel_order на сумму >= порога."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, pin: str):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": pin}, format="json"
    ).json()["data"]["session_token"]


@pytest.fixture
def manager_user(restaurant, db):
    from apps.users.models import User, UserRole

    m = User.objects.create_user(
        username="mgr1", password="x", full_name="Менеджер",
        role=UserRole.MANAGER, restaurant=restaurant,
    )
    m.set_pin("9999")
    m.save(update_fields=["pin_hash"])
    return m


def _create_big_order(restaurant, waiter, table, menu_items):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 50}],  # 50×45 = 2250
        idempotency_key=uuid4(),
    )


def test_cancel_below_threshold_no_override_needed(
    api_client, restaurant, cashier, waiter, table, menu_items, printer,
):
    """Если порог 0 (default) — override не требуется ни для одной суммы."""
    o = _create_big_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, "1234")
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/cancel/",
        {"reason": "test"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content


def test_cancel_above_threshold_requires_override(
    api_client, restaurant, cashier, waiter, table, menu_items, printer, manager_user,
):
    restaurant.manager_override_threshold_tjs = Decimal("1000")
    restaurant.save()

    o = _create_big_order(restaurant, waiter, table, menu_items)  # 2250 TJS
    pin = _pin(api_client, "1234")
    # Без X-Manager-Pin → 403
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/cancel/",
        {"reason": "test"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MANAGER_OVERRIDE_REQUIRED"


def test_cancel_above_threshold_with_valid_manager_pin(
    api_client, restaurant, cashier, waiter, table, menu_items, printer, manager_user,
):
    restaurant.manager_override_threshold_tjs = Decimal("1000")
    restaurant.save()

    o = _create_big_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, "1234")
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/cancel/",
        {"reason": "test"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_X_MANAGER_PIN="9999",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content


def test_cancel_above_threshold_with_invalid_manager_pin(
    api_client, restaurant, cashier, waiter, table, menu_items, printer, manager_user,
):
    restaurant.manager_override_threshold_tjs = Decimal("1000")
    restaurant.save()

    o = _create_big_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, "1234")
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/cancel/",
        {"reason": "test"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_X_MANAGER_PIN="0000",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MANAGER_OVERRIDE_INVALID_PIN"


def test_manager_can_cancel_above_threshold_without_override(
    api_client, restaurant, manager_user, waiter, table, menu_items, printer,
):
    """Сам менеджер может отменять без X-Manager-Pin (он сам менеджер)."""
    restaurant.manager_override_threshold_tjs = Decimal("1000")
    restaurant.save()

    o = _create_big_order(restaurant, waiter, table, menu_items)
    pin = _pin(api_client, "9999")  # PIN самого менеджера
    resp = api_client.post(
        f"/api/v1/orders/{o.id}/cancel/",
        {"reason": "test"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert resp.status_code == 200, resp.content
