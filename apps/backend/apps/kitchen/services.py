"""Сервисы кухни: переходы статусов OrderItem.

Lifecycle:
    NEW → COOKING → READY → SERVED
Нельзя «прыгать» через статус (например NEW → READY) кроме SERVED, который
официант может проставить и из READY и из COOKING (для случая «уже готово было»).

Каждый переход:
- Логируется в audit
- Эмитит SSE event `kitchen.status_changed`
"""
from django.db import transaction
from django.utils import timezone

from apps.orders.models import KitchenStatus, OrderItem
from common.exceptions import BusinessError


_ALLOWED_TRANSITIONS = {
    KitchenStatus.NEW: {KitchenStatus.COOKING},
    KitchenStatus.COOKING: {KitchenStatus.READY},
    KitchenStatus.READY: {KitchenStatus.SERVED},
    KitchenStatus.SERVED: set(),
}


def _emit_event(item: OrderItem, action: str) -> None:
    """Шлёт SSE-event кухонного канала. Безопасно: если events app сломан, не падаем."""
    try:
        from apps.events.dispatch import publish

        publish(
            "kitchen.status_changed",
            restaurant_id=item.order.restaurant_id,
            payload={
                "order_id": item.order_id,
                "item_id": item.id,
                "kitchen_status": item.kitchen_status,
                "action": action,
            },
        )
    except Exception:
        pass


def _set_status(
    *, item_id: int, restaurant, target: str, user, audit_action: str,
) -> OrderItem:
    """Общий хелпер: select_for_update + проверка перехода + сохранение."""
    try:
        item = (
            OrderItem.objects.select_for_update()
            .select_related("order")
            .get(id=item_id, order__restaurant=restaurant)
        )
    except OrderItem.DoesNotExist as exc:
        raise BusinessError(
            "ORDER_ITEM_NOT_FOUND", "Позиция не найдена", 404,
        ) from exc

    if item.cancelled_at is not None:
        raise BusinessError(
            "INVALID_TRANSITION",
            "Позиция отменена — переходы кухни запрещены", 409,
        )

    current = item.kitchen_status
    if target == current:
        # Идемпотентно: уже в нужном статусе — не падаем, просто возвращаем.
        return item
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя перейти из {current} в {target}", 409,
        )

    now = timezone.now()
    fields_to_update = ["kitchen_status"]
    item.kitchen_status = target
    if target == KitchenStatus.COOKING:
        item.started_cooking_at = now
        item.cooked_by = user
        fields_to_update += ["started_cooking_at", "cooked_by"]
    elif target == KitchenStatus.READY:
        item.ready_at = now
        if item.cooked_by_id is None:
            item.cooked_by = user
            fields_to_update.append("cooked_by")
        fields_to_update.append("ready_at")
        # Печать runner'а готовности — официант видит, что блюдо готово.
        # Не блокируем переход, если печать не настроена / упала.
        try:
            from apps.printing.services import enqueue_ready_runner
            enqueue_ready_runner(item, cooked_by=user)
        except Exception:
            import logging
            logging.getLogger("apps.kitchen").exception(
                "ready_runner enqueue failed for item %s", item.id,
            )
    elif target == KitchenStatus.SERVED:
        item.served_at = now
        fields_to_update.append("served_at")
    item.save(update_fields=fields_to_update)

    from apps.audit.services import audit_log
    audit_log(
        user, audit_action, target=item,
        payload={
            "order_id": item.order_id,
            "item_name": item.name_at_order,
            "from_status": current,
            "to_status": target,
        },
    )
    _emit_event(item, audit_action)
    return item


@transaction.atomic
def start_cooking(*, item_id: int, restaurant, user) -> OrderItem:
    return _set_status(
        item_id=item_id, restaurant=restaurant,
        target=KitchenStatus.COOKING, user=user,
        audit_action="kitchen_start_cooking",
    )


