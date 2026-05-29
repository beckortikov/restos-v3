"""Phase 7C: MenuItemTechCard + auto-consume на close_order + auto-recalc cogs."""
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_token(api_client, cashier):
    resp = api_client.post(
        "/api/v1/auth/pin/", {"pin": "1234"}, format="json"
    ).json()
    return resp["data"]["session_token"]


@pytest.fixture
def beef(restaurant):
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Говядина", unit="kg",
    )


@pytest.fixture
def onion(restaurant):
    from apps.inventory.models import Ingredient
    return Ingredient.objects.create(
        restaurant=restaurant, name="Лук", unit="kg",
    )


@pytest.fixture
def category(restaurant):
    from apps.menu.models import Category
    return Category.objects.create(restaurant=restaurant, name="Кухня")


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


def _stock(ing, qty, cost, user):
    """Helper: налить ingredient + установить cost."""
    from apps.inventory.services import record_movement

    record_movement(
        ingredient=ing, kind="purchase",
        qty_delta=qty, unit_cost=cost, user=user,
    )


# -------- recalc_menu_item_cogs --------


def test_recalc_cogs_from_techcard(plov, beef, onion, cashier):
    """cogs = Σ qty_per_unit × avg_cost_per_unit."""
    from apps.inventory.services import recalc_menu_item_cogs
    from apps.menu.models import MenuItemTechCardLine

    _stock(beef, 10, Decimal("100"), cashier)  # 100 за кг
    _stock(onion, 5, Decimal("20"), cashier)   # 20 за кг

    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.150"),
    )
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=onion, qty_per_unit=Decimal("0.050"),
    )
    # cogs = 0.150 × 100 + 0.050 × 20 = 15 + 1 = 16
    plov.refresh_from_db()
    # signal должен был пересчитать сам
    assert plov.cogs == Decimal("16.00")

    # Прямой вызов даёт то же
    assert recalc_menu_item_cogs(plov) == Decimal("16.00")


def test_signal_recalc_on_line_save(plov, beef, cashier):
    """post_save / post_delete signal автоматически пересчитывает cogs."""
    from apps.menu.models import MenuItemTechCardLine

    _stock(beef, 10, Decimal("100"), cashier)

    line = MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )
    plov.refresh_from_db()
    assert plov.cogs == Decimal("20.00")  # 0.2 × 100

    # Изменяем
    line.qty_per_unit = Decimal("0.3")
    line.save()
    plov.refresh_from_db()
    assert plov.cogs == Decimal("30.00")

    # Удаление → возвращаемся к 0
    line.delete()
    plov.refresh_from_db()
    assert plov.cogs == Decimal("0.00")


def test_recalc_with_semi_finished(restaurant, category, beef, cashier):
    """Если в техкарте semi — берём avg_cost полуфабриката."""
    from apps.inventory.models import (
        SemiFinishedRecipeLine,
        SemiFinishedType,
    )
    from apps.inventory.services import produce_semi
    from apps.menu.models import MenuItem, MenuItemTechCardLine

    _stock(beef, 10, Decimal("100"), cashier)

    # Делаем «Фарш» avg=100 за 1 кг
    farsh = SemiFinishedType.objects.create(
        restaurant=restaurant, name="Фарш", output_unit="kg",
        yield_percent=Decimal("100"),
    )
    SemiFinishedRecipeLine.objects.create(
        semi_type=farsh, ingredient=beef, qty_per_output=Decimal("1"),
    )
    produce_semi(semi_type=farsh, qty=Decimal("3"), user=cashier)
    farsh.refresh_from_db()
    assert farsh.avg_cost_per_unit == Decimal("100.0000")

    # Манты с фаршем — 0.1 кг фарша на 1 порцию
    manty = MenuItem.objects.create(
        restaurant=restaurant, category=category,
        name="Манты", price=Decimal("30"),
    )
    MenuItemTechCardLine.objects.create(
        menu_item=manty, nested_semi=farsh, qty_per_unit=Decimal("0.1"),
    )
    manty.refresh_from_db()
    assert manty.cogs == Decimal("10.00")  # 0.1 × 100


