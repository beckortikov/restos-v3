from django.db import transaction
from django.utils import timezone

from common.exceptions import BusinessError

from .models import Table, TableStatus


@transaction.atomic
def open_table(*, table_id: int, waiter, guests_count: int) -> Table:
    try:
        table = Table.objects.select_for_update().get(id=table_id, restaurant=waiter.restaurant)
    except Table.DoesNotExist as exc:
        raise BusinessError("TABLE_NOT_FOUND", "Стол не найден", 404) from exc

    if table.status == TableStatus.OCCUPIED:
        raise BusinessError("TABLE_OCCUPIED", f"{table.name} уже занят", 409)

    table.status = TableStatus.OCCUPIED
    table.waiter = waiter
    table.guests_count = max(int(guests_count), 1)
    table.opened_at = timezone.now()
    table.save(update_fields=["status", "waiter", "guests_count", "opened_at", "updated_at"])
    return table


def free_table(table: Table) -> None:
    """Освобождает стол. Если стол был в группе — также закрывает группу
    (free_table вызывается при close_order, для группы это означает «всё, обедали»).

    Multi-group: если на столе есть ДРУГИЕ активные заказы (NEW/BILL_REQUESTED) —
    стол НЕ освобождается, остаётся occupied. Только пересчитывается guests_count
    (вычитаем гостей закрытой группы) и primary current_order переключается на
    оставшийся активный заказ.
    """
    from apps.orders.models import Order, OrderStatus

    # Активные заказы на столе, кроме только что закрытого (current_order пока
    # ещё может указывать на закрываемый — он DONE, его сюда не включаем).
    other_active = list(
        Order.objects.filter(
            table=table,
            status__in=(OrderStatus.NEW, OrderStatus.BILL_REQUESTED),
        )
    )
    if other_active:
        # Multi-group: на столе остались другие группы. Стол остаётся занятым.
        # Перевычисляем guests_count и переключаем primary current_order.
        new_primary = other_active[0]
        table.current_order = new_primary
        table.waiter = new_primary.waiter
        table.guests_count = sum(o.guests_count for o in other_active)
        # status/opened_at не трогаем — стол всё ещё occupied/bill_requested
        # (если хотя бы одна группа в bill_requested — статус оставляем)
        if any(o.status == OrderStatus.BILL_REQUESTED for o in other_active):
            table.status = TableStatus.BILL_REQUESTED
        else:
            table.status = TableStatus.OCCUPIED
        table.save(
            update_fields=[
                "status", "waiter", "current_order", "guests_count", "updated_at",
            ]
        )
        return

    group = table.group

    table.status = TableStatus.FREE
    table.waiter = None
    table.current_order = None
    table.guests_count = 0
    table.opened_at = None
    table.group = None
    table.save(
        update_fields=[
            "status", "waiter", "current_order", "guests_count", "opened_at",
            "group", "updated_at",
        ]
    )

    # Если был в группе — освободить остальные столы группы и закрыть её.
    if group is not None and group.closed_at is None:
        from .models import TableGroup
        from django.utils import timezone as _tz

        for t in group.tables.exclude(id=table.id):
            t.status = TableStatus.FREE
            t.waiter = None
            t.current_order = None
            t.guests_count = 0
            t.opened_at = None
            t.group = None
            t.save(
                update_fields=[
                    "status", "waiter", "current_order", "guests_count",
                    "opened_at", "group", "updated_at",
                ]
            )
        group.closed_at = _tz.now()
        group.save(update_fields=["closed_at"])


@transaction.atomic
def force_free_table(*, table_id: int, restaurant, user) -> Table:
    """Принудительно освободить стол. Используется кассиром в случае
    рассинхрона (стол `occupied`, но активного заказа нет — например, бажный
    state из старых тестов или внешнего вмешательства).

    Запрещено если на столе есть активный заказ (NEW / BILL_REQUESTED) —
    тогда нужно сначала закрыть/отменить заказ через стандартный flow.
    """
    from apps.orders.models import Order, OrderStatus

    try:
        table = Table.objects.select_for_update().get(
            id=table_id, restaurant=restaurant,
        )
    except Table.DoesNotExist as exc:
        raise BusinessError(
            "TABLE_NOT_FOUND", "Стол не найден", 404,
        ) from exc

    # Проверяем: нет ли активного заказа на столе
    active = Order.objects.filter(
        table=table,
        status__in=(OrderStatus.NEW, OrderStatus.BILL_REQUESTED),
    ).first()
    if active is not None:
        raise BusinessError(
            "TABLE_HAS_ACTIVE_ORDER",
            f"На столе активный заказ #{active.id}. Закройте/отмените заказ "
            "через обычный flow.",
            409,
        )

    free_table(table)
    from apps.audit.services import audit_log
    audit_log(
        user, "settings_update", target=table,
        payload={
            "action": "force_free_table",
            "table_id": table.id,
            "table_name": table.name,
        },
    )
    return table


