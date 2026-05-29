from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.menu.models import MenuItem, Modifier
from apps.printing.models import PrintJob
from apps.printing.services import enqueue_receipt_print
from apps.tables.models import Table, TableStatus
from apps.tables.services import free_table
from common.exceptions import BusinessError

from .models import (
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatus,
    OrderType,
    PaymentMethod,
    RefundedItem,
    RefundOperation,
)


def _reverse_stock_for_cancelled_item(item, *, user=None, reason: str = "") -> None:
    """Phase 8E — вернуть на склад ингредиенты/п/ф/prepared_qty при отмене позиции.

    Использует kind=MANUAL для ingredient/semi движений (явный аудит-след) и
    BatchCookingKind=CORRECT для batch-блюд. consumed_at сбрасывается, чтобы
    повторный consume не задвоился если позицию «восстановят» (не реализовано).
    """
    from decimal import Decimal as _D
    mi = item.menu_item
    if mi is None:
        return
    note = f"Отмена позиции #{item.id} ({reason or 'без причины'})"
    try:
        if getattr(mi, "is_batch_cooking", False):
            # Вернуть в prepared_qty
            from apps.menu.models import BatchCookingKind
            from apps.menu.services import record_batch_cook
            try:
                record_batch_cook(
                    mi, qty_delta=int(item.qty),
                    kind=BatchCookingKind.CORRECT,
                    user=user, note=note,
                    consume_techcard=False,
                )
            except Exception as _e:
                import logging
                logging.getLogger("apps.orders").warning(
                    "reverse batch consume failed for item %s: %s", item.id, _e,
                )
        else:
            # Вернуть ингредиенты/п/ф по техкарте × qty
            from apps.inventory.models import StockMovementKind, SemiStockMovementKind
            from apps.inventory.services import record_movement, record_semi_movement
            from apps.menu.models import MenuItemTechCardLine
            lines = list(
                MenuItemTechCardLine.objects.filter(menu_item=mi)
                .select_related("ingredient", "nested_semi")
            )
            for line in lines:
                qty = _D(str(line.qty_per_unit)) * _D(str(item.qty))
                if line.ingredient is not None:
                    try:
                        record_movement(
                            ingredient=line.ingredient,
                            kind=StockMovementKind.MANUAL,
                            qty_delta=qty,
                            reason=note, user=user,
                        )
                    except Exception as _e:
                        import logging
                        logging.getLogger("apps.orders").warning(
                            "reverse ingredient failed: %s", _e,
                        )
                elif line.nested_semi is not None:
                    try:
                        # SemiStockMovementKind не имеет MANUAL — используем INVENTORY_CORRECT
                        record_semi_movement(
                            semi_type=line.nested_semi,
                            kind=SemiStockMovementKind.INVENTORY_CORRECT,
                            qty_delta=qty,
                            reason=note, user=user,
                        )
                    except Exception as _e:
                        import logging
                        logging.getLogger("apps.orders").warning(
                            "reverse semi failed: %s", _e,
                        )
    finally:
        # Сбросить consumed_at — позиция больше не «списана».
        item.consumed_at = None
        item.save(update_fields=["consumed_at"])


def _consume_stock_for_new_items(order, *, user=None) -> None:
    """Phase 8E — списать со склада позиции, у которых consumed_at IS NULL.

    Вызывается из create_order и add_items_to_order сразу после OrderItem.create().
    `consume_for_order_close` и `record_batch_consume_for_order` отфильтрованы
    по consumed_at, так что повторные вызовы безопасны.

    INSUFFICIENT_STOCK НЕ блокирует создание заказа — складом займётся
    менеджер вручную (через документ «Списание»/«Инвентаризация»). Логируем.
    """
    from apps.inventory.services import consume_for_order_close as _csm
    from apps.menu.services import record_batch_consume_for_order as _bcsm

    try:
        _csm(order, user=user)
    except Exception as _e:
        import logging
        logging.getLogger("apps.orders").warning(
            "consume on create/add failed for order %s: %s", order.id, _e,
        )
    try:
        _bcsm(order, user=user)
    except Exception as _e:
        import logging
        logging.getLogger("apps.orders").warning(
            "batch_consume on create/add failed for order %s: %s", order.id, _e,
        )


