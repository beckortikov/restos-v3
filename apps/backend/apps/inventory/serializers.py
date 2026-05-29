from decimal import Decimal

from rest_framework import serializers

from .models import (
    Ingredient,
    IngredientStockMovement,
    SemiFinishedRecipeLine,
    SemiFinishedStockMovement,
    SemiFinishedType,
    StockMovementKind,
)


class IngredientSerializer(serializers.ModelSerializer):
    current_qty = serializers.DecimalField(
        max_digits=14, decimal_places=3, read_only=True,
    )
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ingredient
        fields = [
            "id", "name", "unit",
            "avg_cost_per_unit",
            "low_stock_threshold", "is_active", "is_food", "sort_order",
            "current_qty", "is_low_stock",
            "created_at", "updated_at",
        ]
        read_only_fields = ["avg_cost_per_unit", "created_at", "updated_at"]

    def validate_name(self, value: str) -> str:
        v = (value or "").strip()
        if not v:
            raise serializers.ValidationError("Название обязательно")
        return v


class StockMovementSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True,
    )

    class Meta:
        model = IngredientStockMovement
        fields = [
            "id", "ingredient", "ingredient_name",
            "kind", "qty_delta", "unit_cost",
            "reason", "user", "order", "created_at",
        ]
        read_only_fields = ["created_at"]


class StockMovementCreateSerializer(serializers.Serializer):
    """Для POST /inventory/stock-movements/ — упрощённый.

    Используется через сервис record_movement, который добавит проверки знаков
    и пересчёт avg_cost.
    """
    ingredient_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=StockMovementKind.choices)
    qty_delta = serializers.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=4, required=False, allow_null=True,
    )
    reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255,
    )


class SemiRecipeLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True, default=None,
    )
    nested_semi_name = serializers.CharField(
        source="nested_semi.name", read_only=True, default=None,
    )

    class Meta:
        model = SemiFinishedRecipeLine
        fields = [
            "id", "ingredient", "ingredient_name",
            "nested_semi", "nested_semi_name",
            "qty_per_output", "sort_order",
        ]


