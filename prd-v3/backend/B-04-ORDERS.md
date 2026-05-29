# B-04 — Заказы (ядро MVP)

Это центральный модуль. Все три приложения общаются с ним:
- waiter создаёт заказ и добавляет позиции;
- кассир закрывает заказ и инициирует печать;
- статусы проходят `new → bill_requested → done` (или `cancelled`).

## Модели

```python
# apps/orders/models.py

class OrderStatus(models.TextChoices):
    NEW            = "new",            "Новый"
    BILL_REQUESTED = "bill_requested", "Счёт"
    DONE           = "done",           "Оплачен"
    CANCELLED      = "cancelled",      "Отменён"


class PaymentMethod(models.TextChoices):
    CASH     = "cash",     "Наличные"
    CARD     = "card",     "Карта"
    TRANSFER = "transfer", "Перевод"


class Order(models.Model):
    restaurant         = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE,
                                            related_name="orders")
    status             = models.CharField(max_length=16, choices=OrderStatus.choices,
                                          default=OrderStatus.NEW, db_index=True)
    table              = models.ForeignKey("tables.Table", on_delete=models.PROTECT,
                                            related_name="orders")
    waiter             = models.ForeignKey("users.User", on_delete=models.PROTECT,
                                            related_name="orders_as_waiter")
    cashier            = models.ForeignKey("users.User", on_delete=models.SET_NULL,
                                            null=True, blank=True,
                                            related_name="orders_as_cashier")
    guests_count       = models.PositiveSmallIntegerField(default=1)
    payment_method     = models.CharField(max_length=10, choices=PaymentMethod.choices,
                                          null=True, blank=True)
    comment            = models.TextField(blank=True)
    idempotency_key    = models.UUIDField(unique=True, db_index=True)
    created_at         = models.DateTimeField(auto_now_add=True, db_index=True)
    bill_requested_at  = models.DateTimeField(null=True, blank=True)
    closed_at          = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at       = models.DateTimeField(null=True, blank=True)
    cancelled_by       = models.ForeignKey("users.User", on_delete=models.SET_NULL,
                                            null=True, blank=True,
                                            related_name="orders_cancelled")
    cancel_reason      = models.TextField(blank=True)
    updated_at         = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = "orders"
        ordering = ["-created_at"]

    @property
    def total(self) -> Decimal:
        return sum(
            (it.subtotal for it in self.items.all() if it.cancelled_at is None),
            Decimal("0.00"),
        )

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED)


class OrderItem(models.Model):
    order            = models.ForeignKey(Order, on_delete=models.CASCADE,
                                          related_name="items")
    menu_item        = models.ForeignKey("menu.MenuItem", on_delete=models.PROTECT)
    name_at_order    = models.CharField(max_length=128)
    price_at_order   = models.DecimalField(max_digits=14, decimal_places=2)
    qty              = models.PositiveIntegerField(default=1)
    cancelled_at     = models.DateTimeField(null=True, blank=True)
    cancelled_by     = models.ForeignKey("users.User", on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name="+")
    cancel_reason    = models.TextField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_items"

    @property
    def subtotal(self) -> Decimal:
        return self.price_at_order * self.qty
```

## Жизненный цикл

```
            ┌─────┐
   create → │ NEW │
            └──┬──┘  add_items, cancel_item
               │     request_bill (waiter)
               ▼
       ┌────────────────┐
       │ BILL_REQUESTED │ ← кассир получает SSE event: order.updated
       └────────┬───────┘
                │ close (cashier)
                ▼
              ┌──────┐
              │ DONE │ → enqueue_receipt_print + free_table
              └──────┘

   cancel из NEW и BILL_REQUESTED → CANCELLED + free_table
   из DONE — отменить нельзя (422 INVALID_TRANSITION)
```

## Сериализаторы

