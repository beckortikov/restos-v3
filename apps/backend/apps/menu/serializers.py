from rest_framework import serializers

from .models import (
    BatchCookingLog,
    Category,
    MenuItem,
    MenuItemNote,
    MenuItemTechCardLine,
    Modifier,
    ModifierGroup,
)


class MenuItemNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItemNote
        fields = ["id", "label", "sort_order", "is_active"]


class CategorySerializer(serializers.ModelSerializer):
    print_station_name = serializers.CharField(
        source="print_station.name", read_only=True, default=None
    )

    class Meta:
        model = Category
        fields = ["id", "name", "sort_order", "print_station", "print_station_name"]


class ModifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Modifier
        fields = ["id", "name", "price_delta", "sort_order", "is_active"]


class ModifierGroupSerializer(serializers.ModelSerializer):
    """Группа модификаторов вместе с вложенным списком модификаторов.

    Чтение: возвращает только `is_active=True` модификаторы.
    Запись: список вложенных опций — full upsert (то, что не в списке —
    удаляется, то что новое — создаётся, существующее по id — обновляется).
    """

    modifiers = ModifierSerializer(many=True, required=False)

    class Meta:
        model = ModifierGroup
        fields = [
            "id", "name",
            "min_select", "max_select", "is_required",
            "sort_order", "is_active", "modifiers",
        ]

    def validate(self, attrs: dict) -> dict:
        min_s = attrs.get("min_select", getattr(self.instance, "min_select", 0))
        max_s = attrs.get("max_select", getattr(self.instance, "max_select", 1))
        if min_s > max_s:
            raise serializers.ValidationError(
                "min_select не может быть больше max_select"
            )
        return attrs

    def create(self, validated_data: dict):
        mods_data = validated_data.pop("modifiers", [])
        group = ModifierGroup.objects.create(**validated_data)
        for m in mods_data:
            Modifier.objects.create(group=group, **m)
        return group

    def update(self, instance, validated_data: dict):
        mods_data = validated_data.pop("modifiers", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if mods_data is not None:
            existing = {m.id: m for m in instance.modifiers.all()}
            seen: set[int] = set()
            for m in mods_data:
                mid = m.get("id")
                if mid and mid in existing:
                    obj = existing[mid]
                    for k, v in m.items():
                        if k != "id":
                            setattr(obj, k, v)
                    obj.save()
                    seen.add(mid)
                else:
                    payload = {k: v for k, v in m.items() if k != "id"}
                    Modifier.objects.create(group=instance, **payload)
            for mid, obj in existing.items():
                if mid not in seen:
                    obj.delete()
        return instance


class MenuItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    modifier_group_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=ModifierGroup.objects.all(), required=False,
        source="modifier_groups", write_only=True,
    )
    modifier_groups = ModifierGroupSerializer(many=True, read_only=True)

    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            "id",
            "category",
            "name",
            "price",
            "emoji",
            "image_url",
            "sort_order",
            "is_available",
            "stop_reason",
            "stop_until",
            "auto_stopped",
            "allow_oversell",
            "modifier_groups",
            "modifier_group_ids",
            # Расширенные поля v3
            "kind",
            "cogs",
            "cook_time_min",
            "is_purchased",
            "auto_consume",
            "is_batch_cooking",
            "prepared_qty",
            "low_stock_threshold",
            "is_low_stock",
            "unit",
            "unit_size",
            "sale_step",
        ]

    def validate(self, attrs: dict) -> dict:
        is_purch = attrs.get(
            "is_purchased", getattr(self.instance, "is_purchased", False)
        )
        is_batch = attrs.get(
            "is_batch_cooking",
            getattr(self.instance, "is_batch_cooking", False),
        )
        if is_purch and is_batch:
            raise serializers.ValidationError(
                "Блюдо не может быть одновременно покупным и заготовочным"
            )
        unit_size = attrs.get(
            "unit_size", getattr(self.instance, "unit_size", 1)
        )
        if unit_size < 1:
            raise serializers.ValidationError("unit_size должен быть ≥ 1")
        return attrs

    def validate_modifier_group_ids(self, groups):
        """Проверяем cross-restaurant изоляцию: ID групп должны принадлежать
        ресторану текущего пользователя."""
        request = self.context.get("request")
        if request is None or not getattr(request.user, "restaurant_id", None):
            return groups
        bad = [g for g in groups if g.restaurant_id != request.user.restaurant_id]
        if bad:
            raise serializers.ValidationError(
                "modifier_group_ids содержат группы из другого ресторана"
            )
        return groups

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url


class MenuItemTechCardLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True, default=None,
    )
    nested_semi_name = serializers.CharField(
        source="nested_semi.name", read_only=True, default=None,
    )
    component_unit = serializers.SerializerMethodField()

    class Meta:
        model = MenuItemTechCardLine
        fields = [
            "id", "ingredient", "ingredient_name",
            "nested_semi", "nested_semi_name",
            "qty_per_unit", "component_unit", "sort_order",
        ]

    def get_component_unit(self, obj) -> str:
        c = obj.ingredient or obj.nested_semi
        if c is None:
            return ""
        return getattr(c, "unit", None) or getattr(c, "output_unit", "")


class BatchCookingLogSerializer(serializers.ModelSerializer):
    """История заготовок (Phase 7E)."""

    user_name = serializers.SerializerMethodField()
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = BatchCookingLog
        fields = [
            "id", "menu_item", "qty_delta", "new_total",
            "kind", "kind_display", "user", "user_name", "note", "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_user_name(self, obj) -> str:
        if obj.user is None:
            return ""
        return getattr(obj.user, "full_name", None) or obj.user.username
