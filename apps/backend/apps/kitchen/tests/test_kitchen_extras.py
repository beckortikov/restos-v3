"""Доп. функционал KDS: cancel-runner, station filter, auto-ready."""
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db


def _pin(api_client, pin: str):
    return api_client.post(
        "/api/v1/auth/pin/", {"pin": pin}, format="json"
    ).json()["data"]["session_token"]


def _create_order(restaurant, waiter, table, menu_items):
    from apps.orders.services import create_order

    return create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2,
        items_data=[
            {"menu_item_id": menu_items["plov"].id, "qty": 2},
            {"menu_item_id": menu_items["chai"].id, "qty": 1},
        ],
        idempotency_key=uuid4(),
    )


# -------- Cancel runner --------


def test_cancel_runner_printed_when_item_was_cooking(
    restaurant, waiter, cook, table, menu_items, printer,
):
    """Если кухня уже взяла позицию (COOKING) — при cancel_item печатается бегунок."""
    from apps.kitchen.services import start_cooking
    from apps.orders.services import cancel_item
    from apps.printing.models import PrintJob, PrintJobKind

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)

    cancel_item(
        order_id=order.id, item_id=item.id, user=waiter, reason="клиент передумал",
    )
    assert PrintJob.objects.filter(
        kind=PrintJobKind.CANCEL_RUNNER, order=order,
    ).count() == 1


def test_cancel_runner_not_printed_for_new_item(
    restaurant, waiter, cook, table, menu_items, printer,
):
    """Если позиция NEW — кухня её не видела, бегунок не нужен."""
    from apps.orders.services import cancel_item
    from apps.printing.models import PrintJob, PrintJobKind

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    # Сразу отменяем без start_cooking
    cancel_item(
        order_id=order.id, item_id=item.id, user=waiter, reason="ошибка",
    )
    assert not PrintJob.objects.filter(
        kind=PrintJobKind.CANCEL_RUNNER,
    ).exists()


def test_cancel_runner_printed_when_item_was_ready(
    restaurant, waiter, cook, table, menu_items, printer,
):
    from apps.kitchen.services import mark_ready, start_cooking
    from apps.orders.services import cancel_item
    from apps.printing.models import PrintJob, PrintJobKind

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    mark_ready(item_id=item.id, restaurant=restaurant, user=cook)

    cancel_item(
        order_id=order.id, item_id=item.id, user=waiter, reason="r",
    )
    assert PrintJob.objects.filter(
        kind=PrintJobKind.CANCEL_RUNNER,
    ).count() == 1


def test_cancel_runner_payload_contains_item_and_reason(
    restaurant, waiter, cook, table, menu_items, printer,
):
    from apps.kitchen.services import start_cooking
    from apps.orders.services import cancel_item
    from apps.printing.models import PrintJob, PrintJobKind

    order = _create_order(restaurant, waiter, table, menu_items)
    item = order.items.first()
    start_cooking(item_id=item.id, restaurant=restaurant, user=cook)
    cancel_item(
        order_id=order.id, item_id=item.id, user=waiter,
        reason="ошибка кассира",
    )
    job = PrintJob.objects.filter(kind=PrintJobKind.CANCEL_RUNNER).first()
    assert job is not None
    assert job.payload["item"]["name"] == item.name_at_order
    assert job.payload["item"]["qty"] == item.qty
    assert job.payload["reason"] == "ошибка кассира"


def test_cancel_runner_template_renders():
    from apps.printing.templates.cancel_runner import render_text_preview

    payload = {
        "restaurant": {"name": "Кафе"},
        "order": {"id": 1, "table": "5", "waiter": "Иван"},
        "item": {"name": "Плов", "qty": 2, "note": "Без лука"},
        "cancelled_by": "Кассир Анна",
        "reason": "клиент передумал",
    }
    text = render_text_preview(payload, width=48)
    assert "ОТМЕНА" in text
    assert "Плов" in text
    assert "×2" in text
    assert "Без лука" in text
    assert "клиент передумал" in text


# -------- Station filter --------


@pytest.fixture
def station_hot(restaurant):
    from apps.printing.models import PrintStation

    return PrintStation.objects.create(
        restaurant=restaurant, name="Горячий цех", system_code="kitchen",
        is_active=True,
    )


@pytest.fixture
def station_bar(restaurant):
    from apps.printing.models import PrintStation

    return PrintStation.objects.create(
        restaurant=restaurant, name="Бар", system_code="",
        is_active=True,
    )


