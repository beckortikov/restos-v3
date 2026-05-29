"""Concurrency safety: два waiter'а одновременно создают заказ на одном столе.

Multi-group: после внедрения нескольких групп на стол оба заказа должны
создаться успешно (это две группы гостей, у каждой свой счёт).

Используем `transactional_db` — без него @transaction.atomic не коммитит
до конца теста, и второй thread не увидит select_for_update эффекта.
"""
import threading
from uuid import uuid4

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_create_on_same_table_both_succeed_as_groups(
    restaurant, waiter, table, menu_items
):
    """Оба параллельных create_order успешно создают по заказу как разные группы."""
    from django.db import connections

    from apps.orders.services import create_order
    from common.exceptions import BusinessError

    barrier = threading.Barrier(2)
    results: dict[str, list] = {"orders": [], "errors": []}

    def worker():
        barrier.wait()
        try:
            o = create_order(
                restaurant=restaurant,
                table_id=table.id,
                waiter=waiter,
                guests_count=1,
                items_data=[{"menu_item_id": menu_items["plov"].id, "qty": 1}],
                comment="",
                idempotency_key=uuid4(),
            )
            results["orders"].append(o.id)
        except BusinessError as exc:
            results["errors"].append(exc.code)
        finally:
            # Закрываем thread-local соединения явно — close_old_connections()
            # игнорирует свежесозданные thread-local connections (CONN_MAX_AGE=0
            # означает «старые», но новые соединения ещё не успели «состариться»),
            # из-за чего TRUNCATE в тесте-следующем-после-этого иногда ловил
            # deadlock на остаточных locks. Явный close() — гарантия.
            for conn in connections.all():
                conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # Оба воркера создали свой заказ — это две группы на одном столе.
    assert len(results["orders"]) == 2
    assert results["errors"] == []
    table.refresh_from_db()
    assert table.status == "occupied"