def _attach_modifiers(
    order_item: OrderItem,
    menu_item: MenuItem,
    modifier_ids: list[int],
) -> None:
    """Валидирует выбранные modifier_ids и снимает snapshot в OrderItemModifier.

    Правила:
    - Все modifier_ids должны принадлежать группам, прикреплённым к menu_item.
    - В каждой группе количество выбранных опций должно быть в [min_select; max_select].
    - is_required=True ⇒ как минимум 1 опция выбрана из этой группы.
    """
    if not modifier_ids and not menu_item.modifier_groups.filter(
        is_required=True
    ).exists():
        return

    allowed_groups = list(
        menu_item.modifier_groups.all().prefetch_related("modifiers")
    )
    allowed_mod_by_id: dict[int, Modifier] = {}
    for g in allowed_groups:
        for m in g.modifiers.all():
            allowed_mod_by_id[m.id] = m

    chosen: list[Modifier] = []
    seen: set[int] = set()
    for mid in modifier_ids:
        if mid in seen:
            continue
        seen.add(mid)
        m = allowed_mod_by_id.get(mid)
        if m is None or not m.is_active:
            raise BusinessError(
                "MODIFIER_NOT_ALLOWED",
                f"Модификатор id={mid} недоступен для блюда «{menu_item.name}»",
                422,
            )
        chosen.append(m)

    # Группировка по group_id для проверки min/max.
    by_group: dict[int, list[Modifier]] = {}
    for m in chosen:
        by_group.setdefault(m.group_id, []).append(m)

    for g in allowed_groups:
        cnt = len(by_group.get(g.id, []))
        if g.is_required and cnt < max(1, g.min_select):
            raise BusinessError(
                "MODIFIER_REQUIRED",
                f"Не выбран обязательный модификатор из группы «{g.name}»",
                422,
            )
        if cnt < g.min_select:
            raise BusinessError(
                "MODIFIER_REQUIRED",
                f"Минимум опций в группе «{g.name}»: {g.min_select}",
                422,
            )
        if cnt > g.max_select:
            raise BusinessError(
                "MODIFIER_TOO_MANY",
                f"Максимум опций в группе «{g.name}»: {g.max_select}",
                422,
            )

    for m in chosen:
        OrderItemModifier.objects.create(
            order_item=order_item,
            modifier=m,
            name_at_order=m.name,
            price_delta_at_order=m.price_delta,
            group_name_at_order=m.group.name if hasattr(m, "group") else "",
        )


@transaction.atomic
def create_order(
    *,
    restaurant,
    waiter,
    items_data: list[dict],
    idempotency_key: UUID,
    table_id: int | None = None,
    guests_count: int = 1,
    comment: str = "",
    order_type: str = OrderType.HALL,
    customer_name: str = "",
    customer_phone: str = "",
    customer_address: str = "",
) -> Order:
    """Создание заказа.

    Для order_type=hall: table_id обязателен; стол берётся под select_for_update,
    помечается occupied + current_order=order.
    Для takeaway/delivery: table_id игнорируется, customer_* — желателен (валидация
    мягкая, форма решает).
    """
    existing = Order.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    if order_type not in OrderType.values:
        raise BusinessError(
            "INVALID_TRANSITION", f"Неизвестный тип заказа: {order_type}", 422
        )

    table: Table | None = None
    if order_type == OrderType.HALL:
        if not table_id:
            raise BusinessError(
                "TABLE_NOT_FOUND", "Для зала нужен table_id", 422
            )
        try:
            table = Table.objects.select_for_update().get(
                id=table_id, restaurant=restaurant
            )
        except Table.DoesNotExist as exc:
            raise BusinessError("TABLE_NOT_FOUND", "Стол не найден", 404) from exc

        # Multi-group: на одном столе разрешено иметь несколько активных
        # заказов (разные компании сидят рядом, у каждой свой счёт).
        # Блокируем только если это MERGED-стол в группе (главный держит
        # один общий заказ всей группы) или если стол явно «не доступен».
        if table.status == TableStatus.MERGED:
            raise BusinessError(
                "TABLE_OCCUPIED",
                f"{table.name} объединён в группу — заказ открывается на главный стол",
                409,
            )

    # Snapshot активной ставки сервисного сбора из настроек ресторана.
    # Сервис применяется ТОЛЬКО для зала (order_type=hall) — за услуги
    # официанта. Для takeaway / delivery официант не обслуживает гостя за
    # столиком, поэтому service_charge=0 независимо от настроек ресторана.
    from decimal import Decimal as _D

    from .models import Discount as _Disc
    service_pct = _D("0.00")
    if order_type == OrderType.HALL:
        svc = (
            _Disc.objects.filter(
                restaurant=restaurant, type="service", is_active=True,
            )
            .order_by("sort_order", "id")
            .first()
        )
        service_pct = _D(str(svc.value)) if svc else _D("0.00")

    order = Order.objects.create(
        restaurant=restaurant,
        order_type=order_type,
        table=table,
        waiter=waiter,
        guests_count=max(int(guests_count), 1) if order_type == OrderType.HALL else 0,
        comment=comment,
        customer_name=customer_name.strip(),
        customer_phone=customer_phone.strip(),
        customer_address=customer_address.strip(),
        idempotency_key=idempotency_key,
        status=OrderStatus.NEW,
        service_charge_pct=service_pct,
    )

    for it in items_data:
        try:
            mi = MenuItem.objects.get(id=it["menu_item_id"], restaurant=restaurant)
        except MenuItem.DoesNotExist as exc:
            raise BusinessError(
                "MENU_ITEM_UNAVAILABLE",
                f"Блюдо id={it['menu_item_id']} не найдено",
                422,
            ) from exc
        if not mi.is_available:
            reason = mi.stop_reason or "недоступно"
            code = "STOCK_INSUFFICIENT" if mi.auto_stopped else "MENU_ITEM_UNAVAILABLE"
            raise BusinessError(code, f"«{mi.name}»: {reason}", 422)
        # Если кухня выключена в ресторане — позиция сразу READY (auto-ready).
        # Повар не работает, готовят за стойкой, флаг для поваров не нужен.
        from apps.orders.models import KitchenStatus

        kstatus = (
            KitchenStatus.READY
            if not order.restaurant.kitchen_enabled
            else KitchenStatus.NEW
        )
        kw_extra = {}
        if kstatus == KitchenStatus.READY:
            kw_extra["ready_at"] = timezone.now()
        oi = OrderItem.objects.create(
            order=order,
            menu_item=mi,
            name_at_order=mi.name,
            price_at_order=mi.price,
            qty=it["qty"],
            note=(it.get("note") or "").strip()[:255],
            kitchen_status=kstatus,
            **kw_extra,
        )
        _attach_modifiers(oi, mi, list(it.get("modifier_ids") or []))

    if table is not None:
        # Multi-group: если стол уже занят другой группой — НЕ перезаписываем
        # current_order/waiter/guests (они принадлежат первой группе). Просто
        # суммируем количество гостей в guests_count для отображения.
        # current_order остаётся как «primary» — это первая группа.
        if table.status == TableStatus.FREE:
            table.status = TableStatus.OCCUPIED
            table.current_order = order
            table.waiter = waiter
            table.guests_count = order.guests_count
            table.opened_at = timezone.now()
            table.save(
                update_fields=[
                    "status", "current_order", "waiter", "guests_count",
                    "opened_at", "updated_at",
                ]
            )
        else:
            # Уже occupied (вторая+ группа). Обновим суммарное число гостей.
            table.guests_count = (table.guests_count or 0) + order.guests_count
            table.save(update_fields=["guests_count", "updated_at"])

    # Phase 8E — списание со склада СРАЗУ при создании заказа (не на close_order).
    # Декремент prepared_qty для batch-блюд тоже здесь.
    _consume_stock_for_new_items(order, user=waiter)

    # Авто-печать на кухню (по PrintStation категорий блюд).
    from apps.printing.services import enqueue_kitchen_prints
    enqueue_kitchen_prints(order)

    from apps.audit.services import audit_log
    audit_log(
        waiter, "order_create", target=order,
        payload={
            "order_type": order_type,
            "table_id": table_id,
            "items_count": len(items_data),
            "total": str(order.total),
        },
    )
    return order


