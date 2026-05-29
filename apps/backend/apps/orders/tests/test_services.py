from decimal import Decimal
from uuid import uuid4

import pytest

from common.exceptions import BusinessError

pytestmark = pytest.mark.django_db


def _items(menu_items):
    return [
        {"menu_item_id": menu_items["plov"].id, "qty": 2},
        {"menu_item_id": menu_items["chai"].id, "qty": 1},
    ]


def test_create_order_happy_path(restaurant, waiter, table, menu_items):
    from apps.orders.services import create_order
    from apps.tables.models import Table, TableStatus

    order = create_order(
        restaurant=restaurant,
        table_id=table.id,
        waiter=waiter,
        guests_count=3,
        items_data=_items(menu_items),
        comment="без острого",
        idempotency_key=uuid4(),
    )

    assert order.status == "new"
    assert order.guests_count == 3
    assert order.items.count() == 2
    assert order.total == Decimal("98.00")  # 45*2 + 8*1

    table.refresh_from_db()
    assert table.status == TableStatus.OCCUPIED
    assert table.current_order_id == order.id
    assert table.waiter_id == waiter.id


def test_create_order_idempotency_returns_same(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import create_order

    key = uuid4()
    order1 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=key,
    )
    order2 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=key,
    )
    assert order1.id == order2.id


def test_create_second_order_on_occupied_table_creates_group(
    restaurant, waiter, table, menu_items
):
    """Multi-group: на занятый стол можно открыть вторую группу.

    Регрессия: раньше ловили TABLE_OCCUPIED, теперь поддерживается несколько
    активных заказов на одном столе (Гр.1, Гр.2 в дизайне).
    """
    from apps.orders.services import create_order

    o1 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    o2 = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=3, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    assert o1.id != o2.id
    assert o1.table_id == o2.table_id
    table.refresh_from_db()
    # primary остаётся первой группой, guests_count = сумма
    assert table.current_order_id == o1.id
    assert table.guests_count == 5


def test_create_order_unavailable_item_raises_422(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import create_order

    menu_items["plov"].is_available = False
    menu_items["plov"].save()

    with pytest.raises(BusinessError) as exc:
        create_order(
            restaurant=restaurant, table_id=table.id, waiter=waiter,
            guests_count=1,
            items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
            comment="", idempotency_key=uuid4(),
        )
    assert exc.value.code == "MENU_ITEM_UNAVAILABLE"
    assert exc.value.status_code == 422


def test_add_items_in_non_new_status_raises(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import add_items_to_order, create_order, request_bill

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    request_bill(order_id=order.id, waiter=waiter)

    with pytest.raises(BusinessError) as exc:
        add_items_to_order(
            order_id=order.id, waiter=waiter,
            items_data=[{"menu_item_id": menu_items["chai"].id, "qty": 1}],
        )
    assert exc.value.code == "INVALID_TRANSITION"


def test_add_items_merges_qty_for_same_menu_item(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import add_items_to_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )
    add_items_to_order(
        order_id=order.id, waiter=waiter,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 2}],
    )
    order.refresh_from_db()
    assert order.items.count() == 1
    assert order.items.first().qty == 3


def test_cancel_item_when_last_active_cancels_order(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import cancel_item, create_order
    from apps.tables.models import TableStatus

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1,
        items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
        comment="", idempotency_key=uuid4(),
    )
    item_id = order.items.first().id

    result = cancel_item(
        order_id=order.id, item_id=item_id, user=waiter, reason="ошибка"
    )
    assert result.status == "cancelled"

    table.refresh_from_db()
    assert table.status == TableStatus.FREE
    assert table.current_order_id is None


def test_cancel_item_requires_reason(restaurant, waiter, table, menu_items):
    from apps.orders.services import cancel_item, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    item_id = order.items.first().id

    with pytest.raises(BusinessError) as exc:
        cancel_item(order_id=order.id, item_id=item_id, user=waiter, reason="  ")
    assert exc.value.code == "INVALID_TRANSITION"


def test_request_bill_empties_raises_ORDER_EMPTY(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import cancel_item, create_order, request_bill

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    for it in order.items.all():
        cancel_item(
            order_id=order.id, item_id=it.id, user=waiter, reason="x"
        )
    # после полной отмены заказ — cancelled
    with pytest.raises(BusinessError) as exc:
        request_bill(order_id=order.id, waiter=waiter)
    assert exc.value.code == "INVALID_TRANSITION"


def test_close_order_happy_path(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order, create_order, request_bill
    from apps.printing.models import PrintJob, PrintJobStatus
    from apps.tables.models import TableStatus

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=2, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    request_bill(order_id=order.id, waiter=waiter)

    closed, job = close_order(
        order_id=order.id, cashier=cashier, payment_method="cash"
    )
    assert closed.status == "done"
    assert closed.cashier_id == cashier.id
    assert closed.payment_method == "cash"
    assert closed.closed_at is not None

    table.refresh_from_db()
    assert table.status == TableStatus.FREE
    assert table.current_order_id is None

    assert isinstance(job, PrintJob)
    assert job.status == PrintJobStatus.PENDING
    assert job.payload["order"]["total"] == "98.00"
    assert job.payload["order"]["payment_method"] == "cash"
    assert job.printer_id == printer.id


def test_close_order_invalid_payment_method(
    restaurant, waiter, cashier, table, menu_items
):
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    with pytest.raises(BusinessError) as exc:
        close_order(order_id=order.id, cashier=cashier, payment_method="bitcoin")
    assert exc.value.code == "INVALID_TRANSITION"


def test_close_already_done_raises_409(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")

    with pytest.raises(BusinessError) as exc:
        close_order(order_id=order.id, cashier=cashier, payment_method="cash")
    assert exc.value.code == "ORDER_ALREADY_CLOSED"
    assert exc.value.status_code == 409


def test_cancel_done_raises_409(
    restaurant, waiter, cashier, table, menu_items, printer
):
    from apps.orders.services import cancel_order, close_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    close_order(order_id=order.id, cashier=cashier, payment_method="cash")

    with pytest.raises(BusinessError) as exc:
        cancel_order(order_id=order.id, user=cashier, reason="ошибка")
    assert exc.value.code == "ORDER_ALREADY_CLOSED"


def test_cancel_idempotent_on_already_cancelled(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import cancel_order, create_order

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    cancel_order(order_id=order.id, user=waiter, reason="x")
    again = cancel_order(order_id=order.id, user=waiter, reason="x")
    assert again.status == "cancelled"


def test_request_bill_marks_table_bill_requested(
    restaurant, waiter, table, menu_items
):
    from apps.orders.services import create_order, request_bill
    from apps.tables.models import TableStatus

    order = create_order(
        restaurant=restaurant, table_id=table.id, waiter=waiter,
        guests_count=1, items_data=_items(menu_items), comment="",
        idempotency_key=uuid4(),
    )
    request_bill(order_id=order.id, waiter=waiter)

    table.refresh_from_db()
    assert table.status == TableStatus.BILL_REQUESTED
    order.refresh_from_db()
    assert order.status == "bill_requested"
    assert order.bill_requested_at is not None