@transaction.atomic
def mark_ready(*, item_id: int, restaurant, user) -> OrderItem:
    return _set_status(
        item_id=item_id, restaurant=restaurant,
        target=KitchenStatus.READY, user=user,
        audit_action="kitchen_mark_ready",
    )


@transaction.atomic
def mark_served(*, item_id: int, restaurant, user) -> OrderItem:
    """Может прыгнуть из NEW/COOKING/READY → SERVED.

    Waiter часто отмечает «подано» сразу — когда заведение без KDS или повар
    не успел тапнуть «В работу». Запрещён только переход с cancelled."""
    try:
        item = (
            OrderItem.objects.select_for_update()
            .select_related("order")
            .get(id=item_id, order__restaurant=restaurant)
        )
    except OrderItem.DoesNotExist as exc:
        raise BusinessError(
            "ORDER_ITEM_NOT_FOUND", "Позиция не найдена", 404,
        ) from exc

    if item.cancelled_at is not None:
        raise BusinessError(
            "INVALID_TRANSITION",
            "Позиция отменена", 409,
        )
    if item.kitchen_status == KitchenStatus.SERVED:
        return item

    now = timezone.now()
    # Если перепрыгнули через COOKING/READY — расставляем timestamps задним числом.
    if item.kitchen_status in (KitchenStatus.NEW, KitchenStatus.COOKING) and item.ready_at is None:
        item.ready_at = now
    if item.started_cooking_at is None:
        item.started_cooking_at = now
    prev = item.kitchen_status
    item.kitchen_status = KitchenStatus.SERVED
    item.served_at = now
    item.save(update_fields=["kitchen_status", "ready_at", "served_at", "started_cooking_at"])
    from apps.audit.services import audit_log
    audit_log(
        user, "kitchen_mark_served", target=item,
        payload={
            "order_id": item.order_id,
            "item_name": item.name_at_order,
            "from_status": prev,
        },
    )
    _emit_event(item, "kitchen_mark_served")
    return item


@transaction.atomic
def unmark_served(*, item_id: int, restaurant, user) -> OrderItem:
    """Откат «выдано» — для waiter, если случайно нажал. Откатывает
    kitchen_status SERVED → READY, чистит served_at."""
    try:
        item = (
            OrderItem.objects.select_for_update()
            .select_related("order")
            .get(id=item_id, order__restaurant=restaurant)
        )
    except OrderItem.DoesNotExist as exc:
        raise BusinessError(
            "ORDER_ITEM_NOT_FOUND", "Позиция не найдена", 404,
        ) from exc

    if item.kitchen_status != KitchenStatus.SERVED:
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя снять выдачу из {item.kitchen_status}", 409,
        )

    item.kitchen_status = KitchenStatus.READY
    item.served_at = None
    item.save(update_fields=["kitchen_status", "served_at"])
    from apps.audit.services import audit_log
    audit_log(
        user, "kitchen_unmark_served", target=item,
        payload={"order_id": item.order_id, "item_name": item.name_at_order},
    )
    _emit_event(item, "kitchen_unmark_served")
    return item


def list_kitchen_items(
    restaurant,
    *,
    statuses: list[str] | None = None,
    station=None,
):
    """Все активные (некоторые статусы + не cancelled) позиции для KDS-канбана.

    По умолчанию: NEW + COOKING + READY (SERVED скрываем — выдано, дело сделано).
    Если `station` задана — фильтр по category.print_station == station
    (для повара горячего цеха не показываем позиции бара).

    Используется в `/kitchen/items/`.
    """
    if statuses is None:
        statuses = [
            KitchenStatus.NEW,
            KitchenStatus.COOKING,
            KitchenStatus.READY,
        ]
    qs = (
        OrderItem.objects
        .filter(
            order__restaurant=restaurant,
            kitchen_status__in=statuses,
            cancelled_at__isnull=True,
        )
        .select_related("order", "order__table", "menu_item__category")
        .order_by("created_at")
    )
    if station is not None:
        qs = qs.filter(menu_item__category__print_station=station)
    return qs