@transaction.atomic
def add_items_to_order(*, order_id: int, waiter, items_data: list[dict]) -> Order:
    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status != OrderStatus.NEW:
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя добавить позицию в заказ со статусом {order.status}",
            422,
        )

    for it in items_data:
        try:
            mi = MenuItem.objects.get(id=it["menu_item_id"], restaurant=order.restaurant)
        except MenuItem.DoesNotExist as exc:
            raise BusinessError(
                "MENU_ITEM_UNAVAILABLE",
                f"Блюдо id={it['menu_item_id']} не найдено",
                422,
            ) from exc
        if not mi.is_available:
            reason = mi.stop_reason or "недоступно"
            code = "STOCK_INSUFFICIENT" if mi.auto_stopped else "MENU_ITEM_UNAVAILABLE"
            raise BusinessError(code, f"«{mi.name}»: {reason}", 422)

        note = (it.get("note") or "").strip()[:255]
        modifier_ids = list(it.get("modifier_ids") or [])
        # Мерджим только позиции с одинаковыми note + signature модификаторов.
        # Если модификаторы — мерджа не делаем (разные опции = разные позиции).
        existing = None
        if not modifier_ids:
            existing = order.items.filter(
                menu_item=mi, note=note, cancelled_at__isnull=True,
                modifiers__isnull=True,
            ).first()
        if existing:
            existing.qty += it["qty"]
            existing.save(update_fields=["qty"])
        else:
            oi = OrderItem.objects.create(
                order=order,
                menu_item=mi,
                name_at_order=mi.name,
                price_at_order=mi.price,
                qty=it["qty"],
                note=note,
            )
            _attach_modifiers(oi, mi, modifier_ids)

    order.save(update_fields=["updated_at"])

    # Phase 8E — списать новые позиции со склада (consumed_at != null будут пропущены).
    _consume_stock_for_new_items(order, user=waiter)

    # Phase 4 — авто-печать на кухню новых позиций (дозаказ).
    # Только что добавленные позиции имеют sent_to_kitchen_at=NULL, остальные
    # уже отправлены при create_order. Не блокируем add_items если печать упала.
    try:
        from apps.printing.services import enqueue_kitchen_prints
        enqueue_kitchen_prints(order, only_unsent=True)
    except Exception as _e:
        import logging
        logging.getLogger("apps.orders").warning(
            "auto-print kitchen for add_items failed (order=%s): %s",
            order.id, _e,
        )

    return order


