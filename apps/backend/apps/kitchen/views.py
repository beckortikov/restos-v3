from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.orders.models import KitchenStatus, OrderItem

from .serializers import KitchenItemSerializer
from .services import (
    list_kitchen_items,
    mark_ready,
    mark_served,
    start_cooking,
    unmark_served,
)


class IsCookOrCashier(permissions.BasePermission):
    """KDS доступен повару (основная роль) и кассиру (для контроля выдачи)."""

    def has_permission(self, request, view) -> bool:
        u = request.user
        return bool(
            u and u.is_authenticated
            and getattr(u, "role", None) in {"cook", "cashier"}
        )


class IsCookOrCashierOrWaiter(permissions.BasePermission):
    """Mark/unmark served — waiter тоже может (отмечает выдачу на свои столы).
    Прочие KDS-операции (start_cooking, mark_ready) — только cook/cashier."""

    def has_permission(self, request, view) -> bool:
        u = request.user
        return bool(
            u and u.is_authenticated
            and getattr(u, "role", None) in {"cook", "cashier", "waiter"}
        )


class KitchenItemViewSet(viewsets.GenericViewSet):
    """KDS endpoints:

    - GET  /kitchen/items/?status=new,cooking,ready  — список для канбана
    - POST /kitchen/items/{id}/start_cooking/        — взял в работу
    - POST /kitchen/items/{id}/mark_ready/           — готово
    - POST /kitchen/items/{id}/mark_served/          — выдано
    """

    serializer_class = KitchenItemSerializer
    permission_classes = [IsCookOrCashier]

    def get_queryset(self):
        return OrderItem.objects.filter(
            order__restaurant=self.request.user.restaurant,
        )

    def list(self, request):
        statuses_raw = request.query_params.get("status")
        if statuses_raw:
            statuses = [
                s.strip() for s in statuses_raw.split(",")
                if s.strip() in KitchenStatus.values
            ]
        else:
            statuses = None
        # Фильтр по станции:
        # - Повар с привязанной kitchen_station видит только свою станцию.
        # - Кассир видит всё (отслеживает выдачу всех цехов).
        # - Можно явно переопределить через ?station=ID или ?station=all.
        station = None
        station_param = request.query_params.get("station")
        if station_param == "all":
            station = None
        elif station_param:
            from apps.printing.models import PrintStation

            try:
                station = PrintStation.objects.get(
                    id=int(station_param),
                    restaurant=request.user.restaurant,
                )
            except (PrintStation.DoesNotExist, ValueError, TypeError):
                station = None
        elif (
            getattr(request.user, "role", None) == "cook"
            and request.user.kitchen_station_id is not None
        ):
            station = request.user.kitchen_station
        qs = list_kitchen_items(
            request.user.restaurant, statuses=statuses, station=station,
        )
        return Response(
            {"data": KitchenItemSerializer(qs, many=True).data,
             "meta": {"total": qs.count()}}
        )

    @action(detail=True, methods=["post"], url_path="start_cooking")
    def start_cooking(self, request, pk=None):
        item = start_cooking(
            item_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": KitchenItemSerializer(item).data})

    @action(detail=True, methods=["post"], url_path="mark_ready")
    def mark_ready(self, request, pk=None):
        item = mark_ready(
            item_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": KitchenItemSerializer(item).data})

    @action(
        detail=True, methods=["post"], url_path="mark_served",
        permission_classes=[IsCookOrCashierOrWaiter],
    )
    def mark_served(self, request, pk=None):
        item = mark_served(
            item_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": KitchenItemSerializer(item).data})

    @action(
        detail=True, methods=["post"], url_path="unmark_served",
        permission_classes=[IsCookOrCashierOrWaiter],
    )
    def unmark_served(self, request, pk=None):
        item = unmark_served(
            item_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": KitchenItemSerializer(item).data})
