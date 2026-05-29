"""Склад: ингредиенты + event-stream движений остатка.

Принцип: остаток (`current_qty`) — **производная** от истории движений,
не хранится напрямую. Это защита от рассинхрона: даже если кто-то отредактирует
DB напрямую, можно перевычислить остаток из movements.

Изменения остатка делаются ТОЛЬКО через создание `IngredientStockMovement`
(см. apps.inventory.services.record_movement).

Phase 7A — фундамент. Дальше:
- 7B: SemiFinishedType + Recipe + produce_semi (использует record_movement)
- 7C: TechCard + auto-consume при close_order
- 7D: POS UI накладные / инвентаризация / редактор техкарт
- 7E: BatchCookingLog
"""
from decimal import Decimal

from django.db import models


class IngredientUnit(models.TextChoices):
    """Единицы измерения ингредиентов. Жёстко зафиксированы — позволяет
    автоматически конвертировать в техкартах (1 кг = 1000 г)."""

    KG = "kg", "Килограмм"
    GRAM = "g", "Грамм"
    LITER = "l", "Литр"
    ML = "ml", "Миллилитр"
    PIECE = "piece", "Штука"
    PACK = "pack", "Упаковка"
    BOTTLE = "bottle", "Бутылка"


class Ingredient(models.Model):
    """Сырьё для приготовления блюд.

    Примеры: «Говядина», «Мука пшеничная», «Кока-Кола 0.5л» (для покупных).
    `current_qty` — read-only property, вычисляется из movements.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="ingredients",
    )
    name = models.CharField(max_length=128)
    unit = models.CharField(
        max_length=12, choices=IngredientUnit.choices,
        default=IngredientUnit.GRAM,
    )
    # Стоимость закупки за единицу (для расчёта cogs блюда по техкарте).
    # При приёмке по разной цене — обновляется как weighted average
    # (или храним FIFO — Phase 7B можно расширить).
    avg_cost_per_unit = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0"),
        help_text="Средневзвешенная закупочная цена за 1 unit",
    )
    # Порог «заканчивается» — для напоминаний в UI / алертов.
    low_stock_threshold = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True,
        help_text="Когда current_qty ≤ threshold — карточка подсвечивается",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    # Phase 8A — флаг «продукт vs хозтовар». is_food=True → еда (используется в
    # техкартах). is_food=False → хозтовар (туалетная бумага, мыло, упаковка) —
    # не используется в техкартах, но учитывается на складе через
    # `SupplyExpense` (выдача в зал/на кухню).
    is_food = models.BooleanField(
        default=True, db_index=True,
        help_text="True = продукт, False = хозтовар (упаковка, моющие, и т.п.)",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingredients"
        ordering = ["sort_order", "name"]
        unique_together = [("restaurant", "name")]
        verbose_name = "Ингредиент"
        verbose_name_plural = "Ингредиенты"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_unit_display()})"

    @property
    def current_qty(self) -> Decimal:
        """Текущий остаток = сумма всех qty_delta движений.

        Вычисляется по запросу. Для high-volume сценариев лучше кэшировать
        в Redis, но пока — на лету (хватает для 100-500 ингредиентов).
        """
        result = (
            self.movements.aggregate(total=models.Sum("qty_delta"))["total"]
            or Decimal("0")
        )
        return result

    @property
    def is_low_stock(self) -> bool:
        if self.low_stock_threshold is None:
            return False
        return self.current_qty <= self.low_stock_threshold


class SemiFinishedType(models.Model):
    """Тип полуфабриката — рецепт + текущий остаток.

    Примеры:
    - «Фарш говяжий» (kg) — выход 80% от сырья (потери при разделке)
    - «Тесто пельменное» (kg) — выход 95%
    - «Куриный бульон» (l) — выход 60% (выкипание)

    Используется в техкартах блюд (Phase 7C):
    «Манты» = 100г Фарш + 50г Тесто + 2г Соль.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE,
        related_name="semi_finished_types",
    )
    name = models.CharField(max_length=128)
    output_unit = models.CharField(
        max_length=12, choices=IngredientUnit.choices,
        default=IngredientUnit.KG,
        help_text="Единица готового полуфабриката",
    )
    yield_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("100"),
        help_text="Выход %: 100=идеально, 80=20%% потерь от сырья",
    )
    avg_cost_per_unit = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0"),
        help_text="Средневзвешенная себестоимость 1 unit готового п/ф",
    )
    low_stock_threshold = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "semi_finished_types"
        ordering = ["sort_order", "name"]
        unique_together = [("restaurant", "name")]
        verbose_name = "Полуфабрикат"
        verbose_name_plural = "Полуфабрикаты"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_output_unit_display()})"

    @property
    def current_qty(self) -> Decimal:
        return (
            self.movements.aggregate(total=models.Sum("qty_delta"))["total"]
            or Decimal("0")
        )

    @property
    def is_low_stock(self) -> bool:
        if self.low_stock_threshold is None:
            return False
        return self.current_qty <= self.low_stock_threshold