@transaction.atomic
def fire_kitchen(*, order_id: int, user) -> dict:
    """Phase 4 «Дозаказ → НА КУХНЮ»: отправить ещё не печатавшиеся позиции
    на кухонный runner.

    Найти `OrderItem`-ы с `sent_to_kitchen_at IS NULL` (активные), создать
    PrintJob'ы через `enqueue_kitchen_prints(order, only_unsent=True)`,
    отметить timestamp.

    Возвращает: {"jobs_count": N, "items_sent": M}.
    Если нет несрафкированных позиций — `{"jobs_count": 0, "items_sent": 0}`.
    """
    from apps.printing.services import enqueue_kitchen_prints

    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя отправить на кухню заказ со статусом {order.status}",
            422,
        )

    unsent_count = order.items.filter(
        cancelled_at__isnull=True, sent_to_kitchen_at__isnull=True,
    ).count()
    if unsent_count == 0:
        return {"jobs_count": 0, "items_sent": 0}

    jobs = enqueue_kitchen_prints(order, only_unsent=True)

    from apps.audit.services import audit_log
    audit_log(
        user, "order_fire_kitchen", target=order,
        payload={"items_sent": unsent_count, "jobs_count": len(jobs)},
    )
    return {"jobs_count": len(jobs), "items_sent": unsent_count}


@transaction.atomic
def cancel_item(*, order_id: int, item_id: int, user, reason: str) -> Order:
    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION", "Нельзя отменить позицию закрытого заказа", 422
        )
    if not (reason or "").strip():
        raise BusinessError("INVALID_TRANSITION", "Нужна причина отмены", 422)

    try:
        item = order.items.select_for_update().get(id=item_id)
    except OrderItem.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Позиция не найдена", 404) from exc

    if item.cancelled_at:
        raise BusinessError("INVALID_TRANSITION", "Позиция уже отменена", 422)

    # Состояние кухни ДО отмены — для решения о бегунке.
    from apps.orders.models import KitchenStatus

    was_in_kitchen = item.kitchen_status in (
        KitchenStatus.COOKING, KitchenStatus.READY,
    )

    item.cancelled_at = timezone.now()
    item.cancelled_by = user
    item.cancel_reason = reason
    item.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])

    # Phase 8E — если позиция уже списана со склада (consumed_at != null),
    # вернуть сырьё обратно: реверс-движения с MANUAL kind и явной причиной.
    if item.consumed_at is not None:
        _reverse_stock_for_cancelled_item(item, user=user, reason=reason)

    from apps.audit.services import audit_log
    audit_log(
        user, "item_cancel", target=order,
        payload={
            "item_id": item.id,
            "item_name": item.name_at_order,
            "qty": item.qty,
            "reason": reason,
        },
    )

    # Бегунок отмены — если позиция уже была принята кухней.
    if was_in_kitchen:
        from apps.printing.services import enqueue_cancel_runner

        try:
            enqueue_cancel_runner(item, cancelled_by=user, reason=reason)
        except Exception:
            # Печать не критична — заказ уже отменён.
            pass

    if not order.items.filter(cancelled_at__isnull=True).exists():
        return cancel_order(order_id=order.id, user=user, reason="Все позиции отменены")

    order.save(update_fields=["updated_at"])
    return order


@transaction.atomic
@transaction.atomic
def set_item_note(*, item_id: int, note: str, actor) -> OrderItem:
    """Обновить комментарий к позиции заказа (например, «без лука»).

    Возможно только пока заказ NEW и item не cancelled. note печатается в
    чеке (snapshot в OrderItem.note)."""
    try:
        item = (
            OrderItem.objects.select_for_update()
            .select_related("order")
            .get(id=item_id, order__restaurant=actor.restaurant)
        )
    except OrderItem.DoesNotExist as exc:
        raise BusinessError(
            "ORDER_ITEM_NOT_FOUND", "Позиция не найдена", 404,
        ) from exc

    if item.cancelled_at is not None:
        raise BusinessError(
            "INVALID_TRANSITION",
            "Нельзя править комментарий отменённой позиции",
            409,
        )
    if item.order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION",
            "Заказ уже закрыт",
            409,
        )

    new_note = (note or "").strip()[:255]
    if new_note == item.note:
        return item

    prev = item.note
    item.note = new_note
    item.save(update_fields=["note"])

    from apps.audit.services import audit_log
    audit_log(
        actor, "order_item_set_note", target=item,
        payload={"order_id": item.order_id, "item_id": item.id, "from": prev, "to": new_note},
    )
    return item


