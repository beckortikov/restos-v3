"""Manual discount application — Phase 4 для frame 9 (PaymentDialog)."""
from decimal import Decimal
from uuid import uuid4

import pytest

from common.exceptions import BusinessError

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [
        {"menu_item_id": menu_items["plov"].id, "qty": 2},  # 2*45 = 90
        {"menu_item_id": menu_items["chai"].id, "qty": 1},  # 1*8 = 8
    ]


@pytest.fixture
def discount_percent_10(restaurant):
    """Скидка 10% (новая, кроме сидерных). Включена."""
    from apps.orders.models import Discount

    return Discount.objects.create(
        restaurant=restaurant, type="discount", name="−10%",
        kind="percent", value="10.00", is_active=True, sort_order=10,
    )


@pytest.fixture
def discount_fixed_15(restaurant):
    """Фикс 15 TJS."""
    from apps.orders.models import Discount

    return Discount.objects.create(
        restaurant=restaurant, type="discount", name="−15 TJS",
        kind="fixed", value="15.00", is_active=True, sort_order=11,
    )


def _make_order(restaurant, waiter, table, menu_items):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )


# -------- Service --------


def test_apply_percent_discount_reduces_total(
    restaurant, waiter, cashier, table, menu_items, discount_percent_10
):
    from apps.orders.services import apply_discount

    order = _make_order(restaurant, waiter, table, menu_items)
    assert order.total == Decimal("98.00")  # subtotal=98, no service in test conftest

    apply_discount(
        order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
    )
    order.refresh_from_db()
    assert order.discount_kind == "percent"
    assert order.discount_value == Decimal("10.00")
    # 10% от 98 = 9.80, total = 98 − 9.80 = 88.20
    assert order.discount_amount == Decimal("9.80")
    assert order.total == Decimal("88.20")


def test_apply_fixed_discount(
    restaurant, waiter, cashier, table, menu_items, discount_fixed_15
):
    from apps.orders.services import apply_discount

    order = _make_order(restaurant, waiter, table, menu_items)
    apply_discount(
        order_id=order.id, discount_id=discount_fixed_15.id, cashier=cashier
    )
    order.refresh_from_db()
    assert order.discount_kind == "fixed"
    assert order.discount_amount == Decimal("15.00")
    assert order.total == Decimal("83.00")  # 98 − 15


def test_remove_discount_clears_fields(
    restaurant, waiter, cashier, table, menu_items, discount_percent_10
):
    from apps.orders.services import apply_discount, remove_discount

    order = _make_order(restaurant, waiter, table, menu_items)
    apply_discount(
        order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
    )
    remove_discount(order_id=order.id, cashier=cashier)
    order.refresh_from_db()
    assert order.applied_discount is None
    assert order.discount_kind == ""
    assert order.discount_amount == Decimal("0.00")
    assert order.total == Decimal("98.00")


