from decimal import Decimal

from django.db import models


class OrderStatus(models.TextChoices):
    NEW = "new", "Новый"
    BILL_REQUESTED = "bill_requested", "Счёт"
    DONE = "done", "Оплачен"
    CANCELLED = "cancelled", "Отменён"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Наличные"
    CARD = "card", "Карта"
    TRANSFER = "transfer", "Перевод"


class OrderType(models.TextChoices):
    HALL = "hall", "Зал"
    TAKEAWAY = "takeaway", "С собой"
    DELIVERY = "delivery", "Доставка"


class Order(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="orders"
    )
    # Ссылка на текущую кассовую смену (Phase 3). nullable: до Phase 3 заказы
    # создавались без смены; новые DONE-заказы привязываются автоматически
    # в orders.services.close_order.
    shift = models.ForeignKey(
        "shifts.CashShift",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    order_type = models.CharField(
        max_length=10,
        choices=OrderType.choices,
        default=OrderType.HALL,
        db_index=True,
    )
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.NEW, db_index=True
    )
    # nullable: takeaway/delivery не привязаны к столу
    table = models.ForeignKey(
        "tables.Table", on_delete=models.PROTECT,
        related_name="orders", null=True, blank=True,
    )
    # Минимальная контактная инфа для takeaway/delivery (для hall — пусто).
    customer_name = models.CharField(max_length=128, blank=True)
    customer_phone = models.CharField(max_length=32, blank=True)
    customer_address = models.CharField(max_length=255, blank=True)
    waiter = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="orders_as_waiter"
    )
    cashier = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_as_cashier",
    )
    guests_count = models.PositiveSmallIntegerField(default=1)
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, null=True, blank=True
    )
    comment = models.TextField(blank=True)
    idempotency_key = models.UUIDField(unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    bill_requested_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_cancelled",
    )
    cancel_reason = models.TextField(blank=True)
    # Архивирован: management command `archive_orders` помечает закрытые/
    # отменённые заказы старше N дней. Архивные не показываются в списках
    # по умолчанию; доступ через `?include_archived=true`. Записи не удаляются —
    # сохраняются для compliance / фискальной отчётности.
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Snapshot ставки сервисного сбора (% от подытога) на момент создания
    # заказа. Источник — active Discount(type='service'). Если изменили в
    # настройках после создания — закрытые заказы не меняются (snapshot).
    service_charge_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Сервисный сбор в %, snapshot из настроек на момент создания",
    )
    # Применённая кассиром скидка — Phase 4. Один к одному, FK для аналитики
    # (какая скидка чаще применяется), а snapshot kind/value/pct — на случай
    # удаления Discount или смены его параметров после применения.
    applied_discount = models.ForeignKey(
        "orders.Discount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_orders",
    )
    discount_kind = models.CharField(
        max_length=10, blank=True,
        help_text="percent | fixed (snapshot из Discount.kind на момент применения)",
    )
    discount_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Значение скидки snapshot (% или TJS). 0 = скидка не применена",
    )
    # Чаевые гостя — добавляются к итогу заказа сверху, не разносятся как
    # отдельный платёж (Phase 6+ — отдельный учёт чаевых официантам).
    # 0.00 = нет чаевых.
    tip_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Чаевые гостя в валюте заказа",
    )
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = "orders"
        ordering = ["-created_at"]
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"

    def __str__(self) -> str:
        return f"Order #{self.id} [{self.status}]"

    @property
    def subtotal(self) -> Decimal:
        """Сумма позиций без скидок и сервиса."""
        return sum(
            (it.subtotal for it in self.items.all() if it.cancelled_at is None),
            Decimal("0.00"),
        )

    @property
    def service_charge_amount(self) -> Decimal:
        """Сумма сервисного сбора в валюте (от subtotal — без учёта скидки)."""
        from decimal import ROUND_HALF_UP

        if not self.service_charge_pct:
            return Decimal("0.00")
        return (self.subtotal * self.service_charge_pct / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def discount_amount(self) -> Decimal:
        """Сумма скидки. Применяется к subtotal (до сервисного сбора)."""
        from decimal import ROUND_HALF_UP

        if not self.discount_kind or not self.discount_value:
            return Decimal("0.00")
        if self.discount_kind == "percent":
            amount = (self.subtotal * self.discount_value / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:  # fixed
            amount = Decimal(self.discount_value)
        # Скидка не больше подытога.
        return min(amount, self.subtotal)

    @property
    def total(self) -> Decimal:
        """Итог к оплате: subtotal + service_charge − discount + tip.

        Если получилось отрицательное (нереалистично, защита) — округляем до 0.
        """
        tip = Decimal(self.tip_amount or 0)
        result = (
            self.subtotal
            + self.service_charge_amount
            - self.discount_amount
            + tip
        )
        return max(result, Decimal("0.00"))

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED)


class KitchenStatus(models.TextChoices):
    """Статус кухни для одной позиции заказа.

    Lifecycle для каждой OrderItem:
        new → cooking → ready → served
    Cancel — параллельный путь через OrderItem.cancelled_at (не статус).
    """
    NEW = "new", "Новая"
    COOKING = "cooking", "Готовится"
    READY = "ready", "Готово"
    SERVED = "served", "Выдано"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey("menu.MenuItem", on_delete=models.PROTECT)
    name_at_order = models.CharField(max_length=128)
    price_at_order = models.DecimalField(max_digits=14, decimal_places=2)
    qty = models.PositiveIntegerField(default=1)
    # Комментарий гостя/кассира к позиции (snapshot — печатается на кухню):
    # «Без лука», «Хорошо прожарить», и т.д. Источник: MenuItemNote шаблоны.
    note = models.CharField(max_length=255, blank=True)
    # Статус кухни — Phase 2 KDS. Каждая позиция движется по lifecycle
    # независимо: повар жмёт «Принять» → «Готово» → официант жмёт «Выдано».
    kitchen_status = models.CharField(
        max_length=12, choices=KitchenStatus.choices,
        default=KitchenStatus.NEW, db_index=True,
    )
    started_cooking_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)
    cooked_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.TextField(blank=True)
    # Phase 4 — отправлена ли позиция на кухню (печать KITCHEN_ORDER runner'а).
    # null = ещё не отправлена → видна в OrderDetailPanel как «новая, ждёт fire».
    # При create_order все позиции автосделают timestamp (enqueue_kitchen_prints).
    # При add_items_to_order — null, пока кассир не нажмёт «НА КУХНЮ».
    sent_to_kitchen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Phase 8E — момент списания со склада/декремента prepared_qty.
    # Заполняется на create_order/add_items_to_order сразу после создания позиции.
    # Если null — close_order вызовет fallback consume (для старых ордеров).
    # При cancel_item с consumed_at != null — нужно реверс-движение (TODO).
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_items"
        ordering = ["id"]
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"

    def __str__(self) -> str:
        return f"{self.name_at_order} ×{self.qty}"

    @property
    def modifiers_total_per_unit(self) -> Decimal:
        """Сумма price_delta всех выбранных модификаторов (за единицу qty)."""
        return sum(
            (m.price_delta_at_order for m in self.modifiers.all()),
            Decimal("0.00"),
        )

    @property
    def subtotal(self) -> Decimal:
        """Цена блюда + дельты модификаторов, умноженные на qty."""
        return (self.price_at_order + self.modifiers_total_per_unit) * self.qty