```python
# apps/orders/serializers.py

class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "menu_item", "name_at_order", "price_at_order", "qty",
                  "cancelled_at", "cancel_reason", "subtotal"]
        read_only_fields = ["name_at_order", "price_at_order"]


class OrderItemWriteSerializer(serializers.Serializer):
    menu_item_id = serializers.IntegerField()
    qty          = serializers.IntegerField(min_value=1, max_value=999)


class OrderSerializer(serializers.ModelSerializer):
    items       = OrderItemSerializer(many=True, read_only=True)
    total       = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    table_name  = serializers.CharField(source="table.name", read_only=True)
    waiter_name = serializers.CharField(source="waiter.full_name", read_only=True)
    cashier_name = serializers.CharField(source="cashier.full_name", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "status", "table", "table_name", "waiter", "waiter_name",
                  "cashier", "cashier_name", "guests_count", "payment_method",
                  "comment", "items", "total",
                  "created_at", "bill_requested_at", "closed_at",
                  "cancelled_at", "cancel_reason", "updated_at"]
        read_only_fields = ["id", "status", "cashier", "payment_method",
                            "created_at", "bill_requested_at", "closed_at",
                            "cancelled_at", "cancel_reason", "updated_at"]


class OrderCreateSerializer(serializers.Serializer):
    table_id     = serializers.IntegerField()
    guests_count = serializers.IntegerField(min_value=1, max_value=99, default=1)
    items        = OrderItemWriteSerializer(many=True, min_length=1)
    comment      = serializers.CharField(required=False, allow_blank=True, default="")


# Лёгкий «poll» сериализатор не нужен: обновления заказов транслируются
# через SSE-событие `order.updated` (apps/events). Поля события собираются
# в apps/events/signals.py.
```

## Сервисы