def request_bill(*, order_id: int, waiter) -> Order:
    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status != OrderStatus.NEW:
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя запросить счёт из статуса {order.status}",
            422,
        )
    if not order.items.filter(cancelled_at__isnull=True).exists():
        raise BusinessError("ORDER_EMPTY", "Заказ пустой", 422)

    order.status = OrderStatus.BILL_REQUESTED
    order.bill_requested_at = timezone.now()
    order.save(update_fields=["status", "bill_requested_at", "updated_at"])

    # Стол подсвечиваем только для hall-заказов.
    if order.table is not None and order.table.status != TableStatus.BILL_REQUESTED:
        order.table.status = TableStatus.BILL_REQUESTED
        order.table.save(update_fields=["status", "updated_at"])

    return order


@transaction.atomic
def close_order(
    *,
    order_id: int,
    cashier,
    payment_method: str | None = None,
    payments: list[dict] | None = None,
    tip_amount: "Decimal | str | None" = None,
) -> tuple[Order, PrintJob]:
    """Закрытие заказа с одной или несколькими оплатами.

    - `payment_method` — single payment (legacy, backwards-compat).
    - `payments=[{method, amount}, ...]` — multi-payment (Phase 4).
      Сумма amount должна совпадать с order.total (±0.01).
    Должен быть передан ровно один из них.
    """
    from decimal import Decimal

    from .models import OrderPayment

    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status == OrderStatus.DONE:
        raise BusinessError("ORDER_ALREADY_CLOSED", "Заказ уже закрыт", 409)
    if order.status == OrderStatus.CANCELLED:
        raise BusinessError(
            "INVALID_TRANSITION", "Заказ отменён, оплатить нельзя", 422
        )
    if not order.items.filter(cancelled_at__isnull=True).exists():
        raise BusinessError("ORDER_EMPTY", "Нет активных позиций", 422)

    # Чаевые — фиксируем ДО валидации payments, т.к. влияют на total.
    if tip_amount is not None:
        try:
            tip_dec = Decimal(str(tip_amount))
        except Exception as exc:
            raise BusinessError(
                "INVALID_TRANSITION",
                f"Сумма чаевых невалидна: {tip_amount}", 422,
            ) from exc
        if tip_dec < 0:
            raise BusinessError(
                "INVALID_TRANSITION",
                "Сумма чаевых не может быть отрицательной", 422,
            )
        order.tip_amount = tip_dec
        # save позже вместе с остальными полями

    # Унифицируем входные данные → список dict {method, amount}
    if payments is None and payment_method is None:
        raise BusinessError(
            "INVALID_TRANSITION",
            "Не передан способ оплаты (payment_method или payments)", 422,
        )
    if payments is None:
        if payment_method not in PaymentMethod.values:
            raise BusinessError(
                "INVALID_TRANSITION", "Неизвестный метод оплаты", 422
            )
        payments_list = [{"method": payment_method, "amount": order.total}]
    else:
        if not payments:
            raise BusinessError(
                "INVALID_TRANSITION", "Список оплат пуст", 422,
            )
        payments_list = []
        for p in payments:
            m = p.get("method")
            if m not in PaymentMethod.values:
                raise BusinessError(
                    "INVALID_TRANSITION",
                    f"Неизвестный метод оплаты: {m}", 422,
                )
            try:
                a = Decimal(str(p.get("amount")))
            except Exception as exc:
                raise BusinessError(
                    "INVALID_TRANSITION",
                    f"Сумма платежа невалидна: {p.get('amount')}", 422,
                ) from exc
            if a <= 0:
                raise BusinessError(
                    "INVALID_TRANSITION",
                    "Сумма платежа должна быть положительной", 422,
                )
            payments_list.append({"method": m, "amount": a})

    total_paid = sum((Decimal(str(p["amount"])) for p in payments_list), Decimal("0"))
    expected = Decimal(str(order.total))
    if abs(total_paid - expected) > Decimal("0.01"):
        raise BusinessError(
            "PAYMENT_AMOUNT_MISMATCH",
            f"Сумма оплат ({total_paid}) не совпадает с итогом заказа ({expected})",
            422,
        )

    # Primary method для denormalized payment_method = метод с наибольшей суммой
    primary = max(payments_list, key=lambda p: Decimal(str(p["amount"])))

    order.status = OrderStatus.DONE
    order.cashier = cashier
    order.payment_method = primary["method"]
    order.closed_at = timezone.now()

    # Привязка к текущей открытой кассовой смене (Phase 3).
    # Если смены нет — заказ сохраняется без shift_id (опционально).
    from apps.shifts.services import get_current_shift

    current_shift = get_current_shift(order.restaurant)
    if current_shift is not None and order.shift_id is None:
        order.shift = current_shift
        order.save(
            update_fields=[
                "status", "cashier", "payment_method", "closed_at",
                "shift", "tip_amount", "updated_at",
            ]
        )
    else:
        order.save(
            update_fields=[
                "status", "cashier", "payment_method", "closed_at",
                "tip_amount", "updated_at",
            ]
        )

    # Создаём OrderPayment-ы (1 для single, N для multi). Сначала чистим
    # на случай если кто-то перезакрывает (хотя select_for_update + DONE-check
    # это исключают).
    OrderPayment.objects.filter(order=order).delete()
    for p in payments_list:
        OrderPayment.objects.create(
            order=order, method=p["method"], amount=Decimal(str(p["amount"]))
        )

    # Освобождать нечего, если это takeaway/delivery.
    if order.table is not None:
        free_table(order.table)

    # ── Phase 7C: автосписание ингредиентов/п/ф по техкартам ──────────────
    # Списываем со склада только когда заказ реально закрывается (DONE).
    # Если у блюда нет техкарты — позиция пропускается (типично для покупных
    # товаров / напитков). Если ингредиента не хватает — BusinessError
    # INSUFFICIENT_STOCK прерывает close_order, и кассир видит почему.
    from apps.inventory.services import consume_for_order_close
    try:
        consume_for_order_close(order, user=cashier)
    except BusinessError:
        raise  # пробрасываем явные бизнес-ошибки (INSUFFICIENT_STOCK и т.п.)
    except Exception as _e:
        # Любые другие ошибки apps.inventory не блокируют close, только логируем.
        import logging
        logging.getLogger("apps.orders").warning(
            "consume_for_order_close failed for order %s: %s", order.id, _e,
        )

    # Phase 7E: декремент prepared_qty для batch-cooking блюд.
    from apps.menu.services import record_batch_consume_for_order
    try:
        record_batch_consume_for_order(order, user=cashier)
    except Exception as _e:
        import logging
        logging.getLogger("apps.orders").warning(
            "record_batch_consume_for_order failed for order %s: %s", order.id, _e,
        )

    job = enqueue_receipt_print(order)

    from apps.audit.services import audit_log
    audit_log(
        cashier, "order_close", target=order,
        payload={
            "payment_method": primary["method"],
            "payments": [
                {"method": p["method"], "amount": str(p["amount"])}
                for p in payments_list
            ],
            "total": str(order.total),
            "service_charge": str(order.service_charge_amount),
            "discount": str(order.discount_amount),
        },
    )
    return order, job


