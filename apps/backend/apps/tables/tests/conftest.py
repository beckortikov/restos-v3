"""Shared fixtures for tables tests (menu_items, printer needed by merge tests
that exercise the create_order/close_order flow).
"""
from decimal import Decimal

import pytest


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
    return {"plov": plov}


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind

    return Printer.objects.create(
        restaurant=restaurant, name="Касса", kind=PrinterKind.VIRTUAL,
        is_default=True, is_active=True,
    )
