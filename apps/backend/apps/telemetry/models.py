"""Модели телеметрии — минимальные агрегаты от ресторанов.

Две модели:
- `TelemetrySnapshot` (cloud): что cloud принял и хранит. Один snapshot
  на (restaurant, business_date) — обновляется в течение дня.
- `PendingTelemetrySnapshot` (restaurant): локальный буфер на случай
  «нет связи с cloud», накапливается пока не получится push.

Эти модели используются на РАЗНЫХ инстансах:
- На cloud-инстансе живёт `TelemetrySnapshot` — но Django создаёт обе
  таблицы везде. На restaurant-инстансе `TelemetrySnapshot` остаётся
  пустой (туда писать не нужно).
"""
from django.db import models


class TelemetrySnapshot(models.Model):
    """Cloud-side: агрегаты, полученные от ресторана.

    Один snapshot на пару (restaurant, business_date). Если в течение дня
    приходит несколько push'ей — мы делаем upsert и обновляем агрегаты
    последними значениями (накопительные с начала дня).

    НЕ хранит: имена кассиров, детали блюд, конкретные заказы, чеки.
    Это всё остаётся локально у ресторана. Cloud видит только цифры
    для биллинга и SLA-мониторинга.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="telemetry_snapshots",
    )
    business_date = models.DateField(
        db_index=True,
        help_text="Календарная дата в TZ ресторана. Один snapshot/день.",
    )
    captured_at = models.DateTimeField(
        help_text="Когда ресторан сформировал этот snapshot",
    )
    received_at = models.DateTimeField(
        auto_now=True,
        help_text="Когда cloud получил этот push",
    )

    # Финансовые агрегаты
    daily_revenue = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Выручка с 00:00 до captured_at (закрытые заказы)",
    )
    daily_orders_count = models.PositiveIntegerField(
        default=0, help_text="Сколько закрытых заказов сегодня",
    )
    mtd_revenue = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Накопительно с 1-го числа месяца (month-to-date)",
    )

    # Status signals
    last_order_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Когда был последний закрытый заказ (любой день)",
    )
    open_shifts_count = models.PositiveSmallIntegerField(
        default=0, help_text="Сколько открытых смен сейчас",
    )
    app_version = models.CharField(
        max_length=32, blank=True,
        help_text="Версия POS-клиента в момент push'а",
    )

    class Meta:
        db_table = "telemetry_snapshots"
        ordering = ["-business_date", "restaurant_id"]
        unique_together = [("restaurant", "business_date")]
        verbose_name = "Телеметрия (день)"
        verbose_name_plural = "Телеметрия (по дням)"

    def __str__(self) -> str:
        return (
            f"{self.restaurant.name} {self.business_date}: "
            f"{self.daily_revenue} TJS, {self.daily_orders_count} зак."
        )


class RestaurantCatalogSnapshot(models.Model):
    """Cloud-side: каталог меню ресторана (singleton per restaurant).

    Хранит структуру категорий + блюд (без cogs / ингредиентов / рецептов).
    Обновляется при каждом push'е с ресторана — типично 1 раз в день
    или при изменении меню (через signal).

    Назначение:
    - Cloud admin видит «что продаёт» каждый клиент
    - Vendor может сравнивать ассортименты
    """

    restaurant = models.OneToOneField(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="catalog_snapshot",
    )
    data = models.JSONField(
        default=dict,
        help_text="{restaurant, categories[], items[], totals}",
    )
    updated_at = models.DateTimeField(auto_now=True)

    # Денормализованные счётчики для быстрого list_display
    categories_count = models.PositiveIntegerField(default=0)
    items_count = models.PositiveIntegerField(default=0)
    active_items_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "restaurant_catalog_snapshots"
        verbose_name = "Каталог меню ресторана"
        verbose_name_plural = "Каталоги меню ресторанов"

    def __str__(self) -> str:
        return (
            f"{self.restaurant.name}: "
            f"{self.items_count} блюд / {self.categories_count} категорий"
        )


class PendingTelemetrySnapshot(models.Model):
    """Restaurant-side: буфер на случай «нет связи с cloud».

    `collect_telemetry()` всегда пишет сюда; `push_telemetry()` пытается
    отправить все pending записи в cloud. На успех — удаляет; на ошибку —
    оставляет, попробуем в следующий раз. Так не теряем данные, даже
    если ресторан offline неделями.
    """

    # На restaurant-инстансе только 1 ресторан → можно не FK, но оставим
    # для теоретической поддержки multi-tenant на одном сервере.
    restaurant_id = models.PositiveIntegerField(db_index=True)
    business_date = models.DateField()
    captured_at = models.DateTimeField()
    payload = models.JSONField(
        help_text="Готовый payload для POST /api/v1/telemetry/push/",
    )
    attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text="Сколько раз пытались отправить — для exp.backoff",
    )
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pending_telemetry_snapshots"
        ordering = ["business_date", "captured_at"]
        unique_together = [("restaurant_id", "business_date")]
        verbose_name = "Pending telemetry"
        verbose_name_plural = "Pending telemetry"

    def __str__(self) -> str:
        return f"Pending<r={self.restaurant_id} d={self.business_date}>"
