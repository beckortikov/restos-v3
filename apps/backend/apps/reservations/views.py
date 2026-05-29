from rest_framework import mixins, status as drf_status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsCashierOrWaiter

from .models import Reservation, ReservationStatus
from .serializers import (
    ReservationCancelSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
)
from .services import (
    cancel_reservation,
    confirm_reservation,
    create_reservation,
    mark_no_show,
    seat_reservation,
)


class ReservationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD-эндпоинт резерваций.

    Фильтры:
    - `?status=pending,confirmed` (CSV)
    - `?from=YYYY-MM-DD&to=YYYY-MM-DD` (по scheduled_at__date)
    - `?table=ID`
    - `?active=true` — только активные сейчас (pending/confirmed)
    """

    serializer_class = ReservationSerializer
    permission_classes = [IsCashierOrWaiter]

    def get_queryset(self):
        return (
            Reservation.objects
            .filter(restaurant=self.request.user.restaurant)
            .select_related("table")
        )

    def list(self, request, *args, **kwargs):
        from common.pagination import StandardPagination

        qs = self.get_queryset().order_by("-scheduled_at", "-id")
        params = request.query_params

        statuses = params.get("status")
        if statuses:
            values = [s.strip() for s in statuses.split(",") if s.strip()]
            qs = qs.filter(status__in=values)

        date_from = params.get("from")
        date_to = params.get("to")
        if date_from:
            qs = qs.filter(scheduled_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_at__date__lte=date_to)

        table_id = params.get("table")
        if table_id:
            qs = qs.filter(table_id=int(table_id))

        active = params.get("active", "").lower() in ("true", "1", "yes")
        if active:
            qs = qs.filter(
                status__in=(
                    ReservationStatus.PENDING,
                    ReservationStatus.CONFIRMED,
                ),
            )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                ReservationSerializer(page, many=True).data
            )
        return Response(
            {"data": ReservationSerializer(qs, many=True).data,
             "meta": {"total": qs.count()}}
        )

    def retrieve(self, request, *args, **kwargs):
        return Response(
            {"data": ReservationSerializer(self.get_object()).data}
        )

    def create(self, request):
        from apps.tables.models import Table
        from common.exceptions import BusinessError

        ser = ReservationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        try:
            table = Table.objects.get(
                id=v["table"], restaurant=request.user.restaurant,
            )
        except Table.DoesNotExist as exc:
            raise BusinessError("TABLE_NOT_FOUND", "Стол не найден", 404) from exc

        r = create_reservation(
            restaurant=request.user.restaurant,
            table=table,
            customer_name=v["customer_name"],
            customer_phone=v.get("customer_phone", ""),
            party_size=v.get("party_size", 2),
            scheduled_at=v["scheduled_at"],
            duration_min=v.get("duration_min", 120),
            notes=v.get("notes", ""),
            user=request.user,
        )
        return Response(
            {"data": ReservationSerializer(r).data},
            status=drf_status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        r = confirm_reservation(
            reservation_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": ReservationSerializer(r).data})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ser = ReservationCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        r = cancel_reservation(
            reservation_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
            reason=ser.validated_data.get("reason", ""),
        )
        return Response({"data": ReservationSerializer(r).data})

    @action(detail=True, methods=["post"], url_path="no_show")
    def no_show(self, request, pk=None):
        r = mark_no_show(
            reservation_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
        )
        return Response({"data": ReservationSerializer(r).data})

    @action(detail=True, methods=["post"])
    def seat(self, request, pk=None):
        """Отметить «гости пришли». В простой версии — просто меняем статус.
        Связывание с Order — отдельный flow в UI (cashier открывает резервацию,
        затем делает create_order, затем второй POST `seat` с order_id)."""
        from apps.orders.models import Order
        from common.exceptions import BusinessError

        order = None
        order_id = request.data.get("order_id")
        if order_id:
            try:
                order = Order.objects.get(
                    id=int(order_id),
                    restaurant=request.user.restaurant,
                )
            except Order.DoesNotExist as exc:
                raise BusinessError(
                    "ORDER_NOT_FOUND", "Заказ не найден", 404,
                ) from exc

        r = seat_reservation(
            reservation_id=int(pk),
            restaurant=request.user.restaurant,
            user=request.user,
            order=order,
        )
        return Response({"data": ReservationSerializer(r).data})