class SemiFinishedRecipeLine(models.Model):
    """Строка рецепта: что и сколько кладём в 1 единицу выхода полуфабриката.

    Для «Фарш говяжий» (1 кг готового, yield 80%):
      Говядина 1.25 кг (с учётом потерь — produce_semi сам умножит)
      Лук 0.1 кг
      Соль 0.015 кг

    `qty_per_output` — за 1 единицу `semi_type.output_unit`. Service
    `produce_semi(qty)` умножает на qty. Если `yield_percent < 100` —
    дополнительно делит на yield_percent/100 (т.е. сырья тратится больше).
    """

    semi_type = models.ForeignKey(
        SemiFinishedType, on_delete=models.CASCADE,
        related_name="recipe_lines",
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="+",
        null=True, blank=True,
        help_text="Сырой ингредиент (XOR с nested_semi)",
    )
    nested_semi = models.ForeignKey(
        SemiFinishedType, on_delete=models.PROTECT, related_name="+",
        null=True, blank=True,
        help_text="Другой п/ф (для рецептов «п/ф из п/ф»)",
    )
    qty_per_output = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text="Сколько единиц компонента на 1 unit выхода п/ф",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "semi_recipe_lines"
        ordering = ["semi_type", "sort_order"]
        verbose_name = "Строка рецепта"
        verbose_name_plural = "Строки рецептов"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ingredient__isnull=False, nested_semi__isnull=True)
                    | models.Q(ingredient__isnull=True, nested_semi__isnull=False)
                ),
                name="recipe_line_one_component_only",
            ),
        ]

    def __str__(self) -> str:
        c = self.ingredient or self.nested_semi
        name = c.name if c else "?"
        return f"{self.semi_type.name} ← {self.qty_per_output} × {name}"


class SemiStockMovementKind(models.TextChoices):
    PRODUCE = "produce", "Произведено (варка партии)"
    CONSUME_FOR_DISH = "consume_for_dish", "Расход в блюде"
    WASTE = "waste", "Списание"
    INVENTORY_CORRECT = "inventory_correct", "Корректировка инвентаризацией"


