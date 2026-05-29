"""Super-Admin API endpoints.

Все эндпоинты под `/api/v1/superadmin/`. Auth — JWT (Authorization: SA <token>).
Login через POST /superadmin/auth/login/ возвращает токен + expires_at.
"""
from __future__ import annotations

from django.contrib.auth import authenticate
from rest_framework import permissions, status as drf_status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.licensing.models import License, LicensePlan
from apps.users.models import Restaurant
from common.exceptions import BusinessError

from .auth import SuperAdminJWTAuthentication, issue_token
from .permissions import IsSuperAdmin
from .serializers import (
    BlockLicenseSerializer,
    ChangePlanSerializer,
    ExtendLicenseSerializer,
    LicenseSerializer,
    RestaurantBriefSerializer,
    RestaurantCreateSerializer,
    SuperAdminLoginSerializer,
)
from .services import (
    block_license,
    change_plan,
    extend_license,
    platform_stats,
    restaurants_overview,
    unblock_license,
)


# -------- Auth --------


class SuperAdminLoginView(APIView):
    """POST /api/v1/superadmin/auth/login/ {username, password} → {token, expires_at}."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = SuperAdminLoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        user = authenticate(
            request,
            username=ser.validated_data["username"],
            password=ser.validated_data["password"],
        )
        if user is None or not user.is_active or not user.is_superuser:
            raise BusinessError(
                "AUTH_INVALID",
                "Неверные учётные данные или нет SA-привилегий",
                401,
            )
        token, exp = issue_token(user)
        return Response({
            "data": {
                "token": token,
                "expires_at": exp,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                },
            }
        })


# -------- Helpers --------


def _get_restaurant(pk) -> Restaurant:
    try:
        return Restaurant.objects.get(id=int(pk))
    except (Restaurant.DoesNotExist, ValueError, TypeError) as exc:
        raise BusinessError("NOT_FOUND", "Ресторан не найден", 404) from exc


def _get_license_for(restaurant: Restaurant) -> License:
    try:
        return restaurant.license
    except License.DoesNotExist as exc:
        raise BusinessError(
            "NOT_FOUND", "Лицензия не найдена для ресторана", 404,
        ) from exc


# -------- Restaurants --------


@api_view(["GET"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def list_restaurants(request):
    """GET /api/v1/superadmin/restaurants/ — список с краткой инфой и метриками."""
    return Response({"data": restaurants_overview()})


@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def create_restaurant(request):
    """POST /api/v1/superadmin/restaurants/ — создать ресторан (триал авто)."""
    ser = RestaurantCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    r = ser.save()  # signals выдадут License + дефолтные справочники
    return Response(
        {"data": RestaurantBriefSerializer(r).data},
        status=drf_status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def restaurant_detail(request, pk):
    r = _get_restaurant(pk)
    if request.method == "GET":
        return Response({"data": RestaurantBriefSerializer(r).data})
    # PATCH
    allowed = {"name", "address", "phone", "currency"}
    for field in list(request.data):
        if field not in allowed:
            raise BusinessError(
                "INVALID_VALUE",
                f"Поле {field!r} не редактируется через SA",
                400,
            )
    for field in allowed & set(request.data):
        setattr(r, field, request.data[field])
    r.save()
    return Response({"data": RestaurantBriefSerializer(r).data})


# -------- License operations --------


@api_view(["GET"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def license_detail(request, pk):
    r = _get_restaurant(pk)
    lic = _get_license_for(r)
    return Response({"data": LicenseSerializer(lic).data})


@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def license_extend(request, pk):
    r = _get_restaurant(pk)
    lic = _get_license_for(r)
    ser = ExtendLicenseSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    lic = extend_license(license_obj=lic, days=ser.validated_data["days"])
    return Response({"data": LicenseSerializer(lic).data})


@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def license_change_plan(request, pk):
    r = _get_restaurant(pk)
    lic = _get_license_for(r)
    ser = ChangePlanSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    lic = change_plan(license_obj=lic, plan=ser.validated_data["plan"])
    return Response({"data": LicenseSerializer(lic).data})


@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def license_block(request, pk):
    r = _get_restaurant(pk)
    lic = _get_license_for(r)
    ser = BlockLicenseSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    lic = block_license(license_obj=lic, reason=ser.validated_data["reason"])
    return Response({"data": LicenseSerializer(lic).data})


@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def license_unblock(request, pk):
    r = _get_restaurant(pk)
    lic = _get_license_for(r)
    lic = unblock_license(license_obj=lic)
    return Response({"data": LicenseSerializer(lic).data})


# -------- Stats --------


@api_view(["GET"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def stats(request):
    return Response({"data": platform_stats()})
