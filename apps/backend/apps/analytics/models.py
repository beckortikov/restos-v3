"""Phase 7 — Аналитика: snapshots для исторической фиксации."""
from __future__ import annotations

from decimal import Decimal

from django.db import models


class AbcKind(models.TextChoices):
    MENU = "menu", "Меню"
    INVENTORY = "inventory", "Склад"


class AbcSnapshot(models.Model):
    """Снимок ABC-анализа на конкретный период.

    Создаётся вручную (менеджером) или cron'ом (раз в неделю/месяц).
    `lines` — детализация по позициям.
    """

    restaurant = models.ForeignKey(
        "users.Restaurant", on_delete=models.CASCADE, related_name="abc_snapshots",
    )
    kind = models.CharField(
        max_length=12, choices=AbcKind.choices, default=AbcKind.MENU,
    )
    period_from = models.DateField()
    period_to = models.DateField()
    total_revenue = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
    )
    total_cogs = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
    )
    total_margin = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
    )
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_abc_snapshots"
        ordering = ["-created_at"]
        verbose_name = "ABC-снимок"
        verbose_name_plural = "ABC-снимки"
        indexes = [
            models.Index(fields=["restaurant", "kind", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.period_from}..{self.period_to} (R{self.restaurant_id})"


class AbcSnapshotLine(models.Model):
    """Одна позиция ABC-снимка (menu_item или ingredient)."""

    snapshot = models.ForeignKey(
        AbcSnapshot, on_delete=models.CASCADE, related_name="lines",
    )
    # XOR: одна из двух ссылок (для menu kind — menu_item, inventory — ingredient).
    menu_item = models.ForeignKey(
        "menu.MenuItem", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    ingredient = models.ForeignKey(
        "inventory.Ingredient", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    name_snapshot = models.CharField(max_length=255)
    qty_sold = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    cogs = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    margin = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    revenue_share_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0"),
        help_text="Доля от total_revenue, 0..100",
    )
    cumulative_share_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0"),
    )
    abc_class = models.CharField(max_length=1, default="C")  # A / B / C
    rank = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "analytics_abc_snapshot_lines"
        ordering = ["snapshot", "rank"]
        verbose_name = "Строка ABC-снимка"
        verbose_name_plural = "Строки ABC-снимков"

    def __str__(self) -> str:
        return f"{self.name_snapshot}: {self.abc_class} ({self.revenue})"
