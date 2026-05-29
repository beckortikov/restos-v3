"""Сигналы вызывают publish() при save() на нужных моделях."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def captured_events(monkeypatch):
    events: list[tuple[str, int, dict]] = []

    def fake_publish(event_type, restaurant_id, payload):
        events.append((event_type, restaurant_id, payload))

    from apps.events import signals as sig

    monkeypatch.setattr(sig, "publish", fake_publish)
    return events


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone

    return Zone.objects.create(restaurant=restaurant, name="Зал")


@pytest.fixture
def table(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=1, name="Стол 1"
    )


def test_table_save_triggers_table_updated(captured_events, restaurant, table):
    captured_events.clear()
    table.status = "occupied"
    table.save()

    types = [e[0] for e in captured_events]
    assert "table.updated" in types
    msg = next(e for e in captured_events if e[0] == "table.updated")
    assert msg[1] == restaurant.id
    assert msg[2]["id"] == table.id
    assert msg[2]["status"] == "occupied"


def test_order_create_triggers_order_created(
    captured_events, restaurant, waiter, table
):
    from apps.menu.models import Category, MenuItem
    from apps.orders.services import create_order

    cat = Category.objects.create(restaurant=restaurant, name="C")
    mi = MenuItem.objects.create(
        restaurant=restaurant, category=cat, name="X", price=Decimal("10.00")
    )
    captured_events.clear()

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=[{"menu_item_id": mi.id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )

    types = [e[0] for e in captured_events]
    assert "order.created" in types
    order_msg = next(e for e in captured_events if e[0] == "order.created")
    assert order_msg[2]["id"] == order.id
    assert order_msg[2]["status"] == "new"
    assert order_msg[2]["table_id"] == table.id
    assert order_msg[2]["waiter_id"] == waiter.id

    # И стол тоже обновился
    assert "table.updated" in types


def test_printjob_save_triggers_print_job_updated(
    captured_events, restaurant, printer
):
    from apps.printing.models import PrintJob, PrintJobKind

    captured_events.clear()
    job = PrintJob.objects.create(
        restaurant=restaurant, printer=printer, kind=PrintJobKind.GUEST_RECEIPT,
        payload={},
    )

    types = [e[0] for e in captured_events]
    assert "print_job.updated" in types
    msg = next(e for e in captured_events if e[0] == "print_job.updated")
    assert msg[2]["id"] == job.id
    assert msg[2]["status"] == "pending"


def test_menu_save_triggers_invalidated(captured_events, restaurant):
    from apps.menu.models import Category, MenuItem

    cat = Category.objects.create(restaurant=restaurant, name="C")
    captured_events.clear()
    MenuItem.objects.create(
        restaurant=restaurant, category=cat, name="X", price=Decimal("1.00")
    )
    types = [e[0] for e in captured_events]
    assert "menu.invalidated" in types


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind

    return Printer.objects.create(
        restaurant=restaurant, name="K", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )
