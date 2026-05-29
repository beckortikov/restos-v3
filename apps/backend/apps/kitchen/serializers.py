from rest_framework import serializers

from apps.orders.models import OrderItem


class KitchenItemSerializer(serializers.ModelSerializer):
    """OrderItem с denormalized полями для KDS-канбана."""

    order_id = serializers.IntegerField(read_only=True)
    table_name = serializers.CharField(
        source="order.table.name", read_only=True, default=None,
    )
    waiter_name = serializers.CharField(
        source="order.waiter.full_name", read_only=True, default=None,
    )
    category_name = serializers.CharField(
        source="menu_item.category.name", read_only=True, default="",
    )
    station_name = serializers.CharField(
        source="menu_item.category.print_station.name",
        read_only=True, default=None,
    )
    order_type = serializers.CharField(
        source="order.order_type", read_only=True, default="hall",
    )
    customer_name = serializers.CharField(
        source="order.customer_name", read_only=True, default="",
    )

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "order_id",
            "table_name",
            "waiter_name",
            "category_name",
            "station_name",
            "order_type",
            "customer_name",
            "name_at_order",
            "qty",
            "note",
            "kitchen_status",
            "started_cooking_at",
            "ready_at",
            "served_at",
            "created_at",
        ]