class SemiFinishedStockMovement(models.Model):
    """Event в истории остатков полуфабриката (append-only)."""

    semi_type = models.ForeignKey(
        SemiFinishedType, on_delete=models.CASCADE, related_name="movements",
    )
    kind = models.CharField(
        max_length=24, choices=SemiStockMovementKind.choices, db_index=True,
    )
    qty_delta = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Себестоимость 1 unit этой партии (только produce)",
    )
    reason = models.CharField(max_length=255, blank=True)
    user = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "semi_stock_movements"
        ordering = ["-created_at", "-id"]
        verbose_name = "Движение п/ф"
        verbose_name_plural = "Движения п/ф"
        indexes = [
            models.Index(fields=["semi_type", "created_at"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.qty_delta >= 0 else ""
        return f"{self.semi_type.name} {sign}{self.qty_delta} ({self.kind})"


class StockMovementKind(models.TextChoices):
    """Типы движений остатка ингредиентов.

    Знак `qty_delta` определяется типом:
    - purchase / return_from_use / inventory_increase → положительный
    - consume / waste / produce_semi / return_to_supplier / inventory_decrease → отрицательный
    """

    PURCHASE = "purchase", "Приёмка (накладная)"
    CONSUME = "consume", "Расход при заказе"
    PRODUCE_SEMI = "produce_semi", "Расход при варке полуфабриката"
    WASTE = "waste", "Списание (порча, бой)"
    INVENTORY_CORRECT = "inventory_correct", "Корректировка инвентаризацией"
    RETURN_TO_SUPPLIER = "return_to_supplier", "Возврат поставщику"
    MANUAL = "manual", "Ручная корректировка"


class IngredientStockMovement(models.Model):
    """Event в истории движений ингредиента. Append-only.

    Изменение остатка делается **только** через создание этой записи —
    никаких прямых UPDATE по qty. Гарантирует полную аудируемость
    и возможность пересчёта остатка с нуля.

    `qty_delta` — знаковая величина в `Ingredient.unit`. Положительная
    для приёмок/возвратов от использования, отрицательная для расходов.
    """

    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.CASCADE, related_name="movements",
    )
    kind = models.CharField(
        max_length=24, choices=StockMovementKind.choices, db_index=True,
    )
    qty_delta = models.DecimalField(
        max_digits=14, decimal_places=3,
        help_text="Знаковая величина в единицах ингредиента. >0 приход, <0 расход.",
    )
    # Закупочная цена в этом конкретном движении (только для purchase) —
    # используется для пересчёта Ingredient.avg_cost_per_unit как weighted avg.
    unit_cost = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Цена за единицу в этой партии (только для purchase)",
    )
    reason = models.CharField(
        max_length=255, blank=True,
        help_text="Свободная причина: «накладная #4521», «истёк срок», и т.д.",
    )
    # Кто провёл операцию (нужно для аудита).
    user = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    # Ссылка на заказ (только для kind=consume).
    order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ingredient_stock_movements"
        ordering = ["-created_at", "-id"]
        verbose_name = "Движение остатка"
        verbose_name_plural = "Движения остатков"
        indexes = [
            models.Index(fields=["ingredient", "created_at"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.qty_delta >= 0 else ""
        return f"{self.ingredient.name} {sign}{self.qty_delta} ({self.kind})"


# ─── Phase 8A — Поставщики, накладные, списания, расход, инвентаризация ──────


class Supplier(models.Model):
    """Поставщик ингредиентов и хозтоваров.

    Один поставщик принадлежит одному ресторану (multi-tenant). Между
    ресторанами не шарится — у каждого свой ИП «Бахром» с разными условиями.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="suppliers",
    )
    name = models.CharField(max_length=128)
    phone = models.CharField(max_length=32, blank=True, default="")
    contact_person = models.CharField(max_length=128, blank=True, default="")
    note = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_suppliers"
        ordering = ["sort_order", "name"]
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"
        indexes = [models.Index(fields=["restaurant", "is_active"])]

    def __str__(self) -> str:
        return self.name


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    APPLIED = "applied", "Проведён"


class StockReceipt(models.Model):
    """Накладная от поставщика. В статусе DRAFT можно редактировать, при
    переводе в APPLIED — атомарно создаём stock movements для всех линий.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="stock_receipts",
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="receipts",
        null=True, blank=True,
    )
    receipt_date = models.DateField()
    number = models.CharField(
        max_length=64, blank=True, default="",
        help_text="Номер накладной (по документу поставщика)",
    )
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Сумма по накладной (по сумме линий, авто-обновляется)",
    )
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT, db_index=True,
    )
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_stock_receipts"
        ordering = ["-receipt_date", "-id"]
        verbose_name = "Накладная"
        verbose_name_plural = "Накладные"
        indexes = [
            models.Index(fields=["restaurant", "-receipt_date"]),
            models.Index(fields=["restaurant", "status"]),
        ]

    def __str__(self) -> str:
        return f"Накладная #{self.id} от {self.receipt_date}"


class StockReceiptLine(models.Model):
    receipt = models.ForeignKey(
        StockReceipt, on_delete=models.CASCADE, related_name="lines",
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="+",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "inventory_stock_receipt_lines"
        ordering = ["receipt", "id"]


class WriteoffReason(models.TextChoices):
    SPOILAGE = "spoilage", "Порча"
    BREAKAGE = "breakage", "Бой/поломка"
    EXPIRED = "expired", "Просрочка"
    TASTING = "tasting", "Дегустация"
    OTHER = "other", "Прочее"


class StockWriteoff(models.Model):
    """Документ списания со склада (партия позиций с одной причиной)."""

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="stock_writeoffs",
    )
    writeoff_date = models.DateField()
    reason = models.CharField(
        max_length=12, choices=WriteoffReason.choices,
        default=WriteoffReason.SPOILAGE,
    )
    note = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT, db_index=True,
    )
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_stock_writeoffs"
        ordering = ["-writeoff_date", "-id"]
        verbose_name = "Списание"
        verbose_name_plural = "Списания"
        indexes = [
            models.Index(fields=["restaurant", "-writeoff_date"]),
            models.Index(fields=["restaurant", "status"]),
        ]

    def __str__(self) -> str:
        return f"Списание #{self.id} от {self.writeoff_date}"