class SemiFinishedTypeSerializer(serializers.ModelSerializer):
    """Сериализатор п/ф с вложенным рецептом (upsert при write)."""

    current_qty = serializers.DecimalField(
        max_digits=14, decimal_places=3, read_only=True,
    )
    is_low_stock = serializers.BooleanField(read_only=True)
    recipe_lines = SemiRecipeLineSerializer(many=True, required=False)

    class Meta:
        model = SemiFinishedType
        fields = [
            "id", "name", "output_unit", "yield_percent",
            "avg_cost_per_unit",
            "low_stock_threshold", "is_active", "sort_order",
            "current_qty", "is_low_stock",
            "recipe_lines",
            "created_at", "updated_at",
        ]
        read_only_fields = ["avg_cost_per_unit", "created_at", "updated_at"]

    def validate_name(self, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise serializers.ValidationError("Название обязательно")
        return v

    def _validate_recipe(self, recipe_data: list, restaurant_id: int) -> None:
        for line in recipe_data:
            ing = line.get("ingredient")
            sem = line.get("nested_semi")
            if (ing is None) == (sem is None):
                raise serializers.ValidationError({
                    "recipe_lines": "Ровно один: ingredient ИЛИ nested_semi",
                })
            if ing and ing.restaurant_id != restaurant_id:
                raise serializers.ValidationError({
                    "recipe_lines": f"Ингредиент «{ing.name}» из другого ресторана",
                })
            if sem and sem.restaurant_id != restaurant_id:
                raise serializers.ValidationError({
                    "recipe_lines": f"П/ф «{sem.name}» из другого ресторана",
                })
            qpo = line.get("qty_per_output")
            if qpo is None or qpo <= 0:
                raise serializers.ValidationError({
                    "recipe_lines": "qty_per_output должен быть > 0",
                })

    def create(self, validated_data: dict):
        recipe_data = validated_data.pop("recipe_lines", [])
        restaurant_id = validated_data["restaurant"].id
        self._validate_recipe(recipe_data, restaurant_id)
        instance = SemiFinishedType.objects.create(**validated_data)
        for line in recipe_data:
            SemiFinishedRecipeLine.objects.create(semi_type=instance, **line)
        return instance

    def update(self, instance, validated_data: dict):
        recipe_data = validated_data.pop("recipe_lines", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if recipe_data is not None:
            self._validate_recipe(recipe_data, instance.restaurant_id)
            # Full upsert: удаляем старые и пересоздаём (рецепт — атомарный объект)
            instance.recipe_lines.all().delete()
            for line in recipe_data:
                SemiFinishedRecipeLine.objects.create(semi_type=instance, **line)
        return instance


class SemiStockMovementSerializer(serializers.ModelSerializer):
    semi_name = serializers.CharField(
        source="semi_type.name", read_only=True,
    )

    class Meta:
        model = SemiFinishedStockMovement
        fields = [
            "id", "semi_type", "semi_name",
            "kind", "qty_delta", "unit_cost",
            "reason", "user", "order", "created_at",
        ]
        read_only_fields = ["created_at"]


# ─── Phase 8A serializers ─────────────────────────────────────────────────


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        from .models import Supplier
        model = Supplier
        fields = [
            "id", "name", "phone", "contact_person",
            "note", "is_active", "sort_order", "created_at",
        ]
        read_only_fields = ["created_at"]


class StockReceiptLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True,
    )
    ingredient_unit = serializers.CharField(
        source="ingredient.unit", read_only=True,
    )

    class Meta:
        from .models import StockReceiptLine
        model = StockReceiptLine
        fields = [
            "id", "ingredient", "ingredient_name", "ingredient_unit",
            "qty", "unit_cost", "total",
        ]
        # total — computed на бэке (qty × unit_cost), клиент не присылает.
        read_only_fields = ["total"]


class StockReceiptSerializer(serializers.ModelSerializer):
    lines = StockReceiptLineSerializer(many=True, required=False)
    supplier_name = serializers.CharField(
        source="supplier.name", read_only=True, default=None,
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    class Meta:
        from .models import StockReceipt
        model = StockReceipt
        fields = [
            "id", "supplier", "supplier_name",
            "receipt_date", "number", "total_amount",
            "status", "status_display", "note",
            "lines", "applied_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "applied_at", "total_amount", "created_at", "updated_at",
        ]

    def create(self, validated_data):
        from django.db import transaction
        from decimal import Decimal as _D

        from .models import StockReceipt, StockReceiptLine

        lines_data = validated_data.pop("lines", [])
        with transaction.atomic():
            receipt = StockReceipt.objects.create(**validated_data)
            total = _D("0.00")
            for ln in lines_data:
                line_total = _D(str(ln.get("qty"))) * _D(str(ln.get("unit_cost")))
                StockReceiptLine.objects.create(
                    receipt=receipt,
                    ingredient=ln["ingredient"],
                    qty=ln["qty"],
                    unit_cost=ln["unit_cost"],
                    total=line_total.quantize(_D("0.01")),
                )
                total += line_total
            receipt.total_amount = total.quantize(_D("0.01"))
            receipt.save(update_fields=["total_amount"])
        return receipt

    def update(self, instance, validated_data):
        from django.db import transaction
        from decimal import Decimal as _D

        from .models import StockReceiptLine
        from common.exceptions import BusinessError

        if instance.status != "draft":
            raise BusinessError(
                "INVALID_STATE", "Проведённую накладную править нельзя", 400,
            )
        lines_data = validated_data.pop("lines", None)
        with transaction.atomic():
            for k, v in validated_data.items():
                setattr(instance, k, v)
            if lines_data is not None:
                instance.lines.all().delete()
                total = _D("0.00")
                for ln in lines_data:
                    line_total = _D(str(ln["qty"])) * _D(str(ln["unit_cost"]))
                    StockReceiptLine.objects.create(
                        receipt=instance,
                        ingredient=ln["ingredient"],
                        qty=ln["qty"],
                        unit_cost=ln["unit_cost"],
                        total=line_total.quantize(_D("0.01")),
                    )
                    total += line_total
                instance.total_amount = total.quantize(_D("0.01"))
            instance.save()
        return instance


class StockWriteoffLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True,
    )
    ingredient_unit = serializers.CharField(
        source="ingredient.unit", read_only=True,
    )

    class Meta:
        from .models import StockWriteoffLine
        model = StockWriteoffLine
        fields = ["id", "ingredient", "ingredient_name", "ingredient_unit", "qty"]


class StockWriteoffSerializer(serializers.ModelSerializer):
    lines = StockWriteoffLineSerializer(many=True, required=False)
    reason_display = serializers.CharField(
        source="get_reason_display", read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    class Meta:
        from .models import StockWriteoff
        model = StockWriteoff
        fields = [
            "id", "writeoff_date", "reason", "reason_display",
            "status", "status_display", "note",
            "lines", "applied_at", "created_at", "updated_at",
        ]
        read_only_fields = ["status", "applied_at", "created_at", "updated_at"]

    def create(self, validated_data):
        from django.db import transaction

        from .models import StockWriteoff, StockWriteoffLine

        lines_data = validated_data.pop("lines", [])
        with transaction.atomic():
            wo = StockWriteoff.objects.create(**validated_data)
            for ln in lines_data:
                StockWriteoffLine.objects.create(
                    writeoff=wo,
                    ingredient=ln["ingredient"],
                    qty=ln["qty"],
                )
        return wo

    def update(self, instance, validated_data):
        from django.db import transaction

        from .models import StockWriteoffLine
        from common.exceptions import BusinessError

        if instance.status != "draft":
            raise BusinessError(
                "INVALID_STATE", "Проведённое списание править нельзя", 400,
            )
        lines_data = validated_data.pop("lines", None)
        with transaction.atomic():
            for k, v in validated_data.items():
                setattr(instance, k, v)
            if lines_data is not None:
                instance.lines.all().delete()
                for ln in lines_data:
                    StockWriteoffLine.objects.create(
                        writeoff=instance,
                        ingredient=ln["ingredient"],
                        qty=ln["qty"],
                    )
            instance.save()
        return instance


class SupplyExpenseSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True,
    )
    reason_display = serializers.CharField(
        source="get_reason_display", read_only=True,
    )

    class Meta:
        from .models import SupplyExpense
        model = SupplyExpense
        fields = [
            "id", "ingredient", "ingredient_name",
            "qty", "reason", "reason_display",
            "note", "user", "created_at",
        ]
        read_only_fields = ["user", "created_at"]


class InventoryCheckLineSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(
        source="ingredient.name", read_only=True,
    )
    ingredient_unit = serializers.CharField(
        source="ingredient.unit", read_only=True,
    )
    diff = serializers.DecimalField(
        max_digits=14, decimal_places=3, read_only=True,
    )

    class Meta:
        from .models import InventoryCheckLine
        model = InventoryCheckLine
        fields = [
            "id", "ingredient", "ingredient_name", "ingredient_unit",
            "expected_qty", "actual_qty", "diff",
        ]


class InventoryCheckSerializer(serializers.ModelSerializer):
    lines = InventoryCheckLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True,
    )

    class Meta:
        from .models import InventoryCheck
        model = InventoryCheck
        fields = [
            "id", "check_date", "is_food",
            "status", "status_display", "note",
            "lines", "applied_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "applied_at", "created_at", "updated_at",
        ]