# -------- consume_for_order_close: auto-consume --------


def test_consume_for_order_close(
    restaurant, waiter, cashier, plov, beef, onion, printer,
):
    """Закрытие заказа списывает ингредиенты по техкарте."""
    from apps.menu.models import MenuItemTechCardLine
    from apps.orders.services import close_order, create_order

    _stock(beef, 10, Decimal("100"), cashier)
    _stock(onion, 5, Decimal("20"), cashier)
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=onion, qty_per_unit=Decimal("0.05"),
    )

    # Заказ на 3 порции
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 3}],
        idempotency_key=uuid4(),
    )
    # Phase 8E — списание происходит СРАЗУ на create_order, а не на close.
    # 3 × 0.2 = 0.6 говядины, 3 × 0.05 = 0.15 лука
    beef.refresh_from_db()
    onion.refresh_from_db()
    assert beef.current_qty == Decimal("9.400")
    assert onion.current_qty == Decimal("4.850")

    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    # После close: ничего нового не списано (consumed_at != null)
    beef.refresh_from_db()
    onion.refresh_from_db()
    assert beef.current_qty == Decimal("9.400")
    assert onion.current_qty == Decimal("4.850")


def test_no_techcard_no_consume(
    restaurant, waiter, cashier, plov, printer,
):
    """Если у блюда нет техкарты — заказ закрывается без списания, без ошибок."""
    from apps.orders.services import close_order, create_order

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    # Не упало → ок
    o.refresh_from_db()
    assert o.status == "done"


def test_insufficient_stock_blocks_close(
    restaurant, waiter, cashier, plov, beef, printer,
):
    """Если ingredient'а не хватает — close_order падает с INSUFFICIENT_STOCK."""
    from apps.menu.models import MenuItemTechCardLine
    from apps.orders.services import close_order, create_order
    from common.exceptions import BusinessError

    _stock(beef, 1, Decimal("100"), cashier)  # 1 кг только
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.5"),
    )

    # 3 порции = 1.5 кг говядины, а есть 1 кг
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 3}],
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        close_order(order_id=o.id, cashier=cashier, payment_method="cash")
    assert exc.value.code == "INSUFFICIENT_STOCK"
    # Заказ НЕ закрыт — атомарность
    o.refresh_from_db()
    assert o.status != "done"
    # Склад не тронут
    beef.refresh_from_db()
    assert beef.current_qty == Decimal("1.000")


def test_cancelled_items_not_consumed(
    restaurant, waiter, cashier, plov, beef, printer,
):
    """Отменённые позиции не списываются со склада."""
    from apps.menu.models import MenuItemTechCardLine
    from apps.orders.services import (
        cancel_item,
        close_order,
        create_order,
    )

    _stock(beef, 5, Decimal("100"), cashier)
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )
    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 5}],
        idempotency_key=uuid4(),
    )
    # Отменим саму позицию полностью
    item = o.items.first()
    cancel_item(
        order_id=o.id, item_id=item.id, user=cashier,
        reason="Передумали",
    )

    # Заказ закрыть нельзя — пустой, поэтому создадим новый
    o2 = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": plov.id, "qty": 2}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o2.id, cashier=cashier, payment_method="cash")
    beef.refresh_from_db()
    # 5 − 2 × 0.2 = 4.6 (отменённые не списаны)
    assert beef.current_qty == Decimal("4.600")


