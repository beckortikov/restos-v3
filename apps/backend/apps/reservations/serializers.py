from rest_framework import serializers

from .models import Reservation


class ReservationSerializer(serializers.ModelSerializer):
    table_name = serializers.CharField(source="table.name", read_only=True)
    end_at = serializers.DateTimeField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Reservation
        fields = [
            "id",
            "table",
            "table_name",
            "customer_name",
            "customer_phone",
            "party_size",
            "scheduled_at",
            "duration_min",
            "end_at",
            "status",
            "is_active",
            "notes",
            "seated_order",
            "seated_at",
            "cancelled_at",
            "cancel_reason",
            "created_at",
            "updated_at",
        ]


class ReservationCreateSerializer(serializers.Serializer):
    table = serializers.IntegerField(min_value=1)
    customer_name = serializers.CharField(max_length=128)
    customer_phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="",
    )
    party_size = serializers.IntegerField(min_value=1, default=2)
    scheduled_at = serializers.DateTimeField()
    duration_min = serializers.IntegerField(min_value=1, default=120)
    notes = serializers.CharField(
        required=False, allow_blank=True, default="",
    )


class ReservationCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