```python
# apps/orders/services.py
from django.db import transaction
from django.utils import timezone
from common.exceptions import BusinessError
from apps.tables.models import Table, TableStatus
from apps.tables.services import free_table
from apps.menu.models import MenuItem
from apps.printing.services import enqueue_receipt_print


@transaction.atomic
def create_order(*, restaurant, table_id, waiter, guests_count, items_data,
                 comment, idempotency_key) -> Order:
    if existing := Order.objects.filter(idempotency_key=idempotency_key).first():
        return existing

    table = Table.objects.select_for_update().get(id=table_id, restaurant=restaurant)
    if table.status == TableStatus.OCCUPIED and table.current_order_id is not None:
        raise BusinessError("TABLE_OCCUPIED", f"{table.name} занят", 409)

    order = Order.objects.create(
        restaurant=restaurant, table=table, waiter=waiter,
        guests_count=guests_count, comment=comment,
        idempotency_key=idempotency_key, status=OrderStatus.NEW,
    )

    for it in items_data:
        mi = MenuItem.objects.get(id=it["menu_item_id"], restaurant=restaurant)
        if not mi.is_available:
            raise BusinessError("MENU_ITEM_UNAVAILABLE", f"«{mi.name}» недоступно", 422)
        OrderItem.objects.create(
            order=order, menu_item=mi,
            name_at_order=mi.name, price_at_order=mi.price,
            qty=it["qty"],
        )

    table.status = TableStatus.OCCUPIED
    table.current_order = order
    table.waiter = waiter
    table.opened_at = timezone.now()
    table.save(update_fields=["status", "current_order", "waiter", "opened_at"])

    return order


@transaction.atomic
def add_items_to_order(*, order_id, waiter, items_data) -> Order:
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status != OrderStatus.NEW:
        raise BusinessError("INVALID_TRANSITION",
                            f"Нельзя добавить в заказ со статусом {order.status}", 422)
    for it in items_data:
        mi = MenuItem.objects.get(id=it["menu_item_id"], restaurant=order.restaurant)
        if not mi.is_available:
            raise BusinessError("MENU_ITEM_UNAVAILABLE", f"«{mi.name}» недоступно", 422)
        existing = order.items.filter(menu_item=mi, cancelled_at__isnull=True).first()
        if existing:
            existing.qty += it["qty"]
            existing.save(update_fields=["qty"])
        else:
            OrderItem.objects.create(
                order=order, menu_item=mi,
                name_at_order=mi.name, price_at_order=mi.price,
                qty=it["qty"],
            )
    return order


@transaction.atomic
def cancel_item(*, order_id, item_id, user, reason) -> Order:
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status not in (OrderStatus.NEW, OrderStatus.BILL_REQUESTED):
        raise BusinessError("INVALID_TRANSITION",
                            "Нельзя отменить позицию закрытого заказа", 422)
    item = order.items.select_for_update().get(id=item_id)
    if item.cancelled_at:
        raise BusinessError("INVALID_TRANSITION", "Позиция уже отменена", 422)
    if not (reason or "").strip():
        raise BusinessError("INVALID_TRANSITION", "Нужна причина отмены", 422)

    item.cancelled_at = timezone.now()
    item.cancelled_by = user
    item.cancel_reason = reason
    item.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])

    # если все позиции отменены — отменяем заказ целиком
    if not order.items.filter(cancelled_at__isnull=True).exists():
        cancel_order(order_id=order.id, user=user, reason="Все позиции отменены")
    return order


@transaction.atomic
def request_bill(*, order_id, waiter) -> Order:
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status != OrderStatus.NEW:
        raise BusinessError("INVALID_TRANSITION",
                            f"Нельзя запросить счёт из статуса {order.status}", 422)
    if not order.items.filter(cancelled_at__isnull=True).exists():
        raise BusinessError("ORDER_EMPTY", "Заказ пустой", 422)

    order.status = OrderStatus.BILL_REQUESTED
    order.bill_requested_at = timezone.now()
    order.save(update_fields=["status", "bill_requested_at"])

    # подсветим стол
    if order.table.status != TableStatus.BILL_REQUESTED:
        order.table.status = TableStatus.BILL_REQUESTED
        order.table.save(update_fields=["status"])
    return order


@transaction.atomic
def close_order(*, order_id, cashier, payment_method) -> tuple[Order, "PrintJob"]:
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status == OrderStatus.DONE:
        raise BusinessError("ORDER_ALREADY_CLOSED", "Заказ уже закрыт", 409)
    if order.status == OrderStatus.CANCELLED:
        raise BusinessError("INVALID_TRANSITION", "Заказ отменён, оплатить нельзя", 422)
    if not order.items.filter(cancelled_at__isnull=True).exists():
        raise BusinessError("ORDER_EMPTY", "Нет активных позиций", 422)
    if payment_method not in PaymentMethod.values:
        raise BusinessError("INVALID_TRANSITION", "Неизвестный метод оплаты", 422)

    order.status = OrderStatus.DONE
    order.cashier = cashier
    order.payment_method = payment_method
    order.closed_at = timezone.now()
    order.save(update_fields=["status", "cashier", "payment_method", "closed_at"])

    free_table(order.table)
    job = enqueue_receipt_print(order)
    return order, job


@transaction.atomic
def cancel_order(*, order_id, user, reason) -> Order:
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status == OrderStatus.DONE:
        raise BusinessError("ORDER_ALREADY_CLOSED", "Закрытый заказ отменить нельзя", 409)
    if order.status == OrderStatus.CANCELLED:
        return order  # идемпотентно

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = user
    order.cancel_reason = reason or ""
    order.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason"])

    free_table(order.table)
    return order
```

## Views

```python
# apps/orders/views.py

class OrderViewSet(viewsets.GenericViewSet,
                   mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = OrderSerializer
    filterset_fields = ["status", "table", "waiter"]

    def get_queryset(self):
        qs = Order.objects.filter(restaurant=self.request.user.restaurant) \
                          .select_related("table", "waiter", "cashier") \
                          .prefetch_related("items")
        if self.request.user.role == "waiter":
            qs = qs.filter(waiter=self.request.user)
        return qs

    def get_permissions(self):
        if self.action == "create":
            return [IsWaiter()]
        if self.action == "add_items":
            return [IsWaiter()]
        if self.action == "request_bill":
            return [IsWaiter()]
        if self.action == "close":
            return [IsCashier()]
        return [permissions.IsAuthenticated()]

    def create(self, request):
        ser = OrderCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        idem = request.idempotency_key
        order = create_order(
            restaurant=request.user.restaurant,
            table_id=ser.validated_data["table_id"],
            waiter=request.user,
            guests_count=ser.validated_data["guests_count"],
            items_data=ser.validated_data["items"],
            comment=ser.validated_data["comment"],
            idempotency_key=idem,
        )
        return Response({"data": OrderSerializer(order).data},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="add_items")
    def add_items(self, request, pk=None):
        items = request.data.get("items", [])
        ser = OrderItemWriteSerializer(data=items, many=True)
        ser.is_valid(raise_exception=True)
        order = add_items_to_order(order_id=pk, waiter=request.user,
                                    items_data=ser.validated_data)
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="cancel_item")
    def cancel_item(self, request, pk=None):
        item_id = request.data.get("item_id")
        reason  = request.data.get("reason", "")
        order = cancel_item(order_id=pk, item_id=item_id,
                            user=request.user, reason=reason)
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"], url_path="request_bill")
    def request_bill(self, request, pk=None):
        order = request_bill(order_id=pk, waiter=request.user)
        return Response({"data": OrderSerializer(order).data})

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        pm = request.data.get("payment_method")
        order, job = close_order(order_id=pk, cashier=request.user, payment_method=pm)
        return Response({"data": {
            "order": OrderSerializer(order).data,
            "print_job": {"id": job.id, "status": job.status},
        }})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = cancel_order(order_id=pk, user=request.user,
                             reason=request.data.get("reason", ""))
        return Response({"data": OrderSerializer(order).data})

```

