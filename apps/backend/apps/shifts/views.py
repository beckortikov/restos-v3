from rest_framework import mixins, status as drf_status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from common.permissions import IsCashier

from .models import CashShift
from .serializers import (
    CashOpSerializer,
    CashShiftOperationSerializer,
    CashShiftSerializer,
    CloseShiftSerializer,
    OpenShiftSerializer,
)
from .services import (
    add_cash_operation,
    build_shift_report,
    close_shift,
    get_current_shift,
    open_shift,
    print_x_report,
    print_z_report,
)


class ShiftViewSet(GenericViewSet):
    """Действия со сменой:
    - GET  /shifts/         — список смен (фильтр ?from=&to= по opened_at__date)
    - POST /shifts/open/    — открыть смену
    - POST /shifts/{id}/close/ — закрыть смену
    - GET  /shifts/current/ — текущая открытая (или null)
    - GET  /shifts/{id}/    — детали + аналитика
    """

    serializer_class = CashShiftSerializer
    permission_classes = [IsCashier]

    def get_queryset(self):
        return CashShift.objects.filter(
            restaurant=self.request.user.restaurant
        ).select_related("cashier")

    def list(self, request):
        """Список смен с пагинацией. Фильтры: ?from=YYYY-MM-DD&to=YYYY-MM-DD,
        ?status=open|closed (CSV допустим: status=open,closed)."""
        from common.pagination import StandardPagination

        qs = self.get_queryset().order_by("-opened_at", "-id")
        params = request.query_params

        date_from = params.get("from")
        date_to = params.get("to")
        if date_from:
            qs = qs.filter(opened_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(opened_at__date__lte=date_to)

        statuses = params.get("status")
        if statuses:
            values = [s.strip() for s in statuses.split(",") if s.strip()]
            qs = qs.filter(status__in=values)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            ser = CashShiftSerializer(page, many=True)
            return paginator.get_paginated_response(ser.data)
        return Response(
            {"data": CashShiftSerializer(qs, many=True).data,
             "meta": {"total": qs.count()}}
        )

    @action(detail=False, methods=["post"], url_path="open")
    def open(self, request):
        ser = OpenShiftSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shift = open_shift(
            restaurant=request.user.restaurant,
            cashier=request.user,
            opening_balance=ser.validated_data["opening_balance"],
        )
        return Response(
            {"data": CashShiftSerializer(shift).data},
            status=drf_status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        ser = CloseShiftSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        shift = close_shift(
            shift_id=int(pk),
            restaurant=request.user.restaurant,
            actual_balance=ser.validated_data["actual_balance"],
            note=ser.validated_data.get("note", ""),
        )
        return Response({"data": CashShiftSerializer(shift).data})

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request):
        shift = get_current_shift(request.user.restaurant)
        if shift is None:
            return Response({"data": None})
        return Response({"data": CashShiftSerializer(shift).data})

    def retrieve(self, request, pk=None):
        try:
            shift = self.get_queryset().get(id=pk)
        except CashShift.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404)
        return Response({"data": CashShiftSerializer(shift).data})

    @action(detail=True, methods=["get"], url_path="report")
    def report(self, request, pk=None):
        """Полный отчёт по смене для frame 15-16 (sales by payment/category/
        order_type/waiter + KPI)."""
        try:
            shift = self.get_queryset().get(id=pk)
        except CashShift.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404)
        return Response({"data": build_shift_report(shift)})

    @action(detail=True, methods=["post"], url_path="cash_op")
    def cash_op(self, request, pk=None):
        """Внесение / изъятие наличных в течение смены.

        Body: {kind: 'cash_in'|'cash_out', amount: Decimal, reason: str}
        Доступно только для OPEN-смены.
        """
        try:
            shift = self.get_queryset().get(id=pk)
        except CashShift.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404)
        ser = CashOpSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        op = add_cash_operation(
            shift=shift,
            kind=ser.validated_data["kind"],
            amount=ser.validated_data["amount"],
            reason=ser.validated_data.get("reason", ""),
            user=request.user,
        )
        return Response(
            {"data": CashShiftOperationSerializer(op).data},
            status=drf_status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="cash_ops")
    def cash_ops(self, request, pk=None):
        """Список cash_in/cash_out операций по смене (для отображения в Z)."""
        try:
            shift = self.get_queryset().get(id=pk)
        except CashShift.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404)
        ops = shift.operations.all().order_by("-created_at")
        return Response(
            {"data": CashShiftOperationSerializer(ops, many=True).data}
        )

    @action(detail=True, methods=["post"], url_path="print_z")
    def print_z(self, request, pk=None):
        """Поставить в очередь печать Z-отчёта (cashier-принтер).

        Доступно для open и closed смен — Z-отчёт можно перепечатать.
        """
        try:
            shift = self.get_queryset().get(id=pk)
        except CashShift.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404)
        job = print_z_report(shift)
        return Response(
            {"data": {"job_id": job.id, "shift_id": shift.id}},
            status=drf_status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="print_x")
    def print_x(self, request, pk=None):
        """Промежуточный X-отчёт по открытой смене (можно печатать многократно)."""
        try:
            shift = self.get_queryset().get(id=pk)
        except CashShift.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("SHIFT_NOT_FOUND", "Смена не найдена", 404)
        job = print_x_report(shift, user=request.user)
        return Response(
            {"data": {"job_id": job.id, "shift_id": shift.id}},
            status=drf_status.HTTP_201_CREATED,
        )
