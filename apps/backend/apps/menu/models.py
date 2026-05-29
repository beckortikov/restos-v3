from django.db import models


class Category(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="categories"
    )
    name = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField(default=0)
    # Цех печати: на какую станцию отправлять блюда этой категории на кухню.
    # null → нет автопечати кухонного заказа (например для напитков-готовых).
    print_station = models.ForeignKey(
        "printing.PrintStation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categories",
    )

    class Meta:
        db_table = "menu_categories"
        ordering = ["sort_order", "name"]
        verbose_name = "Категория меню"
        verbose_name_plural = "Категории меню"

    def __str__(self) -> str:
        return self.name


class MenuItemNote(models.Model):
    """Шаблон комментария к блюду — динамический справочник.

    Примеры: «Без лука», «Хорошо прожарить», «Острее», «Не острое».
    Не хардкодим список — админ через UI редактирует. Используется как
    chip-picker в MenuScreen при добавлении блюда в корзину; результат
    сохраняется в OrderItem.note (snapshot текста на момент заказа).
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="item_notes",
    )
    label = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_item_notes"
        ordering = ["sort_order", "label"]
        unique_together = [("restaurant", "label")]
        verbose_name = "Шаблон комментария"
        verbose_name_plural = "Шаблоны комментариев к блюдам"

    def __str__(self) -> str:
        return self.label


class ModifierGroup(models.Model):
    """Группа модификаторов (например, «Степень прожарки», «Соусы», «Размер порции»).

    Группа содержит одну/несколько `Modifier`. К `MenuItem` подключается через
    M2M (`MenuItem.modifier_groups`). При выборе блюда в POS — кассир должен
    выбрать min_select..max_select модификаторов из каждой группы; если
    `is_required=True` и модификатор не выбран — блокируется добавление.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="modifier_groups",
    )
    name = models.CharField(max_length=64)
    min_select = models.PositiveSmallIntegerField(default=0)
    max_select = models.PositiveSmallIntegerField(default=1)
    is_required = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_modifier_groups"
        ordering = ["sort_order", "name"]
        unique_together = [("restaurant", "name")]
        verbose_name = "Группа модификаторов"
        verbose_name_plural = "Группы модификаторов"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_select__lte=models.F("max_select")),
                name="modgroup_min_le_max",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Modifier(models.Model):
    """Один вариант внутри `ModifierGroup` (например, «Острый соус +2 ТЖС»).

    `price_delta` может быть >0 (доплата) или <0 (скидка). Применяется поверх
    `MenuItem.price` за каждую единицу qty в `OrderItem`.
    """

    group = models.ForeignKey(
        ModifierGroup, on_delete=models.CASCADE, related_name="modifiers"
    )
    name = models.CharField(max_length=64)
    price_delta = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Доплата (>0) или скидка (<0) к цене блюда за единицу",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_modifiers"
        ordering = ["sort_order", "name"]
        unique_together = [("group", "name")]
        verbose_name = "Модификатор"
        verbose_name_plural = "Модификаторы"

    def __str__(self) -> str:
        return self.name


class MenuItemKind(models.TextChoices):
    """Тип блюда — для UI-маркировки и аналитики.

    В отличие от `Category` (что показывает блюдо), `kind` описывает
    *как* оно готовится / откуда идёт, и используется для:
    - бейджей на карточке блюда («Гриль», «Бар»)
    - группировки в отчётах
    - роутинга кухонной печати (опционально, override Category.print_station).
    """

    HOT_KITCHEN = "hot_kitchen", "Горячий цех"
    COLD_KITCHEN = "cold_kitchen", "Холодный цех"
    GRILL = "grill", "Шашлычный / Гриль"
    BAR = "bar", "Бар"
    SHOWCASE = "showcase", "Витрина"
    DRINK = "drink", "Напиток"
    DESSERT = "dessert", "Десерт"


class MenuItemUnit(models.TextChoices):
    """Единица измерения для продажи."""

    PIECE = "piece", "Штука"
    GRAM = "g", "Грамм"
    KG = "kg", "Килограмм"


