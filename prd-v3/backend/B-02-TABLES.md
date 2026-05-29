# B-02 — Столы и зоны

## Модели

```python
# apps/tables/models.py

class TableStatus(models.TextChoices):
    FREE           = "free",           "Свободен"
    OCCUPIED       = "occupied",       "Занят"
    BILL_REQUESTED = "bill_requested", "Счёт"


class Zone(models.Model):
    restaurant = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE, related_name="zones")
    name       = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "zones"
        ordering = ["sort_order", "name"]


class Table(models.Model):
    restaurant       = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE, related_name="tables")
    zone             = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="tables")
    number           = models.PositiveSmallIntegerField()
    name             = models.CharField(max_length=64)
    capacity         = models.PositiveSmallIntegerField(default=2)
    status           = models.CharField(max_length=16, choices=TableStatus.choices,
                                        default=TableStatus.FREE, db_index=True)
    current_order    = models.ForeignKey("orders.Order", on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name="+")
    waiter           = models.ForeignKey("users.User", on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name="+")
    opened_at        = models.DateTimeField(null=True, blank=True)
    updated_at       = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = "tables"
        ordering = ["zone__sort_order", "number"]
        unique_together = [("restaurant", "number")]
```

## Сериализаторы

```python
class ZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zone
        fields = ["id", "name", "sort_order"]


class TableSerializer(serializers.ModelSerializer):
    zone_name      = serializers.CharField(source="zone.name", read_only=True)
    waiter_name    = serializers.CharField(source="waiter.full_name", read_only=True)
    current_order  = serializers.IntegerField(source="current_order_id", read_only=True)

    class Meta:
        model = Table
        fields = ["id", "number", "name", "capacity",
                  "zone", "zone_name",
                  "status", "current_order",
                  "waiter", "waiter_name", "opened_at", "updated_at"]


# Лёгкий вариант сериализатора больше не нужен — обновления едут через SSE
# (см. backend/B-06-EVENTS.md), payload события `table.updated` собирается там.
```

## Сервис

```python
# apps/tables/services.py

@transaction.atomic
def open_table(*, table_id: int, waiter, guests_count: int) -> Table:
    table = Table.objects.select_for_update().get(id=table_id)
    if table.status == TableStatus.OCCUPIED:
        raise BusinessError("TABLE_OCCUPIED", f"{table.name} уже занят", 409)
    table.status = TableStatus.OCCUPIED
    table.waiter = waiter
    table.opened_at = timezone.now()
    table.save(update_fields=["status", "waiter", "opened_at"])
    return table


def free_table(table: Table) -> None:
    """Вызывается из orders.services при close/cancel заказа."""
    table.status = TableStatus.FREE
    table.current_order = None
    table.waiter = None
    table.opened_at = None
    table.save(update_fields=["status", "current_order", "waiter", "opened_at"])
```

## Views и URLs

```python
# apps/tables/views.py

class ZoneViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    pagination_class = None

    def get_queryset(self):
        return self.queryset.filter(restaurant=self.request.user.restaurant)


class TableViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = TableSerializer
    filterset_fields = ["zone", "status"]

    def get_queryset(self):
        return Table.objects.filter(restaurant=self.request.user.restaurant) \
                            .select_related("zone", "waiter", "current_order")

    @action(detail=True, methods=["post"], permission_classes=[IsWaiter])
    def open(self, request, pk=None):
        table = open_table(
            table_id=pk,
            waiter=request.user,
            guests_count=int(request.data.get("guests_count", 1)),
        )
        return Response({"data": TableSerializer(table).data})
```

```python
# apps/tables/urls.py
router = DefaultRouter()
router.register("zones", ZoneViewSet, basename="zone")
router.register("", TableViewSet, basename="table")
urlpatterns = [path("tables/", include(router.urls))]
```

## Эндпоинты

| Метод | URL | Что делает | Кто |
|---|---|---|---|
| GET | `/api/v1/tables/zones/` | Список зон | оба |
| GET | `/api/v1/tables/` | Список столов (фильтр `zone`, `status`) | оба |
| GET | `/api/v1/tables/{id}/` | Деталь стола | оба |
| POST | `/api/v1/tables/{id}/open/` | Открыть стол | waiter |

Обновления статусов столов **не** через `/poll/` — клиент подписан на SSE `/events/` и получает `event: table.updated` мгновенно. См. [B-06-EVENTS.md](B-06-EVENTS.md).

## Замечания

- Открытие стола вызывается **до** `POST /orders/`. Если `create_order` обнаружит, что стол уже `occupied`, отдаст `TABLE_OCCUPIED 409`. На практике waiter сразу делает `open` + `create_order` — это две операции, но `create_order` тоже берёт `select_for_update`, поэтому гонка двух официантов на один стол всегда увидит конфликт.
- Освобождение стола (`free_table`) вызывается из `orders.services.close_order` и `cancel_order` в той же транзакции.
- `current_order` хранится для удобства клиента: в payload SSE-события `table.updated` сразу есть id текущего заказа — клиент идёт за деталями только для нужного.
- `merged_with` (объединение столов) и `Reservation` — Phase 2.
