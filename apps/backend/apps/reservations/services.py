"""Сервисы резерваций — бизнес-логика create/confirm/seat/cancel/no_show."""
from datetime import timedelta
from decimal import Decimal  # noqa: F401  (used in type-checking)

from django.db import transaction
from django.utils import timezone

from common.exceptions import BusinessError

from .models import Reservation, ReservationStatus


def _has_overlap(*, table, start, duration_min, exclude_id=None) -> bool:
    """True если на этом столе есть pending/confirmed резервация, окно которой
    пересекается с [start, start+duration]."""
    end = start + timedelta(minutes=int(duration_min))
    qs = Reservation.objects.filter(
        table=table,
        status__in=(ReservationStatus.PENDING, ReservationStatus.CONFIRMED),
        scheduled_at__lt=end,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    for r in qs:
        if r.end_at > start:
            return True
    return False


@transaction.atomic
def create_reservation(
    *,
    restaurant,
    table,
    customer_name: str,
    customer_phone: str = "",
    party_size: int = 2,
    scheduled_at,
    duration_min: int = 120,
    notes: str = "",
    user=None,
) -> Reservation:
    """Создать резервацию.

    Валидация:
    - `scheduled_at` в будущем (или хотя бы не более 5 минут в прошлом — для
      случая когда оператор оформляет «прямо сейчас»).
    - `party_size > 0`, `party_size <= table.capacity * 2` (мягкий лимит для
      случая «сдвинули стулья»; жёстко не блокируем).
    - Стол того же ресторана.
    - Нет пересечений с другой активной (pending/confirmed) бронью на этом столе.
    """
    if table.restaurant_id != restaurant.id:
        raise BusinessError("TABLE_NOT_FOUND", "Стол не найден", 404)
    if not customer_name.strip():
        raise BusinessError(
            "INVALID_TRANSITION", "Имя гостя обязательно", 422,
        )
    if int(party_size) <= 0:
        raise BusinessError(
            "INVALID_TRANSITION", "Кол-во гостей должно быть > 0", 422,
        )
    if int(duration_min) <= 0:
        raise BusinessError(
            "INVALID_TRANSITION", "Длительность должна быть > 0", 422,
        )

    grace_past = timezone.now() - timedelta(minutes=5)
    if scheduled_at < grace_past:
        raise BusinessError(
            "RESERVATION_IN_PAST",
            "Нельзя бронировать на прошедшее время", 422,
        )

    if _has_overlap(
        table=table, start=scheduled_at, duration_min=duration_min,
    ):
        raise BusinessError(
            "RESERVATION_CONFLICT",
            f"На {table.name} уже есть активная бронь на это время", 409,
        )

    r = Reservation.objects.create(
        restaurant=restaurant, table=table,
        customer_name=customer_name.strip(),
        customer_phone=customer_phone.strip(),
        party_size=int(party_size),
        scheduled_at=scheduled_at,
        duration_min=int(duration_min),
        notes=notes.strip(),
        created_by=user,
        status=ReservationStatus.PENDING,
    )
    from apps.audit.services import audit_log
    audit_log(
        user, "reservation_created", target=r,
        payload={
            "table_id": table.id,
            "table_name": table.name,
            "customer_name": r.customer_name,
            "party_size": r.party_size,
            "scheduled_at": r.scheduled_at.isoformat(),
        },
    )
    return r


@transaction.atomic
def confirm_reservation(*, reservation_id: int, restaurant, user) -> Reservation:
    try:
        r = Reservation.objects.select_for_update().get(
            id=reservation_id, restaurant=restaurant,
        )
    except Reservation.DoesNotExist as exc:
        raise BusinessError(
            "RESERVATION_NOT_FOUND", "Резервация не найдена", 404,
        ) from exc
    if r.status != ReservationStatus.PENDING:
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя подтвердить из статуса {r.status}", 409,
        )
    r.status = ReservationStatus.CONFIRMED
    r.save(update_fields=["status", "updated_at"])
    from apps.audit.services import audit_log
    audit_log(user, "reservation_confirmed", target=r, payload={})
    return r


@transaction.atomic
def cancel_reservation(
    *, reservation_id: int, restaurant, user, reason: str = "",
) -> Reservation:
    try:
        r = Reservation.objects.select_for_update().get(
            id=reservation_id, restaurant=restaurant,
        )
    except Reservation.DoesNotExist as exc:
        raise BusinessError(
            "RESERVATION_NOT_FOUND", "Резервация не найдена", 404,
        ) from exc
    if r.status in (
        ReservationStatus.SEATED, ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
    ):
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя отменить из статуса {r.status}", 409,
        )
    r.status = ReservationStatus.CANCELLED
    r.cancelled_at = timezone.now()
    r.cancel_reason = (reason or "").strip()
    r.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    from apps.audit.services import audit_log
    audit_log(
        user, "reservation_cancelled", target=r,
        payload={"reason": r.cancel_reason},
    )
    return r


@transaction.atomic
def mark_no_show(*, reservation_id: int, restaurant, user) -> Reservation:
    try:
        r = Reservation.objects.select_for_update().get(
            id=reservation_id, restaurant=restaurant,
        )
    except Reservation.DoesNotExist as exc:
        raise BusinessError(
            "RESERVATION_NOT_FOUND", "Резервация не найдена", 404,
        ) from exc
    if r.status not in (
        ReservationStatus.PENDING, ReservationStatus.CONFIRMED,
    ):
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя отметить как «не пришли» из статуса {r.status}", 409,
        )
    r.status = ReservationStatus.NO_SHOW
    r.save(update_fields=["status", "updated_at"])
    from apps.audit.services import audit_log
    audit_log(user, "reservation_no_show", target=r, payload={})
    return r


@transaction.atomic
def seat_reservation(
    *, reservation_id: int, restaurant, user, order=None,
) -> Reservation:
    """Отметить «гости пришли» и (опц.) привязать созданный заказ.

    Обычно: cashier открывает резервацию → seat → переход к создания заказа
    (стандартный flow create_order). После создания заказа вызвать второй раз
    с `order=<created>` чтобы привязать. В простом варианте — просто меняем
    статус, без order.
    """
    try:
        r = Reservation.objects.select_for_update().get(
            id=reservation_id, restaurant=restaurant,
        )
    except Reservation.DoesNotExist as exc:
        raise BusinessError(
            "RESERVATION_NOT_FOUND", "Резервация не найдена", 404,
        ) from exc
    if r.status not in (
        ReservationStatus.PENDING, ReservationStatus.CONFIRMED,
    ):
        raise BusinessError(
            "INVALID_TRANSITION",
            f"Нельзя посадить из статуса {r.status}", 409,
        )
    r.status = ReservationStatus.SEATED
    r.seated_at = timezone.now()
    if order is not None:
        r.seated_order = order
    r.save(update_fields=[
        "status", "seated_at", "seated_order", "updated_at",
    ])
    from apps.audit.services import audit_log
    audit_log(
        user, "reservation_seated", target=r,
        payload={"order_id": (order.id if order else None)},
    )
    return r


def active_reservations_for_table(table, *, lookahead_min: int = 30):
    """Резервации, активные сейчас или в ближайшие N минут.

    Используется для бейджа «Резерв 19:30» на TableCard. Возвращает
    QuerySet, отсортированный по scheduled_at asc.
    """
    now = timezone.now()
    horizon = now + timedelta(minutes=int(lookahead_min))
    return Reservation.objects.filter(
        table=table,
        status__in=(ReservationStatus.PENDING, ReservationStatus.CONFIRMED),
        scheduled_at__lt=horizon,
    ).order_by("scheduled_at")