def test_list_filter_by_station(
    restaurant, waiter, cook, table, menu_items, station_hot, station_bar,
):
    """Только позиции категорий привязанных к станции — попадают в список."""
    from apps.kitchen.services import list_kitchen_items
    from apps.menu.models import Category

    # plov в категории «Горячее» (default fixture). Привязываем к hot.
    plov_cat = menu_items["plov"].category
    plov_cat.print_station = station_hot
    plov_cat.save()
    # chai — в той же категории. Перенесём в barcat
    bar_cat = Category.objects.create(
        restaurant=restaurant, name="Напитки", print_station=station_bar,
    )
    chai = menu_items["chai"]
    chai.category = bar_cat
    chai.save()

    _create_order(restaurant, waiter, table, menu_items)

    qs_hot = list(list_kitchen_items(restaurant, station=station_hot))
    qs_bar = list(list_kitchen_items(restaurant, station=station_bar))

    assert all(i.menu_item.name == "Плов" for i in qs_hot)
    assert all(i.menu_item.name == "Чай" for i in qs_bar)


def test_endpoint_uses_cook_kitchen_station(
    api_client, restaurant, waiter, cook, table, menu_items,
    station_hot, station_bar,
):
    """Если cook.kitchen_station=hot, GET /kitchen/items/ возвращает только hot."""
    from apps.menu.models import Category

    plov_cat = menu_items["plov"].category
    plov_cat.print_station = station_hot
    plov_cat.save()
    bar_cat = Category.objects.create(
        restaurant=restaurant, name="Напитки", print_station=station_bar,
    )
    chai = menu_items["chai"]
    chai.category = bar_cat
    chai.save()

    # Привяжем cook к hot
    cook.kitchen_station = station_hot
    cook.save(update_fields=["kitchen_station"])

    _create_order(restaurant, waiter, table, menu_items)

    pin = _pin(api_client, "5555")
    resp = api_client.get(
        "/api/v1/kitchen/items/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    data = resp.json()["data"]
    names = {i["name_at_order"] for i in data}
    assert "Плов" in names
    assert "Чай" not in names


def test_endpoint_station_all_overrides_cook_filter(
    api_client, restaurant, waiter, cook, table, menu_items,
    station_hot, station_bar,
):
    from apps.menu.models import Category

    plov_cat = menu_items["plov"].category
    plov_cat.print_station = station_hot
    plov_cat.save()
    bar_cat = Category.objects.create(
        restaurant=restaurant, name="Напитки", print_station=station_bar,
    )
    chai = menu_items["chai"]
    chai.category = bar_cat
    chai.save()
    cook.kitchen_station = station_hot
    cook.save(update_fields=["kitchen_station"])

    _create_order(restaurant, waiter, table, menu_items)

    pin = _pin(api_client, "5555")
    resp = api_client.get(
        "/api/v1/kitchen/items/?station=all", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    names = {i["name_at_order"] for i in resp.json()["data"]}
    assert "Плов" in names
    assert "Чай" in names


# -------- Auto-ready (kitchen_enabled=False) --------


def test_kitchen_enabled_default_true(restaurant):
    assert restaurant.kitchen_enabled is True


def test_auto_ready_when_kitchen_disabled(
    restaurant, waiter, table, menu_items,
):
    """Если kitchen_enabled=False — позиции создаются сразу READY."""
    from apps.orders.services import create_order

    restaurant.kitchen_enabled = False
    restaurant.save(update_fields=["kitchen_enabled"])

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    item = order.items.first()
    assert item.kitchen_status == "ready"
    assert item.ready_at is not None


def test_kitchen_enabled_true_creates_new_status(
    restaurant, waiter, table, menu_items,
):
    from apps.orders.services import create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        idempotency_key=uuid4(),
    )
    assert order.items.first().kitchen_status == "new"


def test_restaurant_endpoint_exposes_kitchen_enabled(
    api_client, restaurant, cashier,
):
    pin = _pin(api_client, "1234")
    resp = api_client.get(
        "/api/v1/restaurant/", HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    body = resp.json()["data"]
    assert body["kitchen_enabled"] is True


def test_restaurant_endpoint_patch_kitchen_enabled(
    api_client, restaurant, cashier,
):
    pin = _pin(api_client, "1234")
    resp = api_client.patch(
        "/api/v1/restaurant/",
        {"kitchen_enabled": False},
        format="json",
        HTTP_AUTHORIZATION=f"PIN {pin}",
    )
    assert resp.status_code == 200
    restaurant.refresh_from_db()
    assert restaurant.kitchen_enabled is False