Никакого `poll`-action: клиенты подписаны на SSE `/api/v1/events/` и получают `order.created` / `order.updated` в реальном времени.

```python
# apps/orders/urls.py
router = DefaultRouter()
router.register("", OrderViewSet, basename="order")
urlpatterns = [path("orders/", include(router.urls))]
```

## Эндпоинты

| Метод | URL | Кто | Эффект |
|---|---|---|---|
| GET | `/api/v1/orders/` | оба | список (waiter — только свои) |
| POST | `/api/v1/orders/` | waiter | создать (idempotency обяз.) |
| GET | `/api/v1/orders/{id}/` | оба | деталь с items |
| POST | `/api/v1/orders/{id}/add_items/` | waiter | добавить позиции |
| POST | `/api/v1/orders/{id}/cancel_item/` | оба | отменить позицию (с причиной) |
| POST | `/api/v1/orders/{id}/request_bill/` | waiter | NEW → BILL_REQUESTED |
| POST | `/api/v1/orders/{id}/close/` | cashier | BILL_REQUESTED/NEW → DONE + печать + free_table |
| POST | `/api/v1/orders/{id}/cancel/` | оба | до DONE → CANCELLED + free_table |

## Гонки и одновременный доступ

- `select_for_update` на `Table` и `Order` — обязательно во всех мутациях.
- Если два waiter'а одновременно жмут «открыть стол» — один получит OK, второй — `TABLE_OCCUPIED 409`.
- Если waiter жмёт «request_bill» в момент, когда кассир уже жмёт «close» (статус ещё `NEW`) — кто первый возьмёт row-lock, тот и сделает свой переход; второй увидит `INVALID_TRANSITION` и обновит UI.

## Тесты

`apps/orders/tests/test_services.py` (минимум):

1. `create_order_happy_path` — стол свободен, 2 позиции, проверка `total`, `Table.status`, `current_order`.
2. `create_order_with_existing_idempotency_key_returns_same` — повтор с тем же UUID не создаёт дубль.
3. `create_order_on_occupied_table_raises_409`.
4. `create_order_with_unavailable_item_raises_422`.
5. `add_items_in_non_new_status_raises`.
6. `cancel_item_when_last_active_cancels_order`.
7. `request_bill_empties_raises_ORDER_EMPTY`.
8. `close_order_happy_path` — статус, кассир, `closed_at`, освобождён стол, создан `PrintJob`.
9. `close_already_done_raises_409`.
10. `cancel_done_raises_409`.
11. `concurrent_create_on_same_table_one_wins` — `threading.Thread` × 2.

## Замечания по контракту с MVP-кодом

- В текущем коде RestOS v1 (`lib/types.ts`) есть статусы `cooking/ready/served` — в MVP они **не используются**, появятся в Phase 2 вместе с кухней.
- В коде также есть `Order.payments[]`, `discount_*`, `tip_amount`, `service_percent`, `OrderSplit`, `OrderItem.modifiers`, `OrderItem.printed_at/served_at` — в MVP всё это **не входит**.
- Поле `Order.shift_id` (привязка к кассовой смене) появится в Phase 2.
