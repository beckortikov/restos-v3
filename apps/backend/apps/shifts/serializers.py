from rest_framework import serializers

from .models import CashShift, CashShiftOperation


class CashShiftOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashShiftOperation
        fields = ["id", "kind", "amount", "reason", "created_at"]


class CashShiftSerializer(serializers.ModelSerializer):
    cashier_name = serializers.CharField(source="cashier.full_name", read_only=True)
    cash_revenue = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    card_revenue = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    transfer_revenue = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    expected_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    discrepancy = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, allow_null=True
    )
    orders_count = serializers.IntegerField(read_only=True)
    guests_count = serializers.IntegerField(read_only=True)
    average_check = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = CashShift
        fields = [
            "id",
            "number",
            "status",
            "cashier",
            "cashier_name",
            "opening_balance",
            "closing_balance",
            "actual_balance",
            "opened_at",
            "closed_at",
            "note",
            "cash_revenue",
            "card_revenue",
            "transfer_revenue",
            "expected_balance",
            "discrepancy",
            "orders_count",
            "guests_count",
            "average_check",
        ]


class OpenShiftSerializer(serializers.Serializer):
    opening_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0,
    )


class CloseShiftSerializer(serializers.Serializer):
    actual_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0,
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class CashOpSerializer(serializers.Serializer):
    """POST /shifts/{id}/cash_op/  body."""

    KIND_CHOICES = ("cash_in", "cash_out")
    kind = serializers.ChoiceField(choices=KIND_CHOICES)
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0,
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")