class StockWriteoffLine(models.Model):
    writeoff = models.ForeignKey(
        StockWriteoff, on_delete=models.CASCADE, related_name="lines",
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="+",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        db_table = "inventory_stock_writeoff_lines"


class SupplyExpenseReason(models.TextChoices):
    TO_HALL = "to_hall", "Выдано в зал"
    TO_KITCHEN = "to_kitchen", "Выдано на кухню"
    TO_BAR = "to_bar", "Выдано в бар"
    HOUSEHOLD = "household", "Хозяйственные нужды"
    SPOILAGE = "spoilage", "Порча/негодное"
    OTHER = "other", "Прочее"


class SupplyExpense(models.Model):
    """Расход хозтоваров: «выдано N штук X на кухню».

    Отдельная сущность от StockWriteoff, потому что это не списание потерь,
    а **учёт расхода** (для food-cost vs household-cost разделения).
    Создаёт CONSUME-движение, но с reason='supply_<reason>'.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="supply_expenses",
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="+",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(
        max_length=12, choices=SupplyExpenseReason.choices,
        default=SupplyExpenseReason.HOUSEHOLD,
    )
    note = models.CharField(max_length=255, blank=True, default="")
    user = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_supply_expenses"
        ordering = ["-created_at", "-id"]
        verbose_name = "Расход хозтовара"
        verbose_name_plural = "Расходы хозтоваров"
        indexes = [
            models.Index(fields=["restaurant", "-created_at"]),
            models.Index(fields=["ingredient", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.ingredient.name}: -{self.qty} ({self.reason})"


class InventoryCheck(models.Model):
    """Инвентаризация склада. В DRAFT заполняем `actual_qty` по каждой позиции,
    при APPLIED — расхождения (`actual - expected`) проводятся как
    INVENTORY_CORRECT-движения.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="inventory_checks",
    )
    check_date = models.DateField()
    is_food = models.BooleanField(
        null=True, blank=True,
        help_text="True = продукты, False = хозтовары, null = смешано",
    )
    note = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT, db_index=True,
    )
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_checks"
        ordering = ["-check_date", "-id"]
        verbose_name = "Инвентаризация"
        verbose_name_plural = "Инвентаризации"
        indexes = [
            models.Index(fields=["restaurant", "-check_date"]),
            models.Index(fields=["restaurant", "status"]),
        ]

    def __str__(self) -> str:
        return f"Инвентаризация #{self.id} от {self.check_date}"


class InventoryCheckLine(models.Model):
    inventory_check = models.ForeignKey(
        InventoryCheck, on_delete=models.CASCADE, related_name="lines",
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.PROTECT, related_name="+",
    )
    expected_qty = models.DecimalField(max_digits=14, decimal_places=3)
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        db_table = "inventory_check_lines"
        ordering = ["inventory_check", "id"]

    @property
    def diff(self):
        return self.actual_qty - self.expected_qty
