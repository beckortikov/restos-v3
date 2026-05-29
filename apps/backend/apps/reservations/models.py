"""Резервации (бронь стола на конкретное время) — Phase 8.

Lifecycle:
    pending     — создана, ждёт подтверждения хостесс/менеджера
    confirmed   — подтверждена (звонком, ответом на SMS и т.д.)
    seated      — гости пришли, посажены за стол; привязан Order через seated_order
    cancelled   — отменена гостем заранее
    no_show     — гости не пришли в назначенное время

Бизнес-инвариант: на одном столе не должно быть двух «активных»
(pending/confirmed/seated) резерваций с пересечением времени.
Это проверяется в сервисе `create_reservation`, не в БД-constraint
(чтобы можно было отменять/no_show вручную задним числом без блокировок).
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone


class ReservationStatus(models.TextChoices):
    PENDING = "pending", "Ожидает подтверждения"
    CONFIRMED = "confirmed", "Подтверждена"
    SEATED = "seated", "Гости пришли"
    CANCELLED = "cancelled", "Отменена"
    NO_SHOW = "no_show", "Не пришли"


class Reservation(models.Model):
    """Бронь стола на конкретное время.

    Активные резервации (`pending`/`confirmed`) — те, у которых
    `scheduled_at <= now < scheduled_at + duration`. Используются для
    показа бейджа «Резерв 19:30» на TableCard.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="reservations",
    )
    table = models.ForeignKey(
        "tables.Table", on_delete=models.PROTECT,
        related_name="reservations",
        help_text="Зарезервированный стол. PROTECT — не удалять стол с активной бронью.",
    )
    customer_name = models.CharField(max_length=128)
    customer_phone = models.CharField(max_length=32, blank=True)
    party_size = models.PositiveSmallIntegerField(default=2)
    scheduled_at = models.DateTimeField(
        db_index=True,
        help_text="Время на которое забронировано",
    )
    duration_min = models.PositiveSmallIntegerField(
        default=120,
        help_text="Сколько времени держим бронь (по умолчанию 2 часа)",
    )
    status = models.CharField(
        max_length=12, choices=ReservationStatus.choices,
        default=ReservationStatus.PENDING, db_index=True,
    )
    notes = models.TextField(blank=True)
    seated_order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
        help_text="Заказ, который был открыт при посадке гостей",
    )
    seated_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reservations"
        ordering = ["-scheduled_at"]
        verbose_name = "Резервация"
        verbose_name_plural = "Резервации"
        indexes = [
            models.Index(fields=["restaurant", "scheduled_at"]),
            models.Index(fields=["table", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.customer_name} ×{self.party_size} on {self.table_id}"
            f" @ {self.scheduled_at:%d.%m %H:%M}"
        )

    @property
    def end_at(self):
        return self.scheduled_at + timedelta(minutes=int(self.duration_min))

    @property
    def is_active(self) -> bool:
        """Активна сейчас (в окне времени и не cancelled/no_show)."""
        if self.status in (
            ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW,
            ReservationStatus.SEATED,
        ):
            return False
        now = timezone.now()
        return self.scheduled_at <= now < self.end_at
