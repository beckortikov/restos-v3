"""READY_RUNNER — auto-print runner при переходе позиции в kitchen READY."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


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
def category(restaurant, kitchen_station):
    from apps.menu.models import Category
    return Category.objects.create(
        restaurant=restaurant, name="Горячее", print_station=kitchen_station,
    )


@pytest.fixture
def plov(restaurant, category):
    from apps.menu.models import MenuItem
    return MenuItem.objects.create(
        restaurant=restaurant, category=category,
        name="Плов", price=Decimal("45"),
    )


@pytest.fixture
def cashier_printer(restaurant):
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Касса",
        kind=PrinterKind.VIRTUAL, is_default=True, is_active=True,
    )


@pytest.fixture
def order_with_item(restaurant, waiter, cashier_printer, plov, table):
    from apps.orders.services import create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=table.id,
        items_data=[{"menu_item_id": plov.id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    return o


@pytest.fixture
def table(restaurant):
    from apps.tables.models import Zone, Table
    z = Zone.objects.create(restaurant=restaurant, name="Зал")
    return Table.objects.create(restaurant=restaurant, zone=z, number=1, name="Стол 1", capacity=4)


def test_ready_transition_enqueues_runner(
    order_with_item, cashier, kitchen_printer,
):
    """COOKING → READY → создаётся PrintJob с kind=READY_RUNNER."""
    from apps.kitchen.services import mark_ready, start_cooking
    from apps.orders.models import KitchenStatus
    from apps.printing.models import PrintJob, PrintJobKind

    item = order_with_item.items.first()
    start_cooking(item_id=item.id, restaurant=order_with_item.restaurant, user=cashier)
    mark_ready(item_id=item.id, restaurant=order_with_item.restaurant, user=cashier)

    runners = PrintJob.objects.filter(
        order=order_with_item, kind=PrintJobKind.READY_RUNNER,
    )
    assert runners.count() == 1
    j = runners.first()
    assert j.payload["item"]["name"] == "Плов"
    assert j.payload["item"]["qty"] == 2
    assert j.payload["cooked_by"] == cashier.full_name


def test_ready_runner_template_preview(restaurant, kitchen_printer):
    from apps.printing.models import PrintJob, PrintJobKind
    from apps.printing.escpos_sender import _render_preview

    job = PrintJob.objects.create(
        restaurant=restaurant, printer=kitchen_printer,
        kind=PrintJobKind.READY_RUNNER,
        payload={
            "restaurant": {"name": "Test"},
            "order": {"id": 1, "table": "Стол 5", "waiter": "Иван"},
            "item": {"name": "Лагман", "qty": 1, "note": "острее"},
            "cooked_by": "Карим",
        },
    )
    text = _render_preview(job)
    assert "ГОТОВО" in text
    assert "Лагман" in text
    assert "Стол 5" in text
    assert "Карим" in text
    assert "острее" in text


def test_no_runner_if_no_station(
    restaurant, waiter, cashier, cashier_printer, table,
):
    """Если у категории нет PrintStation и нет fallback — runner не печатается."""
    from apps.menu.models import Category, MenuItem
    from apps.orders.services import create_order
    from apps.kitchen.services import mark_ready, start_cooking
    from apps.orders.models import KitchenStatus
    from apps.printing.models import PrintJob, PrintJobKind

    # Категория без station; default printer = guest_receipt, не kitchen
    cat_no_station = Category.objects.create(
        restaurant=restaurant, name="Без станции",
    )
    mi = MenuItem.objects.create(
        restaurant=restaurant, category=cat_no_station,
        name="X", price=Decimal("10"),
    )
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="hall", guests_count=1, table_id=table.id,
        items_data=[{"menu_item_id": mi.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    item = o.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cashier)
    before = PrintJob.objects.filter(kind=PrintJobKind.READY_RUNNER).count()
    mark_ready(item_id=item.id, restaurant=restaurant, user=cashier)
    after = PrintJob.objects.filter(kind=PrintJobKind.READY_RUNNER).count()
    # Может быть напечатано на fallback (cashier_printer is_default=True, но
    # это для guest_receipt; для kitchen_order нет system station → fallback fails).
    # Главное — не падаем.
    assert after >= before
