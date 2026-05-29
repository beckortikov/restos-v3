"""Phase 4 — fire_kitchen: «дозаказ → НА КУХНЮ»."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def category_kitchen(restaurant, kitchen_station):
    from apps.menu.models import Category
    return Category.objects.create(
        restaurant=restaurant, name="Горячее", print_station=kitchen_station,
    )


@pytest.fixture
def kitchen_printer(restaurant):
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Кухня",
        kind=PrinterKind.VIRTUAL, is_active=True,
    )


@pytest.fixture
def kitchen_station(restaurant, kitchen_printer):
    from apps.printing.models import PrintStation
    return PrintStation.objects.create(
        restaurant=restaurant, name="Кухня",
        printer=kitchen_printer, is_active=True,
    )


@pytest.fixture
def cashier_printer(restaurant):
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Касса",
        kind=PrinterKind.VIRTUAL, is_default=True, is_active=True,
    )


@pytest.fixture
def items(restaurant, category_kitchen):
    from apps.menu.models import MenuItem
    return {
        "plov": MenuItem.objects.create(
            restaurant=restaurant, category=category_kitchen,
            name="Плов", price=Decimal("45"),
        ),
        "lagman": MenuItem.objects.create(
            restaurant=restaurant, category=category_kitchen,
            name="Лагман", price=Decimal("40"),
        ),
    }


# ─── Initial create_order marks sent_to_kitchen_at ──────────────────────────


def test_create_order_marks_items_sent(
    restaurant, waiter, cashier_printer, items,
):
    from apps.orders.services import create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    item = o.items.first()
    assert item.sent_to_kitchen_at is not None


# ─── add_items leaves new items unsent ──────────────────────────────────────


def test_add_items_auto_fires_kitchen(
    restaurant, waiter, cashier_printer, items,
):
    """Дозаказ (add_items_to_order) автоматически печатает новые позиции на кухню."""
    from apps.orders.services import add_items_to_order, create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    add_items_to_order(
        order_id=o.id, waiter=waiter,
        items_data=[{"menu_item_id": items["lagman"].id, "qty": 1}],
    )
    # Обе позиции после add_items должны иметь sent_to_kitchen_at (авто-fire).
    lagman_oi = o.items.filter(menu_item=items["lagman"]).first()
    assert lagman_oi.sent_to_kitchen_at is not None
    plov_oi = o.items.filter(menu_item=items["plov"]).first()
    assert plov_oi.sent_to_kitchen_at is not None


# ─── fire_kitchen sends only unsent items ───────────────────────────────────


def test_fire_kitchen_endpoint_idempotent(
    restaurant, waiter, cashier, cashier_printer, items,
):
    """fire_kitchen остаётся как API на случай ручного re-fire,
    но после add_items авто-печать уже сработала — повторный вызов
    возвращает items_sent=0."""
    from apps.orders.services import (
        add_items_to_order, create_order, fire_kitchen,
    )

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    add_items_to_order(
        order_id=o.id, waiter=waiter,
        items_data=[{"menu_item_id": items["lagman"].id, "qty": 2}],
    )
    # После add_items всё уже на кухне — fire_kitchen findит 0.
    result = fire_kitchen(order_id=o.id, user=cashier)
    assert result == {"items_sent": 0, "jobs_count": 0}


def test_fire_kitchen_no_unsent_returns_zero(
    restaurant, waiter, cashier, cashier_printer, items,
):
    """Если все позиции уже отправлены — fire_kitchen возвращает 0/0."""
    from apps.orders.services import create_order, fire_kitchen

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    result = fire_kitchen(order_id=o.id, user=cashier)
    assert result == {"items_sent": 0, "jobs_count": 0}


def test_fire_kitchen_rejects_closed_order(
    restaurant, waiter, cashier, cashier_printer, items,
):
    from apps.orders.services import close_order, create_order, fire_kitchen
    from common.exceptions import BusinessError

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    with pytest.raises(BusinessError) as exc:
        fire_kitchen(order_id=o.id, user=cashier)
    assert exc.value.code == "INVALID_TRANSITION"


# ─── API endpoint ───────────────────────────────────────────────────────────


def test_fire_kitchen_api(
    api_client, cashier, restaurant, waiter, cashier_printer, items,
):
    """fire_kitchen API остаётся доступным (для возможного manual-trigger)."""
    from apps.orders.services import create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    api_client.force_authenticate(user=cashier)
    resp = api_client.post(f"/api/v1/orders/{o.id}/fire_kitchen/", {}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    # После create_order всё уже отправлено → 0 несрафкированных.
    assert body["items_sent"] == 0
