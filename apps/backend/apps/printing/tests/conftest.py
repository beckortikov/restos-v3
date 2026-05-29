from decimal import Decimal
from uuid import uuid4

import pytest


@pytest.fixture
def zone(restaurant):
    from apps.tables.models import Zone

    return Zone.objects.create(restaurant=restaurant, name="Зал", sort_order=1)


@pytest.fixture
def table(restaurant, zone):
    from apps.tables.models import Table

    return Table.objects.create(
        restaurant=restaurant, zone=zone, number=1, name="Стол 1", capacity=4
    )


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category

    return Category.objects.create(restaurant=restaurant, name="Горячее", sort_order=1)


@pytest.fixture
def menu_items(restaurant, category):
    from apps.menu.models import MenuItem

    plov = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Плов",
        price=Decimal("45.00"), sort_order=1,
    )
    chai = MenuItem.objects.create(
        restaurant=restaurant, category=category, name="Чай",
        price=Decimal("8.00"), sort_order=2,
    )
    return {"plov": plov, "chai": chai}


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind

    return Printer.objects.create(
        restaurant=restaurant, name="Касса", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )


@pytest.fixture
def closed_order(restaurant, waiter, cashier, table, menu_items, printer):
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2},
            {"menu_item_id": menu_items["chai"].id, "qty": 1},
        ],
        comment="", idempotency_key=uuid4(),
    )
    closed, job = close_order(
        order_id=order.id, cashier=cashier, payment_method="cash"
    )
    return closed, job
