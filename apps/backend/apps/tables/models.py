from django.db import models


class TableStatus(models.TextChoices):
    FREE = "free", "Свободен"
    OCCUPIED = "occupied", "Занят"
    BILL_REQUESTED = "bill_requested", "Счёт"
    MERGED = "merged", "Объединён"


class Zone(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="zones"
    )
    name = models.CharField(max_length=64)
    sort_order = models.PositiveSmallIntegerField(default=0)
    # Soft-delete: зона с архивированными столами (или с историческими
    # заказами через FK Table → Zone PROTECT) не удаляется физически.
    # Помечается is_archived=True — пропадает из UI карты зала и табов.
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "zones"
        ordering = ["sort_order", "name"]
        verbose_name = "Зона"
        verbose_name_plural = "Зоны"

    def __str__(self) -> str:
        return self.name


class Table(models.Model):
    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="tables"
    )
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="tables")
    number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=64)
    capacity = models.PositiveSmallIntegerField(default=2)
    status = models.CharField(
        max_length=16,
        choices=TableStatus.choices,
        default=TableStatus.FREE,
        db_index=True,
    )
    waiter = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    current_order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    guests_count = models.PositiveSmallIntegerField(default=0)
    opened_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    # Soft-delete: стол с историческими заказами нельзя физически удалить
    # (Order.table on_delete=PROTECT — нужно сохранять привязку для отчётов
    # и истории). Вместо этого помечаем is_archived=True — стол пропадает
    # из карты зала, но в OrderHistory/reports остаётся видимым.
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tables"
        ordering = ["zone__sort_order", "number"]
        # Номер уникален per-zone: Зал-1 и Веранда-1 — разные столы.
        # Архивированные исключены — иначе нельзя пересоздать стол с
        # тем же номером после soft-delete (нарушение unique).
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "number"],
                condition=models.Q(is_archived=False),
                name="unique_zone_number_active",
            ),
        ]
        verbose_name = "Стол"
        verbose_name_plural = "Столы"

    # Объединение столов (Phase 8) — все столы в одной группе обслуживаются
    # как один: «главный» (с наименьшим id) хранит current_order, остальные
    # переходят в статус MERGED. UI показывает «5+6» на главном.
    group = models.ForeignKey(
        "tables.TableGroup",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="tables",
    )

    def __str__(self) -> str:
        return f"{self.zone.name} / {self.name}"


class TableGroup(models.Model):
    """Объединённая группа столов — для большой компании, которой нужно
    несколько столов рядом. Один из столов — «главный» (наименьший id или
    explicit primary), он держит current_order. Остальные становятся MERGED.

    После закрытия заказа группа разъединяется (`close_table_group`):
    столы возвращаются в FREE, group=None, group.closed_at заполняется.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="table_groups"
    )
    name = models.CharField(
        max_length=64, blank=True,
        help_text="Опциональное имя группы; если пусто — UI генерирует «5+6»",
    )
    primary_table = models.ForeignKey(
        Table, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="primary_in_groups",
        help_text="Стол, на котором висит current_order группы.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        db_table = "table_groups"
        ordering = ["-created_at"]
        verbose_name = "Группа столов"
        verbose_name_plural = "Группы столов"

    def __str__(self) -> str:
        names = ", ".join(
            t.name for t in self.tables.all().order_by("number")
        )
        return f"Группа [{names}]"