class MenuItem(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="menu_items"
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=128)
    price = models.DecimalField(max_digits=14, decimal_places=2)
    emoji = models.CharField(max_length=8, blank=True)
    image = models.ImageField(upload_to="menu/", blank=True, null=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_available = models.BooleanField(default=True, db_index=True)
    # Stop-list: причина и дата возврата (когда снова появится). Заполняются
    # при is_available=False через POST /menu/items/{id}/stop_list/.
    # При is_available=True игнорируются.
    stop_reason = models.CharField(
        max_length=255, blank=True,
        help_text="Причина снятия со стоп-листа (например, «Закончилась говядина»)",
    )
    stop_until = models.DateField(
        null=True, blank=True,
        help_text="Дата когда блюдо снова станет доступным (опц.)",
    )
    # Phase 8D — авто-стоп от нехватки ингредиентов.
    # Если auto_stopped=True, блюдо в стопе именно потому, что движение склада
    # увело какой-то ingredient/semi ниже порога 1 порции. Снимается автоматически
    # при следующем приходе. Ручной стоп (auto_stopped=False) авто-логикой не трогается.
    auto_stopped = models.BooleanField(
        default=False, db_index=True,
        help_text="Снято со стопа автоматически из-за пустого склада (≠ ручной стоп)",
    )
    # Менеджер/кассир разрешил продавать «в минус» — авто-стоп игнорирует это блюдо
    # до тех пор, пока флаг не снимут. Закупка не сбрасывает.
    allow_oversell = models.BooleanField(
        default=False,
        help_text="Разрешить продажу при нулевых остатках (override авто-стопа)",
    )
    # Группы модификаторов, доступные для этого блюда (M2M, без through-таблицы
    # с extra-полями — порядок групп определяется ModifierGroup.sort_order).
    modifier_groups = models.ManyToManyField(
        ModifierGroup, blank=True, related_name="menu_items",
    )

    # ── Тип блюда ────────────────────────────────────────────────────────
    kind = models.CharField(
        max_length=16, choices=MenuItemKind.choices,
        default=MenuItemKind.HOT_KITCHEN, db_index=True,
        help_text="Где/как готовится: горячий цех, бар, гриль и т.д.",
    )

    # ── Финансы / KDS ────────────────────────────────────────────────────
    cogs = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Себестоимость единицы (для аналитики маржинальности)",
    )
    cook_time_min = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Время готовки в минутах (для таймера KDS)",
    )

    # ── Закупной товар ───────────────────────────────────────────────────
    is_purchased = models.BooleanField(
        default=False,
        help_text="Покупной товар (без техкарты) — кофе/снеки от поставщика",
    )
    # Phase 8B — per-item override автосписания. По умолчанию True. Если
    # ресторан включил tech_cards_enabled, но конкретное блюдо помечено
    # auto_consume=False — оно НЕ списывает ингредиенты при close_order.
    auto_consume = models.BooleanField(
        default=True,
        help_text="Списывать по техкарте при close_order (выкл. = не списывать)",
    )

    # ── Заготовочное (партиями) ──────────────────────────────────────────
    is_batch_cooking = models.BooleanField(
        default=False,
        help_text="Готовится партиями (плов на 20 порций утром)",
    )
    prepared_qty = models.PositiveIntegerField(
        default=0,
        help_text="Сколько порций готово сейчас (для batch-блюд)",
    )
    low_stock_threshold = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Порог «заканчивается»: когда prepared_qty ≤ threshold "
                  "карточка подсвечивается оранжевым",
    )

    # ── Продажа на вес / штуки ──────────────────────────────────────────
    unit = models.CharField(
        max_length=8, choices=MenuItemUnit.choices,
        default=MenuItemUnit.PIECE,
        help_text="Единица продажи: штука / граммы / кг",
    )
    unit_size = models.PositiveIntegerField(
        default=1,
        help_text="Цена указана за N единиц: 1 шт / 100 г / 1 кг",
    )
    sale_step = models.PositiveIntegerField(
        default=0,
        help_text="Минимальный шаг продажи (50 г для весов; 0 = любой)",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "menu_items"
        ordering = ["category__sort_order", "sort_order", "name"]
        verbose_name = "Блюдо"
        verbose_name_plural = "Блюда"
        constraints = [
            # Покупной товар не может одновременно быть заготовочным
            models.CheckConstraint(
                condition=(
                    ~(models.Q(is_purchased=True) & models.Q(is_batch_cooking=True))
                ),
                name="menuitem_not_purchased_and_batch",
            ),
            # unit_size ≥ 1 всегда
            models.CheckConstraint(
                condition=models.Q(unit_size__gte=1),
                name="menuitem_unit_size_ge_1",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_low_stock(self) -> bool:
        """True если batch-блюдо подходит к концу — для оранжевой подсветки."""
        if not self.is_batch_cooking:
            return False
        threshold = self.low_stock_threshold or 5
        return self.prepared_qty <= threshold


class MenuItemTechCardLine(models.Model):
    """Строка техкарты блюда — что и сколько идёт на 1 единицу продажи.

    Пример «Манты» (1 порция):
      Фарш (semi) 0.100 кг
      Тесто (semi) 0.050 кг
      Соль (ingredient) 0.002 кг

    XOR между ingredient и nested_semi: ровно один компонент.
    qty_per_unit — за 1 единицу `menu_item` (unit/unit_size система используется
    для отображения цены, но техкарта работает в единицах ingredient/semi).

    При close_order сервис `consume_for_order_close` спишет
    qty_per_unit × order_item.qty по каждой строке техкарты.
    """

    menu_item = models.ForeignKey(
        "menu.MenuItem", on_delete=models.CASCADE,
        related_name="tech_card_lines",
    )
    ingredient = models.ForeignKey(
        "inventory.Ingredient", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
        help_text="Сырой ингредиент (XOR с nested_semi)",
    )
    nested_semi = models.ForeignKey(
        "inventory.SemiFinishedType", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
        help_text="Полуфабрикат (XOR с ingredient)",
    )
    qty_per_unit = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text="Сколько единиц компонента на 1 порцию блюда",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "menu_tech_card_lines"
        ordering = ["menu_item", "sort_order"]
        verbose_name = "Строка техкарты"
        verbose_name_plural = "Строки техкарт"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ingredient__isnull=False, nested_semi__isnull=True)
                    | models.Q(ingredient__isnull=True, nested_semi__isnull=False)
                ),
                name="techcard_line_one_component_only",
            ),
            models.CheckConstraint(
                condition=models.Q(qty_per_unit__gt=0),
                name="techcard_qty_positive",
            ),
        ]

    def __str__(self) -> str:
        comp = self.ingredient or self.nested_semi
        return f"{self.menu_item.name} ← {self.qty_per_unit} × {comp.name if comp else '?'}"


