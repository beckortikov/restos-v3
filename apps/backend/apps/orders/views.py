from uuid import UUID

from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.exceptions import BusinessError
from common.permissions import IsCashier, IsCashierOrWaiter

from .models import CancelReason, Discount, Order, OrderStatus, PaymentProvider
from .serializers import (
    CancelReasonSerializer,
    DiscountSerializer,
    OrderCreateSerializer,
    OrderItemWriteSerializer,
    OrderSerializer,
    PaymentProviderSerializer,
)
from .services import (
    add_items_to_order,
    apply_discount,
    assign_waiter,
    cancel_item,
    cancel_order,
    close_order,
    create_order,
    fire_kitchen,
    refund_order,
    remove_discount,
    request_bill,
    set_item_note,
    transfer_order,
)


def _idempotency_key(request) -> UUID:
    raw = request.headers.get("Idempotency-Key", "")
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BusinessError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "Header Idempotency-Key должен быть UUID",
            400,
        ) from exc


class OrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """List + retrieve заказов ресторана.

    list поддерживает:
    - pagination (?page=&page_size=, дефолт 50)
    - filterset_fields: status / table / waiter / shift / order_type / payment_method
    - ?status=new,bill_requested (через запятую — несколько значений)
    - ?from=YYYY-MM-DD&to=YYYY-MM-DD — по created_at
    - ?q=… — поиск по id / table.name / customer_name / items.name_at_order
    """

    from common.pagination import StandardPagination

    serializer_class = OrderSerializer
    pagination_class = StandardPagination
    # status обрабатывается в _apply_query_filters (поддержка CSV "a,b" + single).
    filterset_fields = [
        "table", "waiter", "shift", "order_type", "payment_method",
    ]

    def get_queryset(self):
        # POS-моноблок: и кассир, и официант видят все заказы ресторана.
        qs = (
            Order.objects.filter(restaurant=self.request.user.restaurant)
            .select_related("table", "waiter", "cashier")
            .prefetch_related("items")
        )
        return self._apply_query_filters(qs)

    def _apply_query_filters(self, qs):
        """Кастомные фильтры поверх django-filter:
        - ?status=a,b → status IN [a, b]
        - ?from=YYYY-MM-DD&to=YYYY-MM-DD → created_at__date range
        - ?q=… → поиск по нескольким полям
        - ?include_archived=true → не исключать archived_at != None
        """
        from django.db.models import Q

        params = self.request.query_params

        # Архивные заказы исключаются по умолчанию.
        include_archived = (
            params.get("include_archived", "").lower() in ("true", "1", "yes")
        )
        if not include_archived:
            qs = qs.filter(archived_at__isnull=True)

        statuses = params.get("status")
        if statuses:
            values = [s.strip() for s in statuses.split(",") if s.strip()]
            qs = qs.filter(status__in=values)

        date_from = params.get("from")
        date_to = params.get("to")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        q = (params.get("q") or "").strip()
        if q:
            # Если q — число, ищем по id; иначе по строковым полям.
            id_q = Q()
            if q.isdigit():
                id_q = Q(id=int(q))
            qs = qs.filter(
                id_q
                | Q(table__name__icontains=q)
                | Q(customer_name__icontains=q)
                | Q(customer_phone__icontains=q)
                | Q(items__name_at_order__icontains=q)
            ).distinct()

        return qs

    def get_permissions(self):
        # POS-моноблок: кассир сам создаёт/наполняет заказы (как waiter).
        if self.action in {"create", "add_items", "request_bill", "fire_kitchen"}:
            return [IsCashierOrWaiter()]
        if self.action == "cancel_item":
            return [IsCashierOrWaiter()]
        if self.action == "close":
            return [IsCashier()]
        if self.action == "cancel":
            return [IsCashierOrWaiter()]
        return [permissions.IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset()).order_by("-created_at")
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = OrderSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        return Response(
            {"data": OrderSerializer(qs, many=True).data, "meta": {"total": qs.count()}}
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": OrderSerializer(self.get_object()).data})

    def create(self, request):
        idem = _idempotency_key(request)
        ser = OrderCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        order = create_order(
            restaurant=request.user.restaurant,
            waiter=request.user,
            items_data=v["items"],
            idempotency_key=idem,
            table_id=v.get("table_id"),
            guests_count=v.get("guests_count", 1),
            comment=v.get("comment", ""),
            order_type=v.get("order_type", "hall"),
            customer_name=v.get("customer_name", ""),
            customer_phone=v.get("customer_phone", ""),
            customer_address=v.get("customer_address", ""),
        )
        return Response(
            {"data": OrderSerializer(order).data}, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="add_items")
    def add_items(self, request, pk=None):
        items = request.data.get("items", [])
        ser = OrderItemWriteSerializer(data=items, many=True)
        ser.is_valid(raise_exception=True)
        order = add_items_to_order(
            order_id=int(pk), waiter=request.user, items_data=ser.validated_data
        )
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="set_item_note")
    def set_item_note(self, request, pk=None):
        """Обновить комментарий к позиции (без лука / хорошо прожарить).

        Body: {"item_id": int, "note": str}
        """
        item_id = int(request.data.get("item_id", 0) or 0)
        note = str(request.data.get("note", "") or "")
        if not item_id:
            raise BusinessError("ORDER_ITEM_NOT_FOUND", "Не указана позиция", 422)
        item = set_item_note(item_id=item_id, note=note, actor=request.user)
        # Возвращаем обновлённый заказ (с обновлёнными items)
        order = Order.objects.get(id=item.order_id)
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="cancel_item")
    def cancel_item(self, request, pk=None):
        order = cancel_item(
            order_id=int(pk),
            item_id=int(request.data.get("item_id", 0)),
            user=request.user,
            reason=request.data.get("reason", ""),
        )
        return Response({"data": OrderSerializer(order).data})

    @action(detail=False, methods=["get"], url_path="me")
    def my_orders(self, request):
        """Активные заказы текущего юзера (waiter shortcut).

        Возвращает заказы со статусом `new` или `bill_requested`, где
        `waiter = request.user`. Для удобства мобильного клиента.
        """
        qs = self.get_queryset().filter(
            waiter=request.user,
            status__in=(OrderStatus.NEW, OrderStatus.BILL_REQUESTED),
        ).order_by("-created_at")
        return Response(
            {"data": OrderSerializer(qs, many=True).data,
             "meta": {"total": qs.count()}}
        )

    @action(detail=False, methods=["get"], url_path="me/stats/today")
    def my_today_stats(self, request):
        """Агрегаты по заказам текущего waiter за сегодня (TZ ресторана).

        Включаем все заказы со статусом NEW/BILL_REQUESTED/DONE (т.е. реальные
        чеки + ещё открытые). CANCELLED — исключаем. Возвращает в формате
        ErrorEnvelope-совместимом: {data: {orders_count, total, service_charge,
        tip}}.
        """
        from decimal import Decimal

        from django.db.models import Count, Sum
        from django.utils import timezone as dj_timezone

        start_of_day = dj_timezone.localtime().replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        qs = self.get_queryset().filter(
            waiter=request.user,
            created_at__gte=start_of_day,
        ).exclude(status=OrderStatus.CANCELLED)

        agg = qs.aggregate(
            orders_count=Count("id"),
            total=Sum("total"),
            service_charge=Sum("service_charge_amount"),
            tip=Sum("tip_amount"),
        )
        zero = Decimal("0")
        return Response({
            "data": {
                "orders_count": agg["orders_count"] or 0,
                "total": str(agg["total"] or zero),
                "service_charge": str(agg["service_charge"] or zero),
                "tip": str(agg["tip"] or zero),
            },
        })

    @action(detail=False, methods=["get"], url_path="me/history")
    def my_history(self, request):
        """История завершённых/отменённых заказов текущего юзера.

        Используется HistoryPage в waiter PWA. Лимит по умолчанию 50.
        """
        try:
            limit = max(1, min(200, int(request.query_params.get("limit", 50))))
        except (TypeError, ValueError):
            limit = 50
        qs = self.get_queryset().filter(
            waiter=request.user,
            status__in=(OrderStatus.DONE, OrderStatus.CANCELLED),
        ).order_by("-created_at")[:limit]
        return Response(
            {"data": OrderSerializer(qs, many=True).data,
             "meta": {"total": len(qs)}}
        )

    @action(detail=True, methods=["post"], url_path="fire_kitchen")
    def fire_kitchen(self, request, pk=None):
        """Отправить новые (несрафкированные) позиции заказа на кухонный runner."""
        result = fire_kitchen(order_id=int(pk), user=request.user)
        return Response({"data": result})

    @action(detail=True, methods=["post"], url_path="request_bill")
    def request_bill(self, request, pk=None):
        order = request_bill(order_id=int(pk), waiter=request.user)
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        # Поддерживаем оба формата:
        # - {payment_method: "cash"} — single payment (legacy)
        # - {payments: [{method, amount}, ...]} — multi-payment (Phase 4)
        order, job = close_order(
            order_id=int(pk),
            cashier=request.user,
            payment_method=request.data.get("payment_method"),
            payments=request.data.get("payments"),
            tip_amount=request.data.get("tip_amount"),
        )
        return Response(
            {
                "data": {
                    "order": OrderSerializer(order).data,
                    "print_job": {"id": job.id, "status": job.status},
                }
            }
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        # Manager-override: если сумма заказа >= порога ресторана и юзер
        # не менеджер сам — требуется PIN менеджера в заголовке X-Manager-Pin.
        from decimal import Decimal

        from apps.users.models import UserRole
        from apps.users.permissions import verify_manager_override
        from .models import Order

        try:
            o = Order.objects.get(id=int(pk), restaurant=request.user.restaurant)
        except Order.DoesNotExist:
            from common.exceptions import BusinessError

            raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404)

        threshold = Decimal(str(
            request.user.restaurant.manager_override_threshold_tjs or 0
        ))
        if (
            threshold > 0
            and o.total >= threshold
            and request.user.role != UserRole.MANAGER
        ):
            verify_manager_override(
                request=request, restaurant=request.user.restaurant,
            )

        order = cancel_order(
            order_id=int(pk),
            user=request.user,
            reason=request.data.get("reason", ""),
        )
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="apply_discount")
    def apply_discount(self, request, pk=None):
        """Применить скидку к активному заказу. Body: {"discount_id": int}."""
        did = int(request.data.get("discount_id", 0) or 0)
        if not did:
            raise BusinessError(
                "DISCOUNT_NOT_FOUND", "Не указан discount_id", 422
            )
        order = apply_discount(
            order_id=int(pk), discount_id=did, cashier=request.user
        )
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="remove_discount")
    def remove_discount(self, request, pk=None):
        """Снять скидку с активного заказа."""
        order = remove_discount(order_id=int(pk), cashier=request.user)
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="assign_waiter")
    def assign_waiter(self, request, pk=None):
        """Сменить официанта на заказе.

        Body: {"waiter_id": int}
        """
        target = int(request.data.get("waiter_id", 0) or 0)
        if not target:
            raise BusinessError(
                "USER_NOT_FOUND", "Не указан официант", 422,
            )
        order = assign_waiter(
            order_id=int(pk), target_waiter_id=target, actor=request.user,
        )
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="transfer")
    def transfer(self, request, pk=None):
        """Перенос заказа на другой стол — frame 7.

        Body: {"table_id": int}
        """
        target_id = int(request.data.get("table_id", 0) or 0)
        if not target_id:
            raise BusinessError(
                "TABLE_NOT_FOUND", "Не указан целевой стол", 422
            )
        order = transfer_order(
            order_id=int(pk), target_table_id=target_id, cashier=request.user
        )
        return Response({"data": OrderSerializer(order).data})

    @action(
        detail=True, methods=["post"], url_path="refund",
        permission_classes=[IsCashier],
    )
    def refund(self, request, pk=None):
        """Возврат по закрытому заказу — frame 13.

        Body: {"items": [{"order_item_id": int, "qty": int}, ...], "reason": "..."}
        Если items пуст — полный возврат всех активных позиций.
        """
        idem = _idempotency_key(request)
        items = request.data.get("items") or []
        reason = request.data.get("reason", "")
        refund = refund_order(
            order_id=int(pk),
            cashier=request.user,
            items_data=list(items),
            reason=reason,
            idempotency_key=idem,
        )
        from .serializers import RefundSerializer

        return Response({"data": RefundSerializer(refund).data}, status=201)

    @action(detail=True, methods=["get"], url_path="refunds")
    def list_refunds(self, request, pk=None):
        """Список возвратов по заказу (frame 13 — показ предыдущих возвратов)."""
        from .models import RefundOperation
        from .serializers import RefundSerializer

        qs = RefundOperation.objects.filter(
            order_id=int(pk), restaurant=request.user.restaurant
        ).order_by("-created_at")
        return Response(
            {"data": RefundSerializer(qs, many=True).data, "meta": {"total": qs.count()}}
        )

    @action(detail=True, methods=["post"], url_path="split_print")
    def split_print(self, request, pk=None):
        """Печать N пре-чеков с разделением суммы поровну — frame 6.

        Body: {"parts": int (2..50)}
        """
        from decimal import ROUND_HALF_UP, Decimal

        from apps.orders.models import Order
        from apps.printing.models import PrintJob, PrintJobKind, Printer
        from apps.printing.services import WORKER_EVENT, build_receipt_payload
        from common.exceptions import BusinessError
        from django.utils import timezone

        try:
            parts = int(request.data.get("parts", 0) or 0)
        except (TypeError, ValueError):
            parts = 0
        if not (2 <= parts <= 50):
            raise BusinessError(
                "INVALID_TRANSITION", "parts должен быть 2..50", 422
            )

        try:
            order = Order.objects.get(
                id=int(pk), restaurant=request.user.restaurant
            )
        except Order.DoesNotExist as exc:
            raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

        if not order.items.filter(cancelled_at__isnull=True).exists():
            raise BusinessError("ORDER_EMPTY", "Заказ пустой", 422)

        total = order.total
        share = (total / parts).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # последняя часть забирает остаток после округлений
        last_share = total - share * (parts - 1)

        printer = (
            Printer.objects.filter(
                restaurant=order.restaurant, is_active=True, is_default=True
            ).first()
            or Printer.objects.filter(
                restaurant=order.restaurant, is_active=True
            ).first()
        )
        jobs: list[PrintJob] = []
        for i in range(1, parts + 1):
            s = last_share if i == parts else share
            payload = build_receipt_payload(
                order, split={"index": i, "count": parts, "share": s}
            )
            job = PrintJob.objects.create(
                restaurant=order.restaurant,
                printer=printer,
                order=order,
                kind=PrintJobKind.GUEST_RECEIPT,
                payload=payload,
                scheduled_at=timezone.now(),
            )
            jobs.append(job)
        WORKER_EVENT.set()

        return Response(
            {
                "data": {
                    "parts": parts,
                    "share": str(share),
                    "last_share": str(last_share),
                    "print_jobs": [{"id": j.id, "status": j.status} for j in jobs],
                }
            }
        )

    @action(detail=True, methods=["post"], url_path="print_pre_bill")
    def print_pre_bill(self, request, pk=None):
        """Печать пре-чека (frame 5) — отправляет PrintJob, не меняя статус заказа."""
        from apps.orders.models import Order
        from apps.printing.services import enqueue_receipt_print
        from common.exceptions import BusinessError

        try:
            order = Order.objects.get(
                id=int(pk), restaurant=request.user.restaurant
            )
        except Order.DoesNotExist as exc:
            raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

        if not order.items.filter(cancelled_at__isnull=True).exists():
            raise BusinessError("ORDER_EMPTY", "Заказ пустой", 422)

        # Запускаем печать без изменения order.status — это не close.
        job = enqueue_receipt_print(order)
        return Response(
            {"data": {"print_job": {"id": job.id, "status": job.status}}}
        )

    @action(detail=True, methods=["post"], url_path="reprint_receipt")
    def reprint_receipt(self, request, pk=None):
        """Повторная печать гостевого чека закрытого заказа.

        Доступно только для closed/refunded заказов. Печатает 1 копию с
        пометкой ДУБЛИКАТ в шапке (через payload['copy']={'duplicate': True}).
        Логирует в audit как settings_update / action=reprint_receipt.
        """
        from apps.audit.services import log_request
        from apps.orders.models import Order, OrderStatus
        from apps.printing.models import PrintJob, PrintJobKind, PrintJobStatus
        from apps.printing.services import build_receipt_payload, resolve_printer
        from common.exceptions import BusinessError
        from django.utils import timezone

        try:
            order = Order.objects.get(
                id=int(pk), restaurant=request.user.restaurant
            )
        except Order.DoesNotExist as exc:
            raise BusinessError("ORDER_NOT_FOUND", "Заказ не найден", 404) from exc

        if order.status != OrderStatus.DONE:
            raise BusinessError(
                "INVALID_TRANSITION",
                "Повторная печать доступна только для закрытых заказов",
                422,
            )

        printer = resolve_printer(order.restaurant, PrintJobKind.GUEST_RECEIPT)
        payload = build_receipt_payload(order)
        payload["duplicate"] = True
        job = PrintJob.objects.create(
            restaurant=order.restaurant,
            printer=printer,
            order=order,
            kind=PrintJobKind.GUEST_RECEIPT,
            payload=payload,
            scheduled_at=timezone.now(),
            status=PrintJobStatus.PENDING,
        )
        from apps.printing.services import WORKER_EVENT
        WORKER_EVENT.set()

        log_request(
            request, "settings_update", target=order,
            payload={"action": "reprint_receipt", "order_id": order.id},
        )
        return Response(
            {"data": {"print_job": {"id": job.id, "status": job.status}}}
        )


class CancelReasonViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD причин отмены/возврата — настройки → «Скидки и сервис».

    Кассир/официант (read-only через GET): видят активные причины своего
    ресторана, фильтруются по kind=item|order|refund.
    Кассир (write): создаёт/редактирует/удаляет причины.
    """

    serializer_class = CancelReasonSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    filterset_fields = ["kind", "is_active"]

    def get_queryset(self):
        return CancelReason.objects.filter(restaurant=self.request.user.restaurant)

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsCashier()]
        return [permissions.IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "data": CancelReasonSerializer(qs, many=True).data,
                "meta": {"total": qs.count()},
            }
        )

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        return Response({"data": ser.data}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"data": ser.data})


class _BaseRestaurantViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Общий шаблон CRUD-вьюхи для справочников ресторана:
    - изоляция по restaurant
    - read для всех auth, write для IsCashier
    - формат ответа {"data": [...], "meta": {"total": N}}
    """

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    model = None  # переопределяется

    def get_queryset(self):
        return self.model.objects.filter(restaurant=self.request.user.restaurant)

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsCashier()]
        return [permissions.IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        ser = self.get_serializer(qs, many=True)
        return Response({"data": ser.data, "meta": {"total": qs.count()}})

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        return Response({"data": ser.data}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"data": ser.data})


class PaymentProviderViewSet(_BaseRestaurantViewSet):
    """CRUD способов оплаты — frame 21."""
    serializer_class = PaymentProviderSerializer
    model = PaymentProvider
    filterset_fields = ["kind", "is_active"]


class DiscountViewSet(_BaseRestaurantViewSet):
    """CRUD скидок и сервисного сбора — frame 22."""
    serializer_class = DiscountSerializer
    model = Discount
    filterset_fields = ["type", "kind", "is_active"]
