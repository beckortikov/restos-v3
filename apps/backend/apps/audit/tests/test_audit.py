"""Audit log: запись через сервис, hooks в order/shift/user, API list."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [{"menu_item_id": menu_items["plov"].id, "qty": 1}]


# -------- Service --------


def test_audit_log_basic(restaurant, cashier):
    from apps.audit.models import AuditEntry
    from apps.audit.services import audit_log

    entry = audit_log(
        cashier, "login", payload={"x": 1}, restaurant=restaurant
    )
    assert entry is not None
    assert entry.action == "login"
    assert entry.user_id == cashier.id
    assert entry.user_full_name == cashier.full_name
    assert entry.payload == {"x": 1}
    assert AuditEntry.objects.filter(restaurant=restaurant).count() == 1


def test_audit_log_with_target(restaurant, waiter, table, menu_items):
    from apps.audit.models import AuditEntry
    from apps.audit.services import audit_log
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    # create_order сам пишет audit, но проверим явно
    e = AuditEntry.objects.filter(
        action="order_create", target_type="Order", target_id=order.id
    ).first()
    assert e is not None
    assert e.payload.get("items_count") == 1


def test_audit_log_no_restaurant_returns_none(db):
    """Если ни в user, ни в target нет restaurant — log не пишется."""
    from apps.audit.services import audit_log

    e = audit_log(None, "login")
    assert e is None


# -------- Hooks integration --------


def test_order_lifecycle_creates_audit_entries(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.audit.models import AuditEntry
    from apps.orders.services import (
        cancel_item, close_order, create_order,
    )

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2},
            {"menu_item_id": menu_items["chai"].id, "qty": 1},
        ],
        comment="", idempotency_key=uuid4(),
    )

    item = order.items.first()
    cancel_item(
        order_id=order.id, item_id=item.id, user=cashier, reason="ошибка",
    )
    close_order(
        order_id=order.id, cashier=cashier, payment_method="cash",
    )

    actions = list(
        AuditEntry.objects.filter(
            restaurant=restaurant, target_type="Order", target_id=order.id,
        ).values_list("action", flat=True)
    )
    assert "order_create" in actions
    assert "item_cancel" in actions
    assert "order_close" in actions


def test_shift_open_close_audit(restaurant, cashier):
    from apps.audit.models import AuditEntry
    from apps.shifts.services import close_shift, open_shift

    shift = open_shift(
        restaurant=restaurant, cashier=cashier, opening_balance=Decimal("100"),
    )
    close_shift(
        shift_id=shift.id, restaurant=restaurant,
        actual_balance=Decimal("100"), note="OK",
    )
    actions = list(
        AuditEntry.objects.filter(
            target_type="CashShift", target_id=shift.id,
        ).values_list("action", flat=True)
    )
    assert "shift_open" in actions
    assert "shift_close" in actions


def test_login_audit(api_client, cashier):
    from apps.audit.models import AuditEntry

    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    )
    assert resp.status_code == 200
    assert AuditEntry.objects.filter(
        action="login", user=cashier
    ).exists()


def test_discount_apply_remove_audit(
    restaurant, waiter, cashier, table, menu_items
):
    from apps.audit.models import AuditEntry
    from apps.orders.models import Discount
    from apps.orders.services import apply_discount, create_order, remove_discount

    disc = Discount.objects.create(
        restaurant=restaurant, type="discount", name="−10%",
        kind="percent", value="10.00", is_active=True, sort_order=10,
    )
    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    apply_discount(order_id=order.id, discount_id=disc.id, cashier=cashier)
    remove_discount(order_id=order.id, cashier=cashier)
    actions = list(
        AuditEntry.objects.filter(
            target_type="Order", target_id=order.id,
        ).values_list("action", flat=True)
    )
    assert "discount_apply" in actions
    assert "discount_remove" in actions


# -------- API --------


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def test_list_audit(api_client, cashier_token, restaurant, cashier):
    from apps.audit.services import audit_log

    audit_log(cashier, "shift_open", restaurant=restaurant)
    audit_log(cashier, "order_create", restaurant=restaurant)

    resp = api_client.get(
        "/api/v1/audit/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    # login_audit auto-created on PIN auth + наши 2 + login
    assert body["meta"]["total"] >= 3


def test_list_audit_filter_by_action(api_client, cashier_token, restaurant, cashier):
    from apps.audit.services import audit_log

    audit_log(cashier, "shift_open", restaurant=restaurant)
    audit_log(cashier, "order_create", restaurant=restaurant)
    audit_log(cashier, "order_create", restaurant=restaurant)

    resp = api_client.get(
        "/api/v1/audit/?action=order_create",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(d["action"] == "order_create" for d in data)
    assert len(data) == 2


def test_audit_cross_tenant_isolation(api_client, cashier, cashier_token):
    from apps.audit.models import AuditEntry
    from apps.audit.services import audit_log
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Other", currency="USD")
    audit_log(None, "login", restaurant=other)
    other_entry = AuditEntry.objects.filter(restaurant=other).first()
    assert other_entry is not None

    resp = api_client.get(
        "/api/v1/audit/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    ids = {e["id"] for e in resp.json()["data"]}
    assert other_entry.id not in ids


def test_audit_waiter_forbidden(api_client, cashier, waiter):
    """Audit log читает только кассир (compliance)."""
    login = api_client.post(
        "/api/v1/auth/login/",
        {"username": "waiter1", "password": "waiter-pass"},
        format="json",
    ).json()
    access = login["data"]["access"]
    resp = api_client.get(
        "/api/v1/audit/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 403


def test_audit_no_write_endpoints(api_client, cashier_token):
    """Журнал не может быть изменён через API — только список."""
    # POST 405
    resp = api_client.post(
        "/api/v1/audit/",
        {"action": "fake"},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code in (405, 403)