def test_consume_with_semi(
    restaurant, waiter, cashier, category, beef, printer,
):
    """Техкарта может использовать nested_semi — списываем из semi-склада."""
    from apps.inventory.models import (
        SemiFinishedRecipeLine,
        SemiFinishedType,
    )
    from apps.inventory.services import produce_semi
    from apps.menu.models import MenuItem, MenuItemTechCardLine
    from apps.orders.services import close_order, create_order

    _stock(beef, 10, Decimal("100"), cashier)
    farsh = SemiFinishedType.objects.create(
        restaurant=restaurant, name="Фарш", output_unit="kg",
        yield_percent=Decimal("100"),
    )
    SemiFinishedRecipeLine.objects.create(
        semi_type=farsh, ingredient=beef, qty_per_output=Decimal("1"),
    )
    produce_semi(semi_type=farsh, qty=Decimal("5"), user=cashier)
    farsh.refresh_from_db()
    assert farsh.current_qty == Decimal("5.000")

    manty = MenuItem.objects.create(
        restaurant=restaurant, category=category,
        name="Манты", price=Decimal("30"),
    )
    MenuItemTechCardLine.objects.create(
        menu_item=manty, nested_semi=farsh, qty_per_unit=Decimal("0.1"),
    )

    o = create_order(
        restaurant=restaurant, waiter=waiter,
        order_type="takeaway", guests_count=1,
        items_data=[{"menu_item_id": manty.id, "qty": 10}],
        idempotency_key=uuid4(),
    )
    close_order(order_id=o.id, cashier=cashier, payment_method="cash")

    farsh.refresh_from_db()
    # 5 − 10 × 0.1 = 4.0
    assert farsh.current_qty == Decimal("4.000")


# -------- API tech card endpoint --------


def test_get_tech_card(api_client, cashier_token, plov, beef, cashier):
    from apps.menu.models import MenuItemTechCardLine

    _stock(beef, 5, Decimal("100"), cashier)
    MenuItemTechCardLine.objects.create(
        menu_item=plov, ingredient=beef, qty_per_unit=Decimal("0.2"),
    )
    resp = api_client.get(
        f"/api/v1/menu/items/{plov.id}/tech_card/",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["meta"]["cogs"] == "20.00"


def test_put_tech_card_replaces_all(
    api_client, cashier_token, plov, beef, onion, cashier,
):
    """PUT — полная замена техкарты, cogs пересчитан сразу."""
    _stock(beef, 10, Decimal("100"), cashier)
    _stock(onion, 5, Decimal("20"), cashier)

    resp = api_client.put(
        f"/api/v1/menu/items/{plov.id}/tech_card/",
        {
            "lines": [
                {"ingredient": beef.id, "qty_per_unit": "0.15", "sort_order": 0},
                {"ingredient": onion.id, "qty_per_unit": "0.05", "sort_order": 1},
            ],
        },
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 200, resp.content
    # 0.15 × 100 + 0.05 × 20 = 15 + 1 = 16
    plov.refresh_from_db()
    assert plov.cogs == Decimal("16.00")
    assert plov.tech_card_lines.count() == 2

    # Повторный PUT с другими строками — старые удаляются
    resp2 = api_client.put(
        f"/api/v1/menu/items/{plov.id}/tech_card/",
        {"lines": [{"ingredient": beef.id, "qty_per_unit": "0.3"}]},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp2.status_code == 200
    plov.refresh_from_db()
    assert plov.tech_card_lines.count() == 1
    assert plov.cogs == Decimal("30.00")


def test_put_tech_card_validates_components(
    api_client, cashier_token, plov, beef,
):
    """Нельзя одновременно ingredient И nested_semi, и нельзя без обоих."""
    # Оба пусты
    resp = api_client.put(
        f"/api/v1/menu/items/{plov.id}/tech_card/",
        {"lines": [{"qty_per_unit": "0.1"}]},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400


def test_put_tech_card_rejects_cross_restaurant_ingredient(
    api_client, cashier_token, plov,
):
    from apps.inventory.models import Ingredient
    from apps.users.models import Restaurant

    other = Restaurant.objects.create(name="Чужой", currency="TJS")
    other_ing = Ingredient.objects.create(
        restaurant=other, name="Чужая мука", unit="kg",
    )
    resp = api_client.put(
        f"/api/v1/menu/items/{plov.id}/tech_card/",
        {"lines": [{"ingredient": other_ing.id, "qty_per_unit": "0.1"}]},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {cashier_token}",
    )
    assert resp.status_code == 400