@transaction.atomic
def cancel_order(*, order_id: int, user, reason: str) -> Order:
    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status == OrderStatus.DONE:
        raise BusinessError(
            "ORDER_ALREADY_CLOSED", "Закрытый заказ отменить нельзя", 409
        )
    if order.status == OrderStatus.CANCELLED:
        return order

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = user
    order.cancel_reason = reason or ""
    order.save(
        update_fields=[
            "status", "cancelled_at", "cancelled_by", "cancel_reason", "updated_at",
        ]
    )

    if order.table is not None:
        free_table(order.table)

    from apps.audit.services import audit_log
    audit_log(
        user, "order_cancel", target=order,
        payload={"reason": reason or ""},
    )
    return order


@transaction.atomic
def refund_order(
    *,
    order_id: int,
    cashier,
    items_data: list[dict],
    reason: str,
    idempotency_key: UUID,
) -> RefundOperation:
    """Возврат по закрытому заказу — frame 13.

    items_data: [{"order_item_id": int, "qty": int}, ...]
    Если items_data пуст — возврат по всем активным позициям заказа полностью.

    - Order должен быть DONE.
    - qty ≤ оригинальный qty минус уже возвращённое.
    - Создаётся RefundOperation + RefundedItem'ы.
    - Если есть открытая смена и платёж был cash → создаётся
      CashShiftOperation(kind=cash_out, amount=refund_amount).
    """
    from decimal import Decimal

    existing = RefundOperation.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if existing:
        return existing

    if not (reason or "").strip():
        raise BusinessError("INVALID_TRANSITION", "Нужна причина возврата", 422)

    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status != OrderStatus.DONE:
        raise BusinessError(
            "INVALID_TRANSITION",
            "Возврат возможен только по закрытым (оплаченным) заказам",
            422,
        )

    # Если позиции не указаны — возвращаем все активные с их полным qty
    # минус уже возвращённое.
    active_items = list(
        order.items.filter(cancelled_at__isnull=True).select_for_update()
    )
    if not active_items:
        raise BusinessError("ORDER_EMPTY", "В заказе нет активных позиций", 422)

    # Карта уже возвращённого qty по позициям (через все прошлые возвраты).
    already: dict[int, int] = {}
    for ri in RefundedItem.objects.filter(
        order_item__order=order
    ).values_list("order_item_id", "qty"):
        oid, q = ri
        already[oid] = already.get(oid, 0) + int(q)

    # Подготовить план: dict order_item_id -> qty к возврату
    plan: dict[int, int] = {}
    if items_data:
        for it in items_data:
            oid = int(it.get("order_item_id", 0))
            qty = int(it.get("qty", 0))
            if qty <= 0:
                continue
            plan[oid] = plan.get(oid, 0) + qty
    else:
        for oi in active_items:
            remaining = oi.qty - already.get(oi.id, 0)
            if remaining > 0:
                plan[oi.id] = remaining

    if not plan:
        raise BusinessError(
            "INVALID_TRANSITION", "Нечего возвращать", 422
        )

    # Валидируем и собираем сумму
    total = Decimal("0.00")
    items_resolved: list[tuple[OrderItem, int]] = []
    for oi in active_items:
        if oi.id not in plan:
            continue
        want = plan[oi.id]
        remaining = oi.qty - already.get(oi.id, 0)
        if want > remaining:
            raise BusinessError(
                "INVALID_TRANSITION",
                f"Для позиции «{oi.name_at_order}» можно вернуть не более {remaining}",
                422,
            )
        total += oi.price_at_order * want
        items_resolved.append((oi, want))

    # Если хоть один order_item_id не нашёлся в активных — ошибка.
    found_ids = {oi.id for oi, _ in items_resolved}
    missing = set(plan.keys()) - found_ids
    if missing:
        raise BusinessError(
            "ORDER_NOT_FOUND",
            f"Позиции {sorted(missing)} не найдены в заказе #{order.id}",
            404,
        )

    if total <= Decimal("0.00"):
        raise BusinessError("INVALID_TRANSITION", "Сумма возврата нулевая", 422)

    # Привязываем к текущей открытой смене (если есть)
    from apps.shifts.models import CashOperationType, CashShiftOperation
    from apps.shifts.services import get_current_shift

    current_shift = get_current_shift(order.restaurant)

    refund = RefundOperation.objects.create(
        restaurant=order.restaurant,
        order=order,
        cashier=cashier,
        shift=current_shift,
        amount=total,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    for oi, qty in items_resolved:
        RefundedItem.objects.create(
            refund=refund,
            order_item=oi,
            qty=qty,
            price_at_refund=oi.price_at_order,
        )

    # Если оплата была наличными и смена открыта — фиксируем cash_out.
    if (
        current_shift is not None
        and order.payment_method == PaymentMethod.CASH
    ):
        CashShiftOperation.objects.create(
            shift=current_shift,
            kind=CashOperationType.CASH_OUT,
            amount=total,
            reason=f"Возврат по заказу #{order.id}: {reason}"[:255],
            created_by=cashier,
        )

    from apps.audit.services import audit_log
    audit_log(
        cashier, "refund", target=order,
        payload={
            "refund_id": refund.id,
            "amount": str(total),
            "items": [{"id": oi.id, "qty": qty} for oi, qty in items_resolved],
            "reason": reason,
        },
    )

    return refund


@transaction.atomic
def assign_waiter(*, order_id: int, target_waiter_id: int, actor) -> Order:
    """Сменить официанта на заказе. Доступно waiter (взять чужой стол) и
    cashier/manager (назначить любого). Target должен быть waiter того же
    ресторана и активен."""
    from apps.users.models import User, UserRole

    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.restaurant_id != actor.restaurant_id:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404)

    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION",
            "Нельзя сменить официанта на закрытом заказе",
            422,
        )

    try:
        target = User.objects.get(
            id=target_waiter_id, restaurant=actor.restaurant, is_active=True,
        )
    except User.DoesNotExist as exc:
        raise BusinessError(
            "USER_NOT_FOUND", "Официант не найден", 404,
        ) from exc

    if target.role != UserRole.WAITER:
        raise BusinessError(
            "INVALID_ROLE", "Можно назначить только официанта", 422,
        )

    if order.waiter_id == target.id:
        return order

    prev_id = order.waiter_id
    order.waiter = target
    order.save(update_fields=["waiter", "updated_at"])

    # Синхронизируем waiter на столе тоже — стол ведёт тот же официант,
    # что и текущий активный заказ.
    if order.table_id is not None:
        Table.objects.filter(id=order.table_id).update(waiter=target)

    from apps.audit.services import audit_log
    audit_log(
        actor, "order_assign_waiter", target=order,
        payload={
            "order_id": order.id,
            "from_waiter_id": prev_id,
            "to_waiter_id": target.id,
        },
    )
    return order


