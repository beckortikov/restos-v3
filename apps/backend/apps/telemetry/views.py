"""Cloud-side endpoint приёма телеметрии от ресторанов.

POST /api/v1/telemetry/push/
Header: X-Restaurant-Key: <api_key>
Body: snapshot payload (см. collector.collect_telemetry)

Доступен ТОЛЬКО когда `SUPERADMIN_ENABLED=True` — это cloud.
На restaurant-инстансе вернёт 404 (не имеет смысла слать самому себе).
"""
from __future__ import annotations

from datetime import date

from django.conf import settings
from django.utils.dateparse import parse_datetime
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import Restaurant
from common.exceptions import BusinessError

from .models import RestaurantCatalogSnapshot, TelemetrySnapshot


def _authenticate_restaurant(request) -> Restaurant:
    """Общая аутентификация по X-Restaurant-Key для всех cloud-endpoints."""
    if not getattr(settings, "SUPERADMIN_ENABLED", False):
        raise BusinessError(
            "NOT_AVAILABLE",
            "Endpoint доступен только на vendor cloud", 404,
        )
    api_key = request.META.get("HTTP_X_RESTAURANT_KEY", "").strip()
    if not api_key:
        raise BusinessError(
            "AUTH_REQUIRED", "Требуется заголовок X-Restaurant-Key", 401,
        )
    try:
        return Restaurant.objects.get(api_key=api_key)
    except Restaurant.DoesNotExist as exc:
        raise BusinessError("AUTH_INVALID", "Неизвестный api_key", 401) from exc


class TelemetryPushView(APIView):
    """POST /api/v1/telemetry/push/ — cloud принимает snapshot."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Cloud-only gate
        if not getattr(settings, "SUPERADMIN_ENABLED", False):
            raise BusinessError(
                "NOT_AVAILABLE",
                "Endpoint доступен только на vendor cloud",
                404,
            )

        api_key = request.META.get("HTTP_X_RESTAURANT_KEY", "").strip()
        if not api_key:
            raise BusinessError(
                "AUTH_REQUIRED", "Требуется заголовок X-Restaurant-Key", 401,
            )
        try:
            restaurant = Restaurant.objects.get(api_key=api_key)
        except Restaurant.DoesNotExist as exc:
            raise BusinessError("AUTH_INVALID", "Неизвестный api_key", 401) from exc

        data = request.data
        try:
            bdate = date.fromisoformat(data["business_date"])
            captured_at = parse_datetime(data["captured_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BusinessError(
                "INVALID_VALUE", f"Неверный формат payload: {exc}", 400,
            ) from exc
        if captured_at is None:
            raise BusinessError("INVALID_VALUE", "captured_at — не дата", 400)

        last_order_at = None
        if data.get("last_order_at"):
            last_order_at = parse_datetime(data["last_order_at"])

        # Upsert: один snapshot/день/ресторан, обновляем при новом push'е.
        snap, _ = TelemetrySnapshot.objects.update_or_create(
            restaurant=restaurant,
            business_date=bdate,
            defaults={
                "captured_at": captured_at,
                "daily_revenue": data.get("daily_revenue") or "0",
                "daily_orders_count": int(data.get("daily_orders_count") or 0),
                "mtd_revenue": data.get("mtd_revenue") or "0",
                "last_order_at": last_order_at,
                "open_shifts_count": int(data.get("open_shifts_count") or 0),
                "app_version": (data.get("app_version") or "")[:32],
            },
        )

        # Попутно фиксируем heartbeat на ресторане
        from django.utils import timezone

        restaurant.last_heartbeat_at = timezone.now()
        ver = (data.get("app_version") or "")[:32]
        update_fields = ["last_heartbeat_at"]
        if ver:
            restaurant.app_version = ver
            update_fields.append("app_version")
        restaurant.save(update_fields=update_fields)

        return Response({
            "data": {
                "ok": True,
                "snapshot_id": snap.id,
                "received_at": snap.received_at.isoformat(),
            }
        })


class CatalogPushView(APIView):
    """POST /api/v1/telemetry/catalog/ — cloud принимает снимок меню."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        restaurant = _authenticate_restaurant(request)

        data = request.data
        if not isinstance(data, dict):
            raise BusinessError("INVALID_VALUE", "Body должен быть object", 400)

        totals = (data.get("totals") or {})
        snap, _ = RestaurantCatalogSnapshot.objects.update_or_create(
            restaurant=restaurant,
            defaults={
                "data": data,
                "categories_count": int(totals.get("categories") or 0),
                "items_count": int(totals.get("items") or 0),
                "active_items_count": int(totals.get("active_items") or 0),
            },
        )

        # Попутно фиксируем heartbeat
        from django.utils import timezone

        restaurant.last_heartbeat_at = timezone.now()
        restaurant.save(update_fields=["last_heartbeat_at"])

        # Если name ресторана в snapshot отличается — синхронизируем
        # (cloud — источник правды, но если на restaurant имя переименовали
        # и они захотели чтобы cloud это знал)
        snapshot_name = (data.get("restaurant") or {}).get("name")
        if snapshot_name and snapshot_name != restaurant.name:
            # Не перезаписываем безусловно — это вопрос политики vendor.
            # Просто логируем; имя меняется только через cloud admin.
            pass

        return Response({
            "data": {
                "ok": True,
                "categories": snap.categories_count,
                "items": snap.items_count,
                "active_items": snap.active_items_count,
                "updated_at": snap.updated_at.isoformat(),
            }
        })
