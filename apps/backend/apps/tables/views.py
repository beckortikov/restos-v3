from rest_framework import mixins, status as drf_status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.exceptions import BusinessError
from common.permissions import IsCashier, IsCashierOrWaiter

from .models import Table, TableGroup, TableStatus, Zone
from .serializers import (
    MergeTablesSerializer,
    TableGroupSerializer,
    TableSerializer,
    ZoneSerializer,
)
from .services import force_free_table, merge_tables, open_table, unmerge_table_group


class ZoneViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD зон зала. Read — кассир/официант, Write — только IsCashier."""

    serializer_class = ZoneSerializer
    pagination_class = None

    def get_queryset(self):
        # Архивированные зоны скрыты из UI (карта зала / waiter PWA), но
        # доступны через FK напрямую — Order/Table сохраняют резолв
        # `zone.name` для исторических отчётов.
        return Zone.objects.filter(
            restaurant=self.request.user.restaurant,
            is_archived=False,
        )

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsCashier()]
        return [IsCashierOrWaiter()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response({"data": ZoneSerializer(qs, many=True).data, "meta": {"total": qs.count()}})

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def destroy(self, request, *args, **kwargs):
        """Удаление зоны.

        Активные (не архивированные) столы → 422 ZONE_NOT_EMPTY.
        Только архивированные столы (или ничего) → если зона имеет
        исторические FK-привязки (через архивированные столы / заказы) →
        soft-archive (is_archived=True). Если зона совсем пустая физически —
        hard-delete.
        """
        from django.db.models import ProtectedError
        from django.utils import timezone
        from rest_framework.response import Response
        from rest_framework import status as http_status

        zone = self.get_object()
        # Проверяем только НЕ-архивированные столы — архивированные не мешают.
        if zone.tables.filter(is_archived=False).exists():
            raise BusinessError(
                "ZONE_NOT_EMPTY",
                "Зона содержит столы. Удалите или перенесите столы перед удалением зоны.",
                422,
            )
        # Если есть архивированные столы — soft-archive зоны (FK PROTECT не даст delete).
        if zone.tables.filter(is_archived=True).exists():
            zone.is_archived = True
            zone.archived_at = timezone.now()
            zone.save(update_fields=["is_archived", "archived_at"])
            return Response(status=http_status.HTTP_204_NO_CONTENT)
        # Иначе — пробуем hard-delete; если внезапно нарвёмся на PROTECT,
        # falls back на soft-archive.
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            zone.is_archived = True
            zone.archived_at = timezone.now()
            zone.save(update_fields=["is_archived", "archived_at"])
            return Response(status=http_status.HTTP_204_NO_CONTENT)


class TableViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TableSerializer
    filterset_fields = ["zone", "status"]
    pagination_class = None

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsCashier()]
        return [IsCashierOrWaiter()]

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def destroy(self, request, *args, **kwargs):
        """Удаление стола.

        Невозможно если стол занят / висит активный заказ / в группе.
        Если есть исторические заказы (status=done/cancelled) — делаем
        soft-archive (is_archived=True): стол пропадёт из карты зала,
        но в OrderHistory/отчётах останется видимым через snapshot
        OrderSerializer.table_zone_name / table_name.
        Если истории нет — физическое удаление.
        """
        from django.utils import timezone
        from rest_framework.response import Response
        from rest_framework import status as http_status

        table = self.get_object()
        if table.status in (
            TableStatus.OCCUPIED, TableStatus.BILL_REQUESTED, TableStatus.MERGED
        ):
            raise BusinessError(
                "TABLE_BUSY",
                "Нельзя удалить занятый/объединённый стол. Сначала закройте заказ.",
                422,
            )
        if table.current_order_id is not None:
            raise BusinessError(
                "TABLE_BUSY",
                "На столе висит активный заказ — удаление невозможно.",
                422,
            )
        if table.orders.exists():
            # Soft-archive — сохраняет FK для истории.
            table.is_archived = True
            table.archived_at = timezone.now()
            table.save(update_fields=["is_archived", "archived_at"])
            return Response(status=http_status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        # Архивированные столы скрыты от UI (карта зала, waiter PWA), но
        # видны в исторических endpoint'ах через FK напрямую (Order.table).
        qs = (
            Table.objects.filter(
                restaurant=self.request.user.restaurant,
                is_archived=False,
            )
            .select_related("zone", "waiter", "group")
            .order_by("zone__sort_order", "number")
        )
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        # Phase: фильтр «Мои» столы для waiter PWA.
        # Стол считается «моим», если у меня есть активный заказ на нём
        # (current_order.waiter == request.user или один из active_orders).
        mine_param = request.query_params.get("mine", "").lower()
        if mine_param in ("true", "1", "yes"):
            from apps.orders.models import Order, OrderStatus

            mine_table_ids = set(
                Order.objects.filter(
                    restaurant=request.user.restaurant,
                    waiter=request.user,
                    status__in=(OrderStatus.NEW, OrderStatus.BILL_REQUESTED),
                    table__isnull=False,
                ).values_list("table_id", flat=True)
            )
            qs = qs.filter(id__in=mine_table_ids)
        return Response(
            {"data": TableSerializer(qs, many=True).data, "meta": {"total": qs.count()}}
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": TableSerializer(self.get_object()).data})

    @action(
        detail=False, methods=["get"], url_path="next_number",
        permission_classes=[IsCashierOrWaiter],
    )
    def next_number(self, request):
        """GET /tables/next_number/?zone=<id> → {next: N, taken: [1,2,5,...]}.

        Подсказка для UI: следующий свободный номер в зоне + список занятых.
        Используется в table_edit_dialog для auto-fill и валидации ввода.
        """
        try:
            zone_id = int(request.query_params.get("zone") or 0)
        except (TypeError, ValueError):
            raise BusinessError("INVALID_VALUE", "zone обязателен", 400)
        if not zone_id:
            raise BusinessError("INVALID_VALUE", "zone обязателен", 400)
        from .models import Zone
        try:
            zone = Zone.objects.get(
                id=zone_id, restaurant=request.user.restaurant,
            )
        except Zone.DoesNotExist:
            raise BusinessError("NOT_FOUND", "Зона не найдена", 404)
        taken = sorted(
            Table.objects.filter(zone=zone).values_list("number", flat=True)
        )
        # Next free: первая «дырка» в последовательности 1..max+1.
        next_num = 1
        for n in taken:
            if n == next_num:
                next_num += 1
            else:
                break
        return Response({"data": {"next": next_num, "taken": taken, "zone": zone_id}})

    @action(detail=True, methods=["post"], permission_classes=[IsCashierOrWaiter])
    def open(self, request, pk=None):
        table = open_table(
            table_id=pk,
            waiter=request.user,
            guests_count=int(request.data.get("guests_count", 1)),
        )
        return Response({"data": TableSerializer(table).data})

    @action(
        detail=True, methods=["post"], url_path="force_free",
        permission_classes=[IsCashierOrWaiter],
    )
    def force_free(self, request, pk=None):
        """POST /tables/{id}/force_free/ — освободить стол с рассинхроном.

        Запрещено если есть активный заказ (NEW / BILL_REQUESTED).
        """
        table = force_free_table(
            table_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": TableSerializer(table).data})

    @action(
        detail=False, methods=["post"], url_path="merge",
        permission_classes=[IsCashierOrWaiter],
    )
    def merge(self, request):
        """POST /tables/merge/  body={table_ids: [1, 2, 3], name?: ""}.

        Создаёт TableGroup, остальные столы получают status=MERGED.
        Primary — стол с наименьшим id. На primary потом открывается заказ.
        """
        ser = MergeTablesSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        group = merge_tables(
            restaurant=request.user.restaurant,
            table_ids=ser.validated_data["table_ids"],
            user=request.user,
            name=ser.validated_data.get("name", ""),
        )
        return Response(
            {"data": TableGroupSerializer(group).data},
            status=drf_status.HTTP_201_CREATED,
        )


class TableGroupViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """CRUD групп столов. Создание — через TableViewSet.merge."""

    serializer_class = TableGroupSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            TableGroup.objects.filter(restaurant=self.request.user.restaurant)
            .prefetch_related("tables")
        )

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        # По умолчанию показываем только активные (не закрытые)
        only_active = request.query_params.get("active", "true").lower() in (
            "true", "1", "yes",
        )
        if only_active:
            qs = qs.filter(closed_at__isnull=True)
        return Response(
            {"data": TableGroupSerializer(qs, many=True).data,
             "meta": {"total": qs.count()}}
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": TableGroupSerializer(self.get_object()).data})

    @action(
        detail=True, methods=["post"], url_path="unmerge",
        permission_classes=[IsCashierOrWaiter],
    )
    def unmerge(self, request, pk=None):
        group = unmerge_table_group(
            restaurant=request.user.restaurant,
            group_id=int(pk),
            user=request.user,
        )
        return Response({"data": TableGroupSerializer(group).data})