@transaction.atomic
def merge_tables(*, restaurant, table_ids: list[int], user, name: str = "") -> "TableGroup":
    """Объединить N свободных столов в группу.

    Все столы должны быть в статусе FREE и в этом ресторане. Создаётся
    `TableGroup`, primary_table = стол с наименьшим id (для стабильности).
    Остальные столы переходят в `MERGED`. На primary потом будет открыт заказ
    (через стандартный create_order на primary_table_id).
    """
    from .models import Table, TableGroup

    if len(table_ids) < 2:
        raise BusinessError(
            "INVALID_TRANSITION", "Нужно выбрать минимум 2 стола", 422,
        )
    qs = Table.objects.select_for_update().filter(
        restaurant=restaurant, id__in=table_ids,
    )
    tables = list(qs)
    if len(tables) != len(set(table_ids)):
        raise BusinessError("TABLE_NOT_FOUND", "Один из столов не найден", 404)

    for t in tables:
        if t.status != TableStatus.FREE:
            raise BusinessError(
                "TABLE_OCCUPIED",
                f"{t.name} не свободен — нельзя объединять", 409,
            )
        if t.group_id is not None:
            raise BusinessError(
                "TABLE_ALREADY_MERGED",
                f"{t.name} уже в группе", 409,
            )

    primary = min(tables, key=lambda t: t.id)
    group = TableGroup.objects.create(
        restaurant=restaurant, name=name, primary_table=primary,
        created_by=user,
    )
    primary.group = group
    primary.save(update_fields=["group", "updated_at"])

    for t in tables:
        if t.id == primary.id:
            continue
        t.group = group
        t.status = TableStatus.MERGED
        t.save(update_fields=["group", "status", "updated_at"])

    from apps.audit.services import audit_log
    audit_log(
        user, "tables_merged", target=group,
        payload={
            "table_ids": [t.id for t in tables],
            "table_names": [t.name for t in sorted(tables, key=lambda x: x.number)],
            "primary_table_id": primary.id,
        },
    )
    return group


@transaction.atomic
def unmerge_table_group(*, restaurant, group_id: int, user) -> "TableGroup":
    """Разъединить группу — все столы возвращаются в FREE, group=None.

    Можно вызвать только если на главном столе нет активного заказа
    (current_order is None или связанный заказ DONE/CANCELLED).
    """
    from .models import TableGroup
    from django.utils import timezone as _tz

    try:
        group = TableGroup.objects.select_for_update().get(
            id=group_id, restaurant=restaurant, closed_at__isnull=True,
        )
    except TableGroup.DoesNotExist as exc:
        raise BusinessError(
            "TABLE_GROUP_NOT_FOUND", "Группа столов не найдена или уже закрыта",
            404,
        ) from exc

    primary = group.primary_table
    if primary is not None and primary.current_order_id is not None:
        from apps.orders.models import Order, OrderStatus

        try:
            o = Order.objects.get(id=primary.current_order_id)
            if o.status not in (OrderStatus.DONE, OrderStatus.CANCELLED):
                raise BusinessError(
                    "TABLE_GROUP_HAS_ORDER",
                    "На группе активный заказ — сначала закройте/отмените его",
                    409,
                )
        except Order.DoesNotExist:
            pass

    table_names = []
    for t in group.tables.all().order_by("number"):
        table_names.append(t.name)
        t.status = TableStatus.FREE
        t.waiter = None
        t.current_order = None
        t.guests_count = 0
        t.opened_at = None
        t.group = None
        t.save(
            update_fields=[
                "status", "waiter", "current_order", "guests_count",
                "opened_at", "group", "updated_at",
            ]
        )
    group.closed_at = _tz.now()
    group.save(update_fields=["closed_at"])

    from apps.audit.services import audit_log
    audit_log(
        user, "tables_unmerged", target=group,
        payload={"table_names": table_names},
    )
    return group
