from rest_framework import serializers

from .models import Table, TableGroup, Zone


class ZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zone
        fields = ["id", "name", "sort_order"]


class TableGroupBriefSerializer(serializers.ModelSerializer):
    """Краткая информация о группе для встраивания в TableSerializer."""

    table_names = serializers.SerializerMethodField()
    table_ids = serializers.SerializerMethodField()

    class Meta:
        model = TableGroup
        fields = [
            "id", "name", "primary_table",
            "table_ids", "table_names",
        ]

    def get_table_names(self, obj: TableGroup) -> list[str]:
        return [t.name for t in obj.tables.all().order_by("number")]

    def get_table_ids(self, obj: TableGroup) -> list[int]:
        return list(obj.tables.all().order_by("number").values_list("id", flat=True))


class TableSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True)
    waiter_name = serializers.CharField(source="waiter.full_name", read_only=True, default=None)
    current_order = serializers.IntegerField(source="current_order_id", read_only=True)
    group = TableGroupBriefSerializer(read_only=True)
    next_reservation = serializers.SerializerMethodField()
    active_orders = serializers.SerializerMethodField()
    # Локализованная подпись статуса — фронт не маппит сам.
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    def validate(self, attrs: dict) -> dict:
        """Cross-restaurant изоляция + уникальность number в ресторане."""
        request = self.context.get("request")
        if request is None or not getattr(request.user, "restaurant_id", None):
            return attrs
        rid = request.user.restaurant_id
        zone = attrs.get("zone")
        if zone is not None and getattr(zone, "restaurant_id", None) != rid:
            raise serializers.ValidationError(
                {"zone": "Зона не принадлежит вашему ресторану"}
            )
        waiter = attrs.get("waiter")
        if waiter is not None and getattr(waiter, "restaurant_id", None) != rid:
            raise serializers.ValidationError(
                {"waiter": "Пользователь не принадлежит вашему ресторану"}
            )
        # Уникальность number в пределах ЗОНЫ (DB-level partial unique,
        # дублируем тут для чистого 400 ответа вместо IntegrityError).
        # Архивированные столы исключаются — освободив номер архивацией
        # стола, кассир должен иметь возможность создать новый с тем же №.
        number = attrs.get("number")
        target_zone = zone or (self.instance.zone if self.instance else None)
        if number is not None and target_zone is not None:
            qs = Table.objects.filter(
                zone=target_zone, number=number, is_archived=False,
            )
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    "number": f"Стол №{number} уже существует в зоне «{target_zone.name}»",
                })
        return attrs

    class Meta:
        model = Table
        fields = [
            "id",
            "number",
            "name",
            "capacity",
            "zone",
            "zone_name",
            "status",
            "status_display",
            "waiter",
            "waiter_name",
            "current_order",
            "guests_count",
            "opened_at",
            "group",
            "next_reservation",
            "active_orders",
            "updated_at",
        ]

    def get_active_orders(self, table) -> list[dict]:
        """Активные заказы (NEW/BILL_REQUESTED) на столе — для multi-group UI.

        Возвращает кратко: id, guests_count, total, waiter_name, status.
        Если на столе одна группа — список из 1 элемента.
        """
        from apps.orders.models import Order, OrderStatus

        qs = (
            Order.objects.filter(
                table=table,
                status__in=(OrderStatus.NEW, OrderStatus.BILL_REQUESTED),
            )
            .select_related("waiter")
            .order_by("created_at")
        )
        out: list[dict] = []
        for o in qs:
            out.append({
                "id": o.id,
                "guests_count": o.guests_count,
                "total": str(o.total),
                "waiter_name": o.waiter.full_name if o.waiter else None,
                "status": o.status,
            })
        return out

    def get_next_reservation(self, table) -> dict | None:
        """Ближайшая активная (pending/confirmed) резервация в окне +24ч,
        для бейджа «Резерв 19:30» на TableCard.

        Окно — сутки, чтобы кассир видел бронь, забронированную утром на вечер
        (типичный сценарий: 09:00 звонит клиент, бронирует на 19:00).
        """
        from apps.reservations.services import active_reservations_for_table

        r = active_reservations_for_table(table, lookahead_min=24 * 60).first()
        if r is None:
            return None
        return {
            "id": r.id,
            "scheduled_at": r.scheduled_at.isoformat(),
            "customer_name": r.customer_name,
            "party_size": r.party_size,
            "status": r.status,
        }


class TableGroupSerializer(serializers.ModelSerializer):
    """Полный сериализатор для CRUD-эндпоинта групп."""

    table_names = serializers.SerializerMethodField()
    tables = serializers.SerializerMethodField()

    class Meta:
        model = TableGroup
        fields = [
            "id", "name", "primary_table",
            "tables", "table_names",
            "created_at", "closed_at",
        ]

    def get_table_names(self, obj: TableGroup) -> list[str]:
        return [t.name for t in obj.tables.all().order_by("number")]

    def get_tables(self, obj: TableGroup) -> list[int]:
        return list(obj.tables.all().order_by("number").values_list("id", flat=True))


class MergeTablesSerializer(serializers.Serializer):
    table_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=2,
    )
    name = serializers.CharField(required=False, allow_blank=True, default="")
