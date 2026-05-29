"""Phase 6 API: табель + расчёт зарплат."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.exceptions import BusinessError

from .models import PayrollPeriod, TimeEntry, TimeEntryStatus
from .serializers import PayrollPeriodSerializer, TimeEntrySerializer
from .services import (
    calculate_period,
    clock_in as svc_clock_in,
    clock_out as svc_clock_out,
    finalize_period,
    pay_period,
)


class TimeEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """Список записей табеля. Manager видит все, обычный user — только свои."""

    serializer_class = TimeEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = TimeEntry.objects.filter(restaurant=u.restaurant).select_related("user")
        # Фильтры
        user_id = self.request.query_params.get("user_id")
        status_param = self.request.query_params.get("status")
        date_from = self.request.query_params.get("from")
        date_to = self.request.query_params.get("to")
        if user_id:
            qs = qs.filter(user_id=user_id)
        if status_param:
            qs = qs.filter(status=status_param)
        if date_from:
            qs = qs.filter(clock_in__date__gte=date_from)
        if date_to:
            qs = qs.filter(clock_in__date__lte=date_to)
        # Не-manager видит только свои
        is_manager = (
            u.role == "manager" or u.is_staff
            or u.role == "cashier"  # cashier в MVP тоже — без отдельной роли manager
        )
        if not is_manager:
            qs = qs.filter(user=u)
        return qs.order_by("-clock_in")

    @action(detail=False, methods=["post"], url_path="clock_in")
    def clock_in(self, request):
        """POST /payroll/time/clock_in/ — открыть свою смену."""
        note = (request.data.get("note") or "").strip()
        entry = svc_clock_in(
            user=request.user, restaurant=request.user.restaurant, note=note,
        )
        return Response(
            {"data": TimeEntrySerializer(entry).data},
            status=http_status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="clock_out")
    def clock_out(self, request):
        """POST /payroll/time/clock_out/ — закрыть свою последнюю смену."""
        note = (request.data.get("note") or "").strip()
        entry = svc_clock_out(
            user=request.user, restaurant=request.user.restaurant, note=note,
        )
        return Response({"data": TimeEntrySerializer(entry).data})

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request):
        """GET /payroll/time/current/ — открыта ли у меня сейчас смена?"""
        entry = TimeEntry.objects.filter(
            user=request.user, restaurant=request.user.restaurant,
            status=TimeEntryStatus.OPEN,
        ).order_by("-clock_in").first()
        if entry is None:
            return Response({"data": None})
        return Response({"data": TimeEntrySerializer(entry).data})


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise BusinessError("INVALID_VALUE", f"Дата должна быть YYYY-MM-DD: {s}", 400)


def _parse_decimal(v) -> Decimal:
    if v in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        raise BusinessError("INVALID_VALUE", f"Число некорректно: {v}", 400)


class PayrollPeriodViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PayrollPeriodSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = PayrollPeriod.objects.filter(restaurant=u.restaurant).select_related("user")
        user_id = self.request.query_params.get("user_id")
        status_param = self.request.query_params.get("status")
        if user_id:
            qs = qs.filter(user_id=user_id)
        if status_param:
            qs = qs.filter(status=status_param)
        # Не-manager видит только свои
        is_manager = (
            u.role == "manager" or u.is_staff or u.role == "cashier"
        )
        if not is_manager:
            qs = qs.filter(user=u)
        return qs.order_by("-period_start")

    @action(detail=False, methods=["post"], url_path="calculate")
    def calculate(self, request):
        """POST /payroll/periods/calculate/ {user_id, from, to, bonuses?, deductions?}."""
        from apps.users.models import User

        user_id = request.data.get("user_id")
        if user_id is None:
            raise BusinessError("INVALID_VALUE", "user_id обязателен", 400)
        target = get_object_or_404(
            User, id=user_id, restaurant=request.user.restaurant,
        )
        start = _parse_date(request.data.get("from") or request.data.get("period_start"))
        end = _parse_date(request.data.get("to") or request.data.get("period_end"))
        if start is None or end is None:
            raise BusinessError("INVALID_VALUE", "from/to обязательны (YYYY-MM-DD)", 400)
        bonuses = _parse_decimal(request.data.get("bonuses"))
        deductions = _parse_decimal(request.data.get("deductions"))
        note = (request.data.get("note") or "").strip()

        period = calculate_period(
            user=target,
            restaurant=request.user.restaurant,
            period_start=start, period_end=end,
            bonuses=bonuses, deductions=deductions, note=note,
        )
        return Response(
            {"data": PayrollPeriodSerializer(period).data},
            status=http_status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="finalize")
    def finalize(self, request, pk=None):
        period = self.get_object()
        finalize_period(period=period)
        return Response({"data": PayrollPeriodSerializer(period).data})

    @action(detail=True, methods=["post"], url_path="pay")
    def pay(self, request, pk=None):
        period = self.get_object()
        paid_op = request.data.get("paid_operation_id")
        pay_period(period=period, paid_operation_id=paid_op)
        return Response({"data": PayrollPeriodSerializer(period).data})
