from rest_framework import serializers

from .models import Restaurant, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "full_name", "role"]


class UserAdminSerializer(serializers.ModelSerializer):
    """Расширенный сериализатор для frame 20 «Настройки / Пользователи».

    PIN никогда не сериализуется (write_only), хранится в pin_hash."""

    pin = serializers.CharField(
        write_only=True, required=False, allow_blank=True,
        min_length=4, max_length=6,
    )
    has_pin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "role",
            "is_active",
            "has_pin",
            "pin",
            "kitchen_station",
            "permissions",
            "created_at",
        ]
        read_only_fields = ["id", "has_pin", "created_at"]

    def get_has_pin(self, obj) -> bool:
        return bool(obj.pin_hash)

    def validate_pin(self, value: str) -> str:
        v = (value or "").strip()
        if v and not v.isdigit():
            raise serializers.ValidationError("PIN должен состоять из цифр")
        return v

    def validate_role(self, value: str) -> str:
        if value not in {"cashier", "waiter", "cook", "manager"}:
            raise serializers.ValidationError(
                "Роль должна быть cashier / waiter / cook / manager"
            )
        return value

    def validate_permissions(self, value):
        from .models import ALL_PERMISSIONS

        if not value:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("permissions должен быть списком")
        bad = [p for p in value if p not in ALL_PERMISSIONS]
        if bad:
            raise serializers.ValidationError(
                f"Неизвестные permission-keys: {bad}"
            )
        return value

    def validate(self, attrs: dict) -> dict:
        # kitchen_station допустима только для роли cook; для прочих — всегда
        # null. При смене роли с cook на cashier/waiter — очищаем явно
        # (даже если поле не пришло в PATCH).
        role = attrs.get("role") or (self.instance.role if self.instance else None)
        if role != "cook":
            attrs["kitchen_station"] = None
        return attrs

    def create(self, validated_data: dict):
        pin = validated_data.pop("pin", "")
        user = User(**validated_data)
        if pin:
            user.set_pin(pin)
        user.save()
        return user

    def update(self, instance, validated_data: dict):
        pin = validated_data.pop("pin", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if pin:
            instance.set_pin(pin)
        instance.save()
        return instance


class RestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        fields = [
            "id",
            "name",
            "address",
            "phone",
            "currency",
            "timezone",
            "pin_lock_timeout_min",
            "receipt_copies",
            "kitchen_enabled",
            "manager_override_threshold_tjs",
            "receipt_header_extra",
            "receipt_footer",
            "auto_open_cash_drawer",
            "tech_cards_enabled",
            "supply_allow_negative",
            "printer_virtual_mode",
        ]
