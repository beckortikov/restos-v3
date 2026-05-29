"""Сериализаторы super-admin API."""
from __future__ import annotations

from rest_framework import serializers

from apps.licensing.models import License, LicensePlan
from apps.users.models import Restaurant


class SuperAdminLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=64)
    password = serializers.CharField(write_only=True, min_length=4)


class RestaurantBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        fields = [
            "id", "name", "address", "phone", "currency",
            "last_heartbeat_at", "app_version",
        ]


class RestaurantCreateSerializer(serializers.ModelSerializer):
    """SA создаёт ресторан. Триал-лицензия выдаётся автоматически через signal."""

    class Meta:
        model = Restaurant
        fields = ["id", "name", "address", "phone", "currency"]

    def validate_name(self, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise serializers.ValidationError("Название не может быть пустым")
        if Restaurant.objects.filter(name__iexact=v).exists():
            raise serializers.ValidationError(
                f"Ресторан с названием «{v}» уже существует"
            )
        return v


class LicenseSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()

    class Meta:
        model = License
        fields = [
            "id", "restaurant", "plan", "license_key",
            "started_at", "expires_at", "is_blocked", "block_reason",
            "notes", "created_at", "updated_at",
            "status", "days_left",
        ]
        read_only_fields = [
            "id", "license_key", "created_at", "updated_at",
            "status", "days_left",
        ]

    def get_status(self, lic: License) -> str:
        from datetime import timedelta

        from django.utils import timezone
        now = timezone.now()
        grace_end = lic.expires_at + timedelta(days=License.GRACE_DAYS)
        if lic.is_blocked:
            return "blocked"
        if now > grace_end:
            return "expired"
        if now > lic.expires_at:
            return "grace"
        return "active"

    def get_days_left(self, lic: License) -> int:
        from django.utils import timezone

        delta = lic.expires_at - timezone.now()
        return max(0, int(delta.total_seconds() // 86400))


class ExtendLicenseSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=3650)


class ChangePlanSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=LicensePlan.choices)


class BlockLicenseSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, max_length=255)