def test_apply_discount_blocked_for_closed_order(
    restaurant, waiter, cashier, table, menu_items, discount_percent_10, printer
):
    from apps.orders.services import apply_discount, close_order

    order = _make_order(restaurant, waiter, table, menu_items)
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")
    with pytest.raises(BusinessError) as exc:
        apply_discount(
            order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_apply_inactive_discount_blocked(
    restaurant, waiter, cashier, table, menu_items, discount_percent_10
):
    from apps.orders.services import apply_discount

    discount_percent_10.is_active = False
    discount_percent_10.save()

    order = _make_order(restaurant, waiter, table, menu_items)
    with pytest.raises(BusinessError) as exc:
        apply_discount(
            order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
        )
    assert exc.value.code == "DISCOUNT_INACTIVE"


def test_apply_service_type_discount_blocked(
    restaurant, waiter, cashier, table, menu_items
):
    """Скидку типа service применять нельзя — только discount."""
    from apps.orders.models import Discount
    from apps.orders.services import apply_discount

    svc = Discount.objects.filter(restaurant=restaurant, type="service").first()
    order = _make_order(restaurant, waiter, table, menu_items)
    with pytest.raises(BusinessError) as exc:
        apply_discount(
            order_id=order.id, discount_id=svc.id, cashier=cashier
        )
    assert exc.value.code == "DISCOUNT_NOT_FOUND"


def test_discount_snapshot_doesnt_change_when_settings_change(
    restaurant, waiter, cashier, table, menu_items, discount_percent_10
):
    """Если в настройках поменяли value скидки — уже применённая не меняется."""
    from apps.orders.services import apply_discount

    order = _make_order(restaurant, waiter, table, menu_items)
    apply_discount(
        order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
    )

    discount_percent_10.value = Decimal("50.00")  # +40% от того что было
    discount_percent_10.save()

    order.refresh_from_db()
    assert order.discount_value == Decimal("10.00")  # snapshot
    assert order.total == Decimal("88.20")  # как раньше


def test_discount_combined_with_service_charge(
    restaurant, waiter, cashier, table, menu_items, discount_percent_10
):
    """subtotal=98, service=12% (12.00 от subtotal=98 → 11.76),
    discount=10% (9.80), total = 98 + 11.76 − 9.80 = 99.96."""
    from apps.orders.models import Discount
    from apps.orders.services import apply_discount

    # Включаем service 12%
    Discount.objects.filter(restaurant=restaurant, type="service").update(
        is_active=False
    )
    Discount.objects.create(
        restaurant=restaurant, type="service", name="Svc 12",
        kind="percent", value="12.00", is_active=True, sort_order=99,
    )

    order = _make_order(restaurant, waiter, table, menu_items)
    apply_discount(
        order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
    )
    order.refresh_from_db()
    assert order.subtotal == Decimal("98.00")
    assert order.service_charge_amount == Decimal("11.76")
    assert order.discount_amount == Decimal("9.80")
    assert order.total == Decimal("99.96")


def test_fixed_discount_capped_at_subtotal(
    restaurant, waiter, cashier, table, menu_items
):
    """Фикс-скидка больше subtotal — обрезается до subtotal (total >= 0)."""
    from apps.orders.models import Discount
    from apps.orders.services import apply_discount

    big = Discount.objects.create(
        restaurant=restaurant, type="discount", name="БОЛЬШАЯ",
        kind="fixed", value="500.00", is_active=True, sort_order=20,
    )
    order = _make_order(restaurant, waiter, table, menu_items)
    apply_discount(order_id=order.id, discount_id=big.id, cashier=cashier)
    order.refresh_from_db()
    # discount_amount = subtotal (98), total = 0
    assert order.discount_amount == Decimal("98.00")
    assert order.total == Decimal("0.00")


# -------- API --------


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


def test_api_apply_discount(
    api_client, cashier_token, restaurant, waiter, cashier,
    table, menu_items, discount_percent_10,
):
    order = _make_order(restaurant, waiter, table, menu_items)
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/apply_discount/",
        {"discount_id": discount_percent_10.id},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["discount_kind"] == "percent"
    assert body["discount_amount"] == "9.80"
    assert body["total"] == "88.20"


def test_api_remove_discount(
    api_client, cashier_token, restaurant, waiter, cashier,
    table, menu_items, discount_percent_10,
):
    from apps.orders.services import apply_discount

    order = _make_order(restaurant, waiter, table, menu_items)
    apply_discount(
        order_id=order.id, discount_id=discount_percent_10.id, cashier=cashier
    )
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/remove_discount/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["discount_amount"] == "0.00"
    assert resp.json()["data"]["total"] == "98.00"


def test_api_apply_discount_missing_id(
    api_client, cashier_token, restaurant, waiter, cashier,
    table, menu_items,
):
    order = _make_order(restaurant, waiter, table, menu_items)
    resp = api_client.post(
        f"/api/v1/orders/{order.id}/apply_discount/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 422
