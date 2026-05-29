from decimal import Decimal

from django.db import models
from django.utils import timezone


class ShiftStatus(models.TextChoices):
    OPEN = "open", "Открыта"
    CLOSED = "closed", "Закрыта"


class CashOperationType(models.TextChoices):
    CASH_IN = "cash_in", "Внесение"
    CASH_OUT = "cash_out", "Изъятие"


class CashShift(models.Model):
    """Кассовая смена. Один открытый CashShift на ресторан в любой момент."""

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="shifts"
    )
    cashier = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="shifts"
    )
    status = models.CharField(
        max_length=10,
        choices=ShiftStatus.choices,
        default=ShiftStatus.OPEN,
        db_index=True,
    )
    number = models.PositiveIntegerField()  # порядковый № в ресторане
    opening_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    closing_balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    # фактическая сумма, которую кассир насчитал при закрытии
    actual_balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    opened_at = models.DateTimeField(default=timezone.now, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = "cash_shifts"
        ordering = ["-opened_at"]
        verbose_name = "Кассовая смена"
        verbose_name_plural = "Кассовые смены"

    def __str__(self) -> str:
        return f"Смена №{self.number} [{self.status}]"

    # ---------- computed ----------

    def _revenue_by_method(self, method: str) -> Decimal:
        """Считает выручку по способу оплаты с учётом Phase 4 multi-payment.

        Если у заказа есть OrderPayment-ы — берём суммы из них (точные за метод).
        Если нет (legacy) — fallback на Order.total с Order.payment_method.
        """
        from apps.orders.models import Order, OrderPayment, OrderStatus

        done = Order.objects.filter(shift=self, status=OrderStatus.DONE)
        total = Decimal("0.00")

        # 1) точные суммы из OrderPayment
        op_qs = OrderPayment.objects.filter(order__in=done, method=method)
        agg = op_qs.aggregate(s=models.Sum("amount"))
        total += agg["s"] or Decimal("0.00")

        # 2) legacy-заказы без OrderPayment-ов: fallback на Order.payment_method
        orders_with_payments = set(
            OrderPayment.objects.filter(order__in=done)
            .values_list("order_id", flat=True)
        )
        legacy = done.filter(payment_method=method).exclude(
            id__in=orders_with_payments,
        )
        for o in legacy:
            total += o.total
        return total

    @property
    def cash_revenue(self) -> Decimal:
        """Сумма наличных оплат за смену (с учётом multi-payment)."""
        from apps.orders.models import PaymentMethod

        return self._revenue_by_method(PaymentMethod.CASH)

    @property
    def card_revenue(self) -> Decimal:
        from apps.orders.models import PaymentMethod

        return self._revenue_by_method(PaymentMethod.CARD)

    @property
    def transfer_revenue(self) -> Decimal:
        from apps.orders.models import PaymentMethod

        return self._revenue_by_method(PaymentMethod.TRANSFER)

    @property
    def cash_in_total(self) -> Decimal:
        agg = self.operations.filter(
            kind=CashOperationType.CASH_IN
        ).aggregate(s=models.Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def cash_out_total(self) -> Decimal:
        agg = self.operations.filter(
            kind=CashOperationType.CASH_OUT
        ).aggregate(s=models.Sum("amount"))
        return agg["s"] or Decimal("0.00")

    @property
    def expected_balance(self) -> Decimal:
        """Ожидаемый остаток в кассе:
        opening_balance + cash_revenue + cash_in − cash_out."""
        return (
            self.opening_balance
            + self.cash_revenue
            + self.cash_in_total
            - self.cash_out_total
        )

    @property
    def discrepancy(self) -> Decimal | None:
        if self.actual_balance is None:
            return None
        return self.actual_balance - self.expected_balance

    @property
    def orders_count(self) -> int:
        from apps.orders.models import Order, OrderStatus

        return Order.objects.filter(
            shift=self, status=OrderStatus.DONE
        ).count()

    @property
    def guests_count(self) -> int:
        from apps.orders.models import Order, OrderStatus

        agg = Order.objects.filter(
            shift=self, status=OrderStatus.DONE
        ).aggregate(s=models.Sum("guests_count"))
        return int(agg["s"] or 0)

    @property
    def average_check(self) -> Decimal:
        n = self.orders_count
        if n == 0:
            return Decimal("0.00")
        return (self.cash_revenue + self.card_revenue + self.transfer_revenue) / n


class CashShiftOperation(models.Model):
    """Внесение / изъятие наличных в течение смены."""

    shift = models.ForeignKey(
        CashShift, on_delete=models.CASCADE, related_name="operations"
    )
    kind = models.CharField(max_length=10, choices=CashOperationType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "cash_shift_operations"
        ordering = ["-created_at"]
        verbose_name = "Операция по смене"
        verbose_name_plural = "Операции по смене"