def transfer_order(*, order_id: int, target_table_id: int, cashier) -> Order:
    """Перенос hall-заказа на другой стол — frame 7.

    - Order должен быть NEW или BILL_REQUESTED и order_type=hall.
    - target_table должен быть FREE.
    - Исходный стол освобождается, target помечается OCCUPIED + current_order.
    """
    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION",
            "Перенос возможен только для активных заказов",
            422,
        )
    if order.order_type != OrderType.HALL:
        raise BusinessError(
            "INVALID_TRANSITION",
            "Перенос возможен только для заказов в зале",
            422,
        )

    try:
        target = Table.objects.select_for_update().get(
            id=target_table_id, restaurant=order.restaurant
        )
    except Table.DoesNotExist as exc:
        raise BusinessError(
            "TABLE_NOT_FOUND", "Целевой стол не найден", 404
        ) from exc

    if order.table_id == target.id:
        raise BusinessError(
            "INVALID_TRANSITION", "Это тот же самый стол", 422
        )
    if (
        target.status == TableStatus.OCCUPIED
        and target.current_order_id is not None
    ):
        raise BusinessError(
            "TABLE_OCCUPIED", f"{target.name} занят", 409
        )

    # Сначала переключаем FK заказа на новый стол, чтобы free_table старого
    # стола не считал этот же заказ «активным на нём» (multi-group логика).
    old_table_id = order.table_id
    order.table = target
    order.save(update_fields=["table", "updated_at"])

    if old_table_id is not None:
        old_table = Table.objects.select_for_update().get(id=old_table_id)
        free_table(old_table)

    target.status = (
        TableStatus.BILL_REQUESTED
        if order.status == OrderStatus.BILL_REQUESTED
        else TableStatus.OCCUPIED
    )
    target.current_order = order
    target.waiter = order.waiter
    target.guests_count = order.guests_count
    target.opened_at = timezone.now()
    target.save(
        update_fields=[
            "status", "current_order", "waiter", "guests_count",
            "opened_at", "updated_at",
        ]
    )

    from apps.audit.services import audit_log
    audit_log(
        cashier, "order_transfer", target=order,
        payload={
            "from_table_id": order.table_id if order.table else None,
            "to_table_id": target.id,
        },
    )
    return order


