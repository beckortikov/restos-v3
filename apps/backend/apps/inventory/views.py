"""HTTP API склада: CRUD ингредиентов + создание движений + история."""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.exceptions import BusinessError
from common.permissions import IsCashier, IsCashierOrWaiter

from .models import (
    Ingredient,
    IngredientStockMovement,
    SemiFinishedStockMovement,
    SemiFinishedType,
)
from .serializers import (
    IngredientSerializer,
    SemiFinishedTypeSerializer,
    SemiStockMovementSerializer,
    StockMovementCreateSerializer,
    StockMovementSerializer,
)
from .services import (
    produce_semi as produce_semi_service,
    record_movement,
    record_semi_movement,
)


from .views_8a import IngredientsImportMixin


class IngredientViewSet(
    IngredientsImportMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD ингредиентов.

    - Read: cashier + waiter (для отображения остатков на UI заказа)
    - Write: только cashier (управление складом — администрирование)
    """

    serializer_class = IngredientSerializer
    filterset_fields = ["is_active", "unit"]
    pagination_class = None

    def get_queryset(self):
        qs = Ingredient.objects.filter(restaurant=self.request.user.restaurant)
        # Phase 8A — фильтр по типу (продукты / хозтовары).
        kind = self.request.query_params.get("kind")
        if kind == "food":
            qs = qs.filter(is_food=True)
        elif kind in ("household", "supply", "non_food"):
            qs = qs.filter(is_food=False)
        return qs

    def get_permissions(self):
        if self.action in {
            "create", "update", "partial_update", "destroy",
            "purchase", "waste", "inventory_correct",
        }:
            return [IsCashier()]
        return [IsCashierOrWaiter()]

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """Phase 8D — KPI-агрегат для верхней панели «Склад → Продукты/Хозтовары».

        Query: ?kind=food|household  (default: food)
        Возвращает: { total, in_stock, low_stock, out_of_stock, inactive,
                      total_value (Decimal в TJS) }.
        total_value = Σ(current_qty × avg_cost_per_unit) только по активным.
        Использует annotate(Sum) — один запрос в БД, без N+1.
        """
        from decimal import Decimal

        from django.db.models import F, Sum

        qs = self.get_queryset()
        annotated = qs.annotate(qty=Sum("movements__qty_delta"))
        total = qs.count()
        in_stock = 0
        low = 0
        out = 0
        inactive = 0
        total_value = Decimal("0")
        for ing in annotated:
            if not ing.is_active:
                inactive += 1
                continue
            q = ing.qty or Decimal("0")
            if q <= 0:
                out += 1
            else:
                in_stock += 1
                thr = ing.low_stock_threshold
                if thr is not None and q <= Decimal(str(thr)):
                    low += 1
                total_value += Decimal(str(q)) * Decimal(str(ing.avg_cost_per_unit))
        return Response({
            "data": {
                "total": total,
                "in_stock": in_stock,
                "low_stock": low,
                "out_of_stock": out,
                "inactive": inactive,
                "total_value": str(total_value.quantize(Decimal("0.01"))),
            },
        })

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {"data": IngredientSerializer(qs, many=True).data,
             "meta": {"total": qs.count()}}
        )

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def destroy(self, request, *args, **kwargs):
        """Phase 8E — двухшаговое удаление:
        1) Если is_active=True → soft-delete (is_active=False), история сохраняется.
        2) Если is_active=False → жёсткое удаление (физически + cascade history).
        Без движений → сразу жёсткое.
        """
        ing = self.get_object()
        if ing.is_active and ing.movements.exists():
            ing.is_active = False
            ing.save(update_fields=["is_active", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        # is_active=False ИЛИ нет движений → физически удалить.
        # Cascade: IngredientStockMovement.ingredient on_delete=CASCADE — история тоже уйдёт.
        # MenuItemTechCardLine.ingredient on_delete=PROTECT — если кто-то использует в техкарте,
        # вернётся 409, кассир увидит ошибку.
        from django.db.models import ProtectedError
        try:
            ing.delete()
        except ProtectedError as exc:
            from common.exceptions import BusinessError
            raise BusinessError(
                "PROTECTED",
                f"Нельзя удалить «{ing.name}» — используется в техкартах блюд. "
                "Сначала уберите из техкарт.",
                409,
            ) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="movements")
    def movements(self, request, pk=None):
        """История движений ингредиента."""
        ing = self.get_object()
        qs = ing.movements.all().select_related("user", "order").order_by("-created_at")
        # Простая пагинация
        limit = min(int(request.query_params.get("limit", 100)), 500)
        qs = qs[:limit]
        return Response({
            "data": StockMovementSerializer(qs, many=True).data,
            "meta": {"count": len(qs), "limit": limit},
        })

    @action(detail=True, methods=["post"], url_path="purchase")
    def purchase(self, request, pk=None):
        """POST /inventory/ingredients/{id}/purchase/ {qty, unit_cost, reason}
        — приёмка по накладной. Положительный qty_delta + обновление avg_cost.
        """
        ing = self.get_object()
        from decimal import Decimal as _D

        try:
            qty = _D(str(request.data.get("qty") or "0"))
        except Exception as exc:
            raise BusinessError("INVALID_VALUE", "qty должен быть число", 400) from exc
        if qty <= 0:
            raise BusinessError("INVALID_VALUE", "qty должен быть > 0", 400)
        unit_cost = request.data.get("unit_cost")
        if unit_cost is not None:
            try:
                unit_cost = _D(str(unit_cost))
            except Exception:
                raise BusinessError("INVALID_VALUE", "unit_cost — не число", 400)
        mv = record_movement(
            ingredient=ing, kind="purchase",
            qty_delta=qty, unit_cost=unit_cost,
            reason=(request.data.get("reason") or "")[:255],
            user=request.user,
        )
        return Response(
            {"data": StockMovementSerializer(mv).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="waste")
    def waste(self, request, pk=None):
        """POST /inventory/ingredients/{id}/waste/ {qty, reason} — списание."""
        ing = self.get_object()
        from decimal import Decimal as _D

        try:
            qty = _D(str(request.data.get("qty") or "0"))
        except Exception as exc:
            raise BusinessError("INVALID_VALUE", "qty должен быть число", 400) from exc
        if qty <= 0:
            raise BusinessError(
                "INVALID_VALUE", "qty (списать) должен быть > 0", 400,
            )
        mv = record_movement(
            ingredient=ing, kind="waste",
            qty_delta=-qty,
            reason=(request.data.get("reason") or "")[:255],
            user=request.user,
        )
        return Response(
            {"data": StockMovementSerializer(mv).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="inventory_correct")
    def inventory_correct(self, request, pk=None):
        """POST /inventory/ingredients/{id}/inventory_correct/
        {actual_qty, reason} — выравнивание под фактический подсчёт.
        Создаёт ±delta movement.
        """
        ing = self.get_object()
        from decimal import Decimal as _D

        try:
            actual = _D(str(request.data.get("actual_qty") or "0"))
        except Exception as exc:
            raise BusinessError("INVALID_VALUE", "actual_qty не число", 400) from exc
        if actual < 0:
            raise BusinessError("INVALID_VALUE", "actual_qty не может быть < 0", 400)
        delta = actual - ing.current_qty
        if delta == 0:
            return Response(
                {"data": {"message": "Остаток совпадает, корректировка не требуется"}},
            )
        mv = record_movement(
            ingredient=ing, kind="inventory_correct",
            qty_delta=delta,
            reason=(request.data.get("reason") or "Инвентаризация")[:255],
            user=request.user,
        )
        return Response(
            {"data": StockMovementSerializer(mv).data},
            status=status.HTTP_201_CREATED,
        )


class StockMovementViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only список всех движений (для аудита/отчётов)."""

    serializer_class = StockMovementSerializer
    filterset_fields = ["ingredient", "kind", "order"]

    def get_queryset(self):
        return IngredientStockMovement.objects.filter(
            ingredient__restaurant=self.request.user.restaurant
        ).select_related("ingredient", "user", "order")

    def get_permissions(self):
        return [IsCashier()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        limit = min(int(request.query_params.get("limit", 100)), 500)
        rows = list(qs[:limit])
        return Response({
            "data": StockMovementSerializer(rows, many=True).data,
            "meta": {"count": len(rows), "limit": limit},
        })


class SemiFinishedTypeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD полуфабрикатов + операции производства/расхода.

    Read — cashier/waiter, write — только cashier.
    """

    serializer_class = SemiFinishedTypeSerializer
    filterset_fields = ["is_active", "output_unit"]
    pagination_class = None

    def get_queryset(self):
        return SemiFinishedType.objects.filter(
            restaurant=self.request.user.restaurant,
        ).prefetch_related("recipe_lines__ingredient", "recipe_lines__nested_semi")

    def get_permissions(self):
        if self.action in {
            "create", "update", "partial_update", "destroy",
            "produce", "waste", "inventory_correct",
        }:
            return [IsCashier()]
        return [IsCashierOrWaiter()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response({
            "data": SemiFinishedTypeSerializer(qs, many=True).data,
            "meta": {"total": qs.count()},
        })

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def destroy(self, request, *args, **kwargs):
        """Phase 8E — двухшаговое удаление: первый раз → soft, второй → hard."""
        semi = self.get_object()
        if semi.is_active and semi.movements.exists():
            semi.is_active = False
            semi.save(update_fields=["is_active", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        from django.db.models import ProtectedError
        try:
            semi.delete()
        except ProtectedError as exc:
            from common.exceptions import BusinessError
            raise BusinessError(
                "PROTECTED",
                f"Нельзя удалить «{semi.name}» — используется в техкартах или рецептах. "
                "Сначала уберите из техкарт.",
                409,
            ) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="movements")
    def movements(self, request, pk=None):
        semi = self.get_object()
        qs = semi.movements.all().select_related("user", "order").order_by("-created_at")
        limit = min(int(request.query_params.get("limit", 100)), 500)
        qs = qs[:limit]
        return Response({
            "data": SemiStockMovementSerializer(qs, many=True).data,
            "meta": {"count": len(qs), "limit": limit},
        })

    @action(detail=True, methods=["post"], url_path="produce")
    def produce(self, request, pk=None):
        """POST /inventory/semi/{id}/produce/ {qty, reason} — варка партии.

        Списывает ингредиенты по рецепту с учётом yield_percent, добавляет
        qty к остатку п/ф, обновляет weighted avg_cost.
        """
        semi = self.get_object()
        mv = produce_semi_service(
            semi_type=semi,
            qty=request.data.get("qty"),
            reason=(request.data.get("reason") or "")[:255],
            user=request.user,
        )
        return Response(
            {"data": SemiStockMovementSerializer(mv).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="waste")
    def waste(self, request, pk=None):
        """Списание готового п/ф (порча, бой)."""
        semi = self.get_object()
        from decimal import Decimal as _D

        try:
            qty = _D(str(request.data.get("qty") or "0"))
        except Exception as exc:
            raise BusinessError("INVALID_VALUE", "qty не число", 400) from exc
        if qty <= 0:
            raise BusinessError("INVALID_VALUE", "qty должен быть > 0", 400)
        mv = record_semi_movement(
            semi_type=semi, kind="waste", qty_delta=-qty,
            reason=(request.data.get("reason") or "")[:255],
            user=request.user,
        )
        return Response(
            {"data": SemiStockMovementSerializer(mv).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="inventory_correct")
    def inventory_correct(self, request, pk=None):
        semi = self.get_object()
        from decimal import Decimal as _D

        try:
            actual = _D(str(request.data.get("actual_qty") or "0"))
        except Exception as exc:
            raise BusinessError("INVALID_VALUE", "actual_qty не число", 400) from exc
        if actual < 0:
            raise BusinessError("INVALID_VALUE", "actual_qty не может быть < 0", 400)
        delta = actual - semi.current_qty
        if delta == 0:
            return Response(
                {"data": {"message": "Остаток совпадает"}},
            )
        mv = record_semi_movement(
            semi_type=semi, kind="inventory_correct", qty_delta=delta,
            reason=(request.data.get("reason") or "Инвентаризация")[:255],
            user=request.user,
        )
        return Response(
            {"data": SemiStockMovementSerializer(mv).data},
            status=status.HTTP_201_CREATED,
        )