class BatchCookingKind(models.TextChoices):
    """Тип события для лога заготовочных блюд (Phase 7E)."""

    COOK = "cook", "Заготовка"            # cook нажал «+N порций»
    CONSUME = "consume", "Расход"          # close_order списал N порций
    CORRECT = "correct", "Корректировка"   # manager выровнял prepared_qty вручную


class BatchCookingLog(models.Model):
    """История изменений prepared_qty для batch-блюд (Phase 7E).

    `prepared_qty` на MenuItem — денормализованный счётчик (быстрый
    доступ из MenuScreen для подсветки low-stock). История —
    в этой таблице (аудит «кто, сколько, когда заготовил/списал»).

    При close_order для каждого OrderItem с `is_batch_cooking=True`
    создаётся запись с `kind=CONSUME` и `qty_delta = -qty`. Для cook'а —
    кнопка «+N порций» → запись с `kind=COOK` и `qty_delta = +N`.
    """

    menu_item = models.ForeignKey(
        "menu.MenuItem", on_delete=models.CASCADE,
        related_name="batch_logs",
    )
    qty_delta = models.IntegerField(
        help_text="+N при заготовке, -N при расходе (всегда != 0)",
    )
    new_total = models.PositiveIntegerField(
        help_text="prepared_qty ПОСЛЕ применения qty_delta (clamped to ≥ 0)",
    )
    kind = models.CharField(
        max_length=12, choices=BatchCookingKind.choices,
    )
    user = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "menu_batch_cooking_log"
        ordering = ["-created_at"]
        verbose_name = "Лог заготовки"
        verbose_name_plural = "Логи заготовки"
        indexes = [
            models.Index(fields=["menu_item", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(qty_delta=0),
                name="batch_log_qty_delta_nonzero",
            ),
        ]

    def __str__(self) -> str:
        sign = "+" if self.qty_delta > 0 else ""
        return f"{self.menu_item.name} {sign}{self.qty_delta} ({self.kind})"