class OrderItemModifier(models.Model):
    """Snapshot выбранного модификатора в момент заказа.

    Хранит name/price_delta «как было» — даже если потом админ переименует
    модификатор или изменит цену, чек/история останутся корректными.
    """

    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name="modifiers"
    )
    modifier = models.ForeignKey(
        "menu.Modifier", on_delete=models.PROTECT, related_name="+",
    )
    name_at_order = models.CharField(max_length=64)
    price_delta_at_order = models.DecimalField(max_digits=14, decimal_places=2)
    group_name_at_order = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_item_modifiers"
        ordering = ["id"]
        verbose_name = "Модификатор позиции"
        verbose_name_plural = "Модификаторы позиций"

    def __str__(self) -> str:
        sign = "+" if self.price_delta_at_order >= 0 else ""
        return f"{self.name_at_order} ({sign}{self.price_delta_at_order})"


class RefundOperation(models.Model):
    """Возврат по закрытому заказу — frame 13.

    Один RefundOperation = одна транзакция возврата (может включать несколько
    позиций, частично или полностью). На один Order может быть несколько Refund'ов.
    Уменьшает наличный остаток смены через CashShiftOperation(kind=cash_out).
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="refunds"
    )
    order = models.ForeignKey(
        Order, on_delete=models.PROTECT, related_name="refunds"
    )
    cashier = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="refunds_made"
    )
    shift = models.ForeignKey(
        "shifts.CashShift",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refunds",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField()
    idempotency_key = models.UUIDField(unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "refund_operations"
        ordering = ["-created_at"]
        verbose_name = "Возврат"
        verbose_name_plural = "Возвраты"

    def __str__(self) -> str:
        return f"Refund #{self.id} order=#{self.order_id} {self.amount}"


class PaymentProviderKind(models.TextChoices):
    CASH = "cash", "Наличные"
    CARD = "card", "Банковская карта"
    QR = "qr", "QR-оплата"
    WALLET = "wallet", "Мобильный кошелёк"
    TRANSFER = "transfer", "Перевод"


class PaymentProvider(models.Model):
    """Способ оплаты — frame 21 «Настройки → Способы оплаты».

    Не путать с enum `PaymentMethod` (он остаётся для обратной совместимости
    Order.payment_method и аналитики). PaymentProvider — это «реальный»
    провайдер платежа в конкретном ресторане: касса, эквайер «Alif Pay»,
    QR-провайдер и т.д. Админ настраивает их в UI; в Phase 2 кассир будет
    выбирать конкретного провайдера при оплате (и его комиссия попадёт
    в финансовый отчёт).
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="payment_providers"
    )
    name = models.CharField(max_length=64)
    kind = models.CharField(
        max_length=10, choices=PaymentProviderKind.choices, db_index=True
    )
    description = models.CharField(max_length=255, blank=True)
    commission_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, help_text="Комиссия в %"
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payment_providers"
        ordering = ["sort_order", "name"]
        verbose_name = "Способ оплаты"
        verbose_name_plural = "Способы оплаты"

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class DiscountKind(models.TextChoices):
    PERCENT = "percent", "Процент"
    FIXED = "fixed", "Фиксированная"


