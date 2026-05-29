"""Audit log — журнал важных действий пользователей.

Для compliance, расследования споров, и восстановления хронологии.
Запись неизменяема (нет update, нет delete через API). Хранится столько,
сколько нужно бизнесу (auto-archive — отдельный cron).
"""
from django.db import models


class AuditAction(models.TextChoices):
    # Auth
    LOGIN = "login", "Вход"
    LOGOUT = "logout", "Выход"
    PIN_CHANGE = "pin_change", "Смена PIN"
    # Shifts
    SHIFT_OPEN = "shift_open", "Открытие смены"
    SHIFT_CLOSE = "shift_close", "Закрытие смены"
    Z_REPORT_PRINTED = "z_report_printed", "Печать Z-отчёта"
    X_REPORT_PRINTED = "x_report_printed", "Печать X-отчёта"
    CASH_IN = "cash_in", "Внесение в кассу"
    CASH_OUT = "cash_out", "Изъятие из кассы"
    # Orders
    ORDER_CREATE = "order_create", "Создание заказа"
    ORDER_ADD_ITEMS = "order_add_items", "Добавление позиций"
    ORDER_CANCEL = "order_cancel", "Отмена заказа"
    ORDER_CLOSE = "order_close", "Закрытие заказа (оплата)"
    ORDER_TRANSFER = "order_transfer", "Перенос на другой стол"
    ITEM_CANCEL = "item_cancel", "Отмена позиции"
    BILL_REQUEST = "bill_request", "Запрос счёта"
    DISCOUNT_APPLY = "discount_apply", "Применение скидки"
    DISCOUNT_REMOVE = "discount_remove", "Снятие скидки"
    REFUND = "refund", "Возврат"
    # Users / settings
    USER_CREATE = "user_create", "Создание пользователя"
    USER_UPDATE = "user_update", "Изменение пользователя"
    USER_DELETE = "user_delete", "Удаление пользователя"
    SETTINGS_UPDATE = "settings_update", "Изменение настроек"
    MANAGER_OVERRIDE = "manager_override", "Подтверждение менеджера"
    # Tables
    TABLES_MERGED = "tables_merged", "Объединение столов"
    TABLES_UNMERGED = "tables_unmerged", "Разъединение столов"
    # Kitchen / KDS
    KITCHEN_START_COOKING = "kitchen_start_cooking", "Кухня: взято в работу"
    KITCHEN_MARK_READY = "kitchen_mark_ready", "Кухня: готово"
    KITCHEN_MARK_SERVED = "kitchen_mark_served", "Кухня: выдано"
    # Reservations
    RESERVATION_CREATED = "reservation_created", "Создана резервация"
    RESERVATION_CONFIRMED = "reservation_confirmed", "Резервация подтверждена"
    RESERVATION_SEATED = "reservation_seated", "Гости резервации пришли"
    RESERVATION_CANCELLED = "reservation_cancelled", "Резервация отменена"
    RESERVATION_NO_SHOW = "reservation_no_show", "Гости резервации не пришли"


class AuditEntry(models.Model):
    """Неизменяемая запись о действии пользователя."""

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="audit_entries", db_index=True,
    )
    user = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_entries",
    )
    user_full_name = models.CharField(
        max_length=128, blank=True,
        help_text="Snapshot имени пользователя на момент действия",
    )
    action = models.CharField(
        max_length=24, choices=AuditAction.choices, db_index=True,
    )
    # Тип объекта-цели и его id (Order, User, PaymentProvider, и т.д.)
    target_type = models.CharField(max_length=32, blank=True, db_index=True)
    target_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    # Произвольный JSON с дополнительными данными (сумма, причина, diff).
    payload = models.JSONField(default=dict, blank=True)
    # IP клиента (опционально, может пригодиться для расследования).
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_entries"
        ordering = ["-created_at"]
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал действий"
        indexes = [
            models.Index(
                fields=["restaurant", "-created_at"], name="audit_resto_date_idx"
            ),
            models.Index(
                fields=["restaurant", "action", "-created_at"],
                name="audit_resto_action_idx",
            ),
        ]

    def __str__(self) -> str:
        who = self.user_full_name or (self.user.username if self.user else "—")
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {who} {self.action}"
