"""Phase 8B — tech_cards_enabled (global) + auto_consume (per-item) toggles."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category
    return Category.objects.create(restaurant=restaurant, name="Кухня")


@pytest.fixture
def beef(restaurant):
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Говядина", unit="kg",
    )


@pytest.fixture
def plov(restaurant, category):
    from apps.menu.models import MenuItem
    return MenuItem.objects.create(
        restaurant=restaurant, category=category,
        name="Плов", price=Decimal("45"),
    )


@pytest.fixture
def printer(restaurant):
    from apps.printing.models import Printer, PrinterKind
    return Printer.objects.create(
        restaurant=restaurant, name="Касса",
        kind=PrinterKind.VIRTUAL, is_default=True, is_active=True,
    )


@pytest.fixture
def stocked_techcard(beef, plov, cashier):
    """Налить склад + создать техкарту: 1 порция плова = 0.2 кг говядины."""
    from apps.inventory.models import StockMovementKind
    from apps.inventory.services import record_movement
    from apps.menu.models import MenuItemTechCardLine

    record_movement(
        ingredient=beef, kind=StockMovementKind.PURCHASE,
        qty_delta=Decimal("10"), unit_cost=Decimal("100"), reason="init",
    )
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )


def _close_order(restaurant, waiter, cashier, plov, qty=2):
    from apps.orders.services import close_order, create_order
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": qty}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    return o


def test_global_toggle_off_skips_all_consumption(
    restaurant, waiter, cashier, plov, beef, printer, stocked_techcard,
):
    """Если restaurant.tech_cards_enabled=False — ничего не списывается."""
    restaurant.tech_cards_enabled = False
    restaurant.save(update_fields=["tech_cards_enabled"])

    _close_order(restaurant, waiter, cashier, plov, qty=2)

    beef.refresh_from_db()
    assert beef.current_qty == Decimal("10.000")  # ничего не списано


def test_global_toggle_on_consumes_normally(
    restaurant, waiter, cashier, plov, beef, printer, stocked_techcard,
):
    """По умолчанию tech_cards_enabled=True — списание работает."""
    assert restaurant.tech_cards_enabled is True
    _close_order(restaurant, waiter, cashier, plov, qty=2)

    beef.refresh_from_db()
    # 2 × 0.2 = 0.4 → осталось 9.6
    assert beef.current_qty == Decimal("9.600")


def test_per_item_auto_consume_off_skips_only_that_item(
    restaurant, waiter, cashier, plov, beef, printer, stocked_techcard,
):
    """Если у конкретного блюда auto_consume=False — оно не списывает."""
    plov.auto_consume = False
    plov.save(update_fields=["auto_consume"])

    _close_order(restaurant, waiter, cashier, plov, qty=2)

    beef.refresh_from_db()
    assert beef.current_qty == Decimal("10.000")  # не списано


def test_per_item_overrides_only_self_not_others(
    restaurant, waiter, cashier, category, beef, printer,
):
    """auto_consume=False у одного блюда не блокирует другие."""
    from apps.inventory.models import StockMovementKind
    from apps.inventory.services import record_movement
    from apps.menu.models import MenuItem, MenuItemTechCardLine
    from apps.orders.services import close_order, create_order

    record_movement(
        ingredient=beef, kind=StockMovementKind.PURCHASE,
        qty_delta=Decimal("10"), unit_cost=Decimal("100"), reason="init",
    )

    plov_skip = MenuItem.objects.create(
        restaurant=restaurant, category=category,
        name="Плов (без склада)", price=Decimal("45"),
        auto_consume=False,
    )
    MenuItemTechCardLine.objects.create(
        menu_item=plov_skip, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )

    plov_normal = MenuItem.objects.create(
        restaurant=restaurant, category=category,
        name="Плов (со складом)", price=Decimal("45"),
    )
    MenuItemTechCardLine.objects.create(
        menu_item=plov_normal, ingredient=beef, qty_per_unit=Decimal("0.3"),
    )

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[
            {"menu_item_id": plov_skip.id, "qty": 5},     # должен пропустить
            {"menu_item_id": plov_normal.id, "qty": 2},   # должен списать 0.6
        ],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    beef.refresh_from_db()
    # Списано только plov_normal: 2 × 0.3 = 0.6 → осталось 9.4
    assert beef.current_qty == Decimal("9.400")
