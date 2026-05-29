from rest_framework import serializers

from .models import (
    CancelReason,
    CancelReasonKind,
    Discount,
    DiscountKind,
    Order,
    OrderItem,
    OrderItemModifier,
    PaymentProvider,
    PaymentProviderKind,
    RefundedItem,
    RefundOperation,
)


class OrderItemModifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItemModifier
        fields = [
            "id", "modifier", "name_at_order",
            "price_delta_at_order", "group_name_at_order",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    modifiers = OrderItemModifierSerializer(many=True, read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "menu_item",
            "name_at_order",
            "price_at_order",
            "qty",
            "note",
            "cancelled_at",
            "cancel_reason",
            "sent_to_kitchen_at",
            "served_at",
            "kitchen_status",
            "subtotal",
            "modifiers",
        ]
        read_only_fields = ["name_at_order", "price_at_order", "sent_to_kitchen_at"]


class OrderItemWriteSerializer(serializers.Serializer):
    menu_item_id = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1, max_value=999)
    note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255,
    )
    modifier_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False, default=list,
    )


class OrderPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        from .models import OrderPayment
        model = OrderPayment
        fields = ["id", "method", "amount", "created_at"]


class CancelledItemSerializer(serializers.ModelSerializer):
    """Отменённая позиция — для истории voids в OrderDetail на клиенте."""

    cancelled_by_name = serializers.CharField(
        source="cancelled_by.full_name", read_only=True, default=None,
    )

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "menu_item",
            "name_at_order",
            "price_at_order",
            "qty",
            "cancel_reason",
            "cancelled_at",
            "cancelled_by",
            "cancelled_by_name",
        ]


class OrderSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    cancelled_items = serializers.SerializerMethodField()
    payments = OrderPaymentSerializer(many=True, read_only=True)
    # Локализованная подпись статуса — фронт не маппит сам.
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    def get_items(self, order) -> list[dict]:
        """Только активные позиции (без cancelled_at). Отменённые — в
        отдельном поле `cancelled_items` (audit-история для UI)."""
        active = order.items.filter(cancelled_at__isnull=True)
        return OrderItemSerializer(active, many=True, context=self.context).data

    def get_cancelled_items(self, order) -> list[dict]:
        cancelled = order.items.filter(cancelled_at__isnull=False).order_by("cancelled_at")
        return CancelledItemSerializer(cancelled, many=True, context=self.context).data
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    service_charge_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    discount_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    discount_name = serializers.CharField(
        source="applied_discount.name", read_only=True, default=None
    )
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    table_name = serializers.CharField(
        source="table.name", read_only=True, default=None
    )
    # Имя зоны стола («Зал», «Веранда», «Куча», ...) — нужно фронту, чтобы
    # не хардкодить «Зал». Для takeaway/delivery и заказов без стола = None.
    table_zone_name = serializers.CharField(
        source="table.zone.name", read_only=True, default=None,
    )
    waiter_name = serializers.CharField(source="waiter.full_name", read_only=True)
    cashier_name = serializers.CharField(
        source="cashier.full_name", read_only=True, default=None
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "status",
            "status_display",
            "order_type",
            "table",
            "table_name",
            "table_zone_name",
            "waiter",
            "waiter_name",
            "cashier",
            "cashier_name",
            "guests_count",
            "customer_name",
            "customer_phone",
            "customer_address",
            "payment_method",
            "payments",
            "comment",
            "items",
            "cancelled_items",
            "subtotal",
            "service_charge_pct",
            "service_charge_amount",
            "applied_discount",
            "discount_name",
            "discount_kind",
            "discount_value",
            "discount_amount",
            "tip_amount",
            "total",
            "created_at",
            "bill_requested_at",
            "closed_at",
            "cancelled_at",
            "cancel_reason",
            "updated_at",
        ]


class OrderCreateSerializer(serializers.Serializer):
    order_type = serializers.ChoiceField(
        choices=["hall", "takeaway", "delivery"],
        default="hall",
    )
    table_id = serializers.IntegerField(required=False, allow_null=True)
    guests_count = serializers.IntegerField(min_value=0, max_value=99, default=1)
    items = OrderItemWriteSerializer(many=True, min_length=1)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    customer_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=128
    )
    customer_phone = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=32
    )
    customer_address = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )

    def validate(self, attrs):
        ot = attrs.get("order_type", "hall")
        if ot == "hall" and not attrs.get("table_id"):
            raise serializers.ValidationError(
                {"table_id": "Обязателен для зала (order_type=hall)"}
            )
        if ot == "delivery" and not attrs.get("customer_address"):
            raise serializers.ValidationError(
                {"customer_address": "Обязателен для доставки"}
            )
        return attrs


class RefundedItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    name_at_order = serializers.CharField(
        source="order_item.name_at_order", read_only=True
    )

    class Meta:
        model = RefundedItem
        fields = [
            "id",
            "order_item",
            "name_at_order",
            "qty",
            "price_at_refund",
            "subtotal",
        ]


class RefundSerializer(serializers.ModelSerializer):
    items = RefundedItemSerializer(many=True, read_only=True)
    cashier_name = serializers.CharField(
        source="cashier.full_name", read_only=True
    )

    class Meta:
        model = RefundOperation
        fields = [
            "id",
            "order",
            "amount",
            "reason",
            "cashier",
            "cashier_name",
            "shift",
            "items",
            "created_at",
        ]


class CancelReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = CancelReason
        fields = ["id", "kind", "label", "sort_order", "is_active"]

    def validate_kind(self, value: str) -> str:
        if value not in CancelReasonKind.values:
            raise serializers.ValidationError(
                "kind должен быть item / order / refund"
            )
        return value


class PaymentProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentProvider
        fields = [
            "id", "kind", "name", "description",
            "commission_pct", "is_active", "sort_order",
        ]

    def validate_kind(self, value: str) -> str:
        if value not in PaymentProviderKind.values:
            raise serializers.ValidationError(
                "kind должен быть cash/card/qr/wallet/transfer"
            )
        return value


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = [
            "id", "type", "name", "description",
            "kind", "value", "is_active", "sort_order",
        ]

    def validate_type(self, value: str) -> str:
        if value not in {"discount", "service"}:
            raise serializers.ValidationError(
                "type должен быть discount или service"
            )
        return value

    def validate_kind(self, value: str) -> str:
        if value not in DiscountKind.values:
            raise serializers.ValidationError(
                "kind должен быть percent или fixed"
            )
        return value