@transaction.atomic
def apply_discount(*, order_id: int, discount_id: int, cashier) -> Order:
    """Применить скидку к активному заказу — Phase 4.

    Snapshot'им kind/value на момент применения, чтобы изменение Discount
    в настройках не меняло уже применённую скидку.
    """
    from .models import Discount as _Disc

    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION",
            "Скидку можно применить только к активному заказу",
            422,
        )

    try:
        disc = _Disc.objects.get(
            id=discount_id, restaurant=order.restaurant, type="discount"
        )
    except _Disc.DoesNotExist as exc:
        raise BusinessError(
            "DISCOUNT_NOT_FOUND", "Скидка не найдена", 404
        ) from exc

    if not disc.is_active:
        raise BusinessError(
            "DISCOUNT_INACTIVE", "Скидка отключена в настройках", 422
        )

    order.applied_discount = disc
    order.discount_kind = disc.kind
    order.discount_value = disc.value
    order.save(
        update_fields=[
            "applied_discount", "discount_kind", "discount_value", "updated_at",
        ]
    )
    from apps.audit.services import audit_log
    audit_log(
        cashier, "discount_apply", target=order,
        payload={
            "discount_id": disc.id,
            "discount_name": disc.name,
            "kind": disc.kind,
            "value": str(disc.value),
        },
    )
    return order


@transaction.atomic
def remove_discount(*, order_id: int, cashier) -> Order:
    """Снять скидку с заказа."""
    try:
        order = Order.objects.select_for_update().get(id=order_id)
    except Order.DoesNotExist as exc:
        raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError(
            "INVALID_TRANSITION",
            "Скидку можно снять только с активного заказа",
            422,
        )

    from decimal import Decimal as _D
    order.applied_discount = None
    order.discount_kind = ""
    order.discount_value = _D("0")
    order.save(
        update_fields=[
            "applied_discount", "discount_kind", "discount_value", "updated_at",
        ]
    )
    from apps.audit.services import audit_log
    audit_log(cashier, "discount_remove", target=order)
    return order


def archive_old_orders(*, days: int = 90) -> int:
    """Архивировать закрытые/отменённые заказы старше N дней.

    Возвращает количество заархивированных записей. Активные (NEW /
    BILL_REQUESTED) и уже архивированные не трогаются.
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=int(days))
    qs = Order.objects.filter(
        status__in=[OrderStatus.DONE, OrderStatus.CANCELLED],
        archived_at__isnull=True,
    ).filter(
        # либо closed_at, либо cancelled_at — берём более позднюю
        # «дата завершения». В Django используем Q с двумя условиями:
    )
    # Простой критерий: closed_at < cutoff ИЛИ (status=cancelled AND cancelled_at < cutoff).
    from django.db.models import Q

    cond = (
        Q(status=OrderStatus.DONE, closed_at__lt=cutoff)
        | Q(status=OrderStatus.CANCELLED, cancelled_at__lt=cutoff)
    )
    qs = qs.filter(cond)
    count = qs.update(archived_at=timezone.now())
    return count
