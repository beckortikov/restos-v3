from rest_framework import serializers

from .models import PayrollPeriod, TimeEntry


class TimeEntrySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)
    hours_worked = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )

    class Meta:
        model = TimeEntry
        fields = [
            "id", "user", "user_name", "user_role",
            "clock_in", "clock_out", "status",
            "hourly_rate_snapshot", "hours_worked", "note",
            "created_at",
        ]
        read_only_fields = [
            "clock_in", "clock_out", "status",
            "hourly_rate_snapshot", "created_at",
        ]


class PayrollPeriodSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    class Meta:
        model = PayrollPeriod
        fields = [
            "id", "user", "user_name",
            "period_start", "period_end",
            "hours_worked", "hourly_rate", "base_salary",
            "bonuses", "deductions", "total", "note",
            "status", "status_display", "paid_at", "paid_operation_id",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "hours_worked", "hourly_rate", "base_salary", "total",
            "status", "paid_at", "paid_operation_id",
            "created_at", "updated_at",
        ]
