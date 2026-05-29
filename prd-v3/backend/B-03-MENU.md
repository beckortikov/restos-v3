# B-03 — Меню

В MVP — минимальное меню: категория + блюдо. Без техкарт, модификаторов, weight-based, стоп-листа, импорта Excel — это Phase 2.

## Модели

```python
# apps/menu/models.py

class Category(models.Model):
    restaurant = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE, related_name="categories")
    name       = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "menu_categories"
        ordering = ["sort_order", "name"]


class MenuItem(models.Model):
    restaurant   = models.ForeignKey("users.Restaurant", on_delete=models.CASCADE, related_name="menu_items")
    category     = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name         = models.CharField(max_length=128)
    price        = models.DecimalField(max_digits=14, decimal_places=2)
    emoji        = models.CharField(max_length=8, blank=True)
    image        = models.ImageField(upload_to="menu/", blank=True, null=True)
    sort_order   = models.PositiveSmallIntegerField(default=0)
    is_available = models.BooleanField(default=True, db_index=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_items"
        ordering = ["category__sort_order", "sort_order", "name"]
```

## Сериализаторы

```python
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "sort_order"]


class MenuItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = MenuItem
        fields = ["id", "category", "name", "price", "emoji",
                  "image_url", "sort_order", "is_available"]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        return obj.image.url
```

## Views

```python
# apps/menu/views.py

class CategoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        return Category.objects.filter(restaurant=self.request.user.restaurant)


class MenuItemViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = MenuItemSerializer
    filterset_fields = ["category", "is_available"]
    pagination_class = None      # меню целиком отдаём одним батчем (≤ 500 блюд)

    def get_queryset(self):
        return MenuItem.objects.filter(restaurant=self.request.user.restaurant)\
                               .select_related("category")

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        # ETag = max(updated_at).timestamp() + count
        last = qs.order_by("-updated_at").values_list("updated_at", flat=True).first()
        cnt = qs.count()
        etag = f'W/"{int(last.timestamp()) if last else 0}-{cnt}"'

        if request.headers.get("If-None-Match") == etag:
            resp = Response(status=304)
        else:
            resp = Response({"data": MenuItemSerializer(qs, many=True).data,
                             "meta": {"total": cnt}})
        resp["ETag"] = etag
        resp["Cache-Control"] = "max-age=300"
        return resp
```

```python
# apps/menu/urls.py
router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="menu-category")
router.register("items", MenuItemViewSet, basename="menu-item")
urlpatterns = [path("menu/", include(router.urls))]
```

## Эндпоинты

| Метод | URL | Что делает |
|---|---|---|
| GET | `/api/v1/menu/categories/` | Список категорий |
| GET | `/api/v1/menu/items/` | Все блюда (с ETag) |
| GET | `/api/v1/menu/items/{id}/` | Деталь блюда |

## Кэширование на клиенте

- Сервер отдаёт `ETag: W/"<ts>-<count>"` и `Cache-Control: max-age=300`.
- Клиент (waiter PWA, cashier PySide) шлёт `If-None-Match` — при отсутствии изменений получает `304 Not Modified` без тела.
- При изменении меню backend публикует SSE-событие `menu.invalidated` (см. B-06). Клиент по нему форсированно перезапрашивает `/menu/items/` с обновлённым ETag.
- В waiter-PWA service worker делает cache-first для `/api/v1/menu/items/` и `/media/menu/*`.
- В cashier PySide — кэш в `apsw` SQLite, хэш сравнивается перед запросом.

## Управление

В MVP блюда создаются и редактируются **только через Django admin**. Импорт Excel, фотографии, перетаскивание сортировки — Phase 2.

`is_available=false` — единственный способ убрать блюдо из меню в реальном времени; если кто-то попытается заказать недоступное блюдо, `create_order` отдаст `MENU_ITEM_UNAVAILABLE 422`.