class Discount(models.Model):
    """Скидка / Сервисный сбор — frame 22 «Скидки и сервис».

    type = "service" — единственная сервисная карточка ресторана (UNIQUE
    с restaurant в коде сервиса/UI; в БД допустим одна на ресторан).
    type = "discount" — обычная скидка (постоянная клиентская, акционная).
    Применение скидки к заказу — Phase 4+ (модель Order расширим
    через OrderDiscount).
    """

    DISCOUNT = "discount"
    SERVICE = "service"
    TYPE_CHOICES = [(DISCOUNT, "Скидка"), (SERVICE, "Сервисный сбор")]

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="discounts"
    )
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=DISCOUNT)
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(
        max_length=10, choices=DiscountKind.choices, default=DiscountKind.PERCENT
    )
    value = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Процент 0–100 либо фиксированная сумма",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discounts"
        ordering = ["type", "sort_order", "name"]
        verbose_name = "Скидка"
        verbose_name_plural = "Скидки"

    def __str__(self) -> str:
        return f"{self.name} ({self.value}{'%' if self.kind == 'percent' else ''})"


class CancelReasonKind(models.TextChoices):
    ITEM = "item", "Отмена позиции"
    ORDER = "order", "Отмена заказа"
    REFUND = "refund", "Возврат"


class CancelReason(models.Model):
    """Причины отмены / возврата — настраиваются админом через UI «Настройки».

    Архитектурный принцип: пользовательские бизнес-строки НЕ хардкодим в код,
    а грузим из БД. Это ускоряет ввод (чипы быстрого выбора) и даёт каждому
    ресторану свои варианты ("гость передумал", "ошибка кассира", и т.д.).
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="cancel_reasons"
    )
    kind = models.CharField(
        max_length=10, choices=CancelReasonKind.choices, db_index=True
    )
    label = models.CharField(max_length=128)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cancel_reasons"
        ordering = ["kind", "sort_order", "label"]
        verbose_name = "Причина отмены"
        verbose_name_plural = "Причины отмены"
        unique_together = [("restaurant", "kind", "label")]

    def __str__(self) -> str:
        return f"{self.kind}: {self.label}"


class RefundedItem(models.Model):
    """Позиция в составе RefundOperation. qty ≤ qty оригинальной OrderItem."""

    refund = models.ForeignKey(
        RefundOperation, on_delete=models.CASCADE, related_name="items"
    )
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.PROTECT, related_name="refunds"
    )
    qty = models.PositiveIntegerField()
    price_at_refund = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "refunded_items"
        ordering = ["id"]
        verbose_name = "Возвращённая позиция"
        verbose_name_plural = "Возвращённые позиции"

    @property
    def subtotal(self) -> Decimal:
        return self.price_at_refund * self.qty

    def __str__(self) -> str:
        return f"{self.order_item.name_at_order} ×{self.qty} (refund)"



class OrderPayment(models.Model):
    """Платёж по заказу — Phase 4 multi-payment.

    Позволяет «3000 наличкой + 2000 картой» на один заказ.
    Order.payment_method остаётся как denormalized «primary» способ
    (последний/наибольший по сумме), для backwards-compat в отчётах
    и одинарных оплатах. sum(payments.amount) должен равняться order.total.
    """

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="payments"
    )
    method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # Дальше Phase 4+: account FK на FinancialAccount. Сейчас не нужен.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_payments"
        ordering = ["id"]
        verbose_name = "Платёж по заказу"
        verbose_name_plural = "Платежи по заказам"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="orderpayment_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Order #{self.order_id}: {self.method} {self.amount}"
