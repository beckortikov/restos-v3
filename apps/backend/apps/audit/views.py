"""Read-only API для журнала. Кассир видит свой ресторан, фильтрует по
action / user / диапазону дат. Запись в журнал — только из сервисов
(нет POST/PATCH/DELETE через API)."""
from rest_framework import mixins, viewsets
from rest_framework.response import Response

from common.pagination import StandardPagination
from common.permissions import IsCashier

from .models import AuditEntry
from .serializers import AuditEntrySerializer


class AuditEntryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditEntrySerializer
    permission_classes = [IsCashier]
    pagination_class = StandardPagination
    filterset_fields = ["action", "user", "target_type"]

    def get_queryset(self):
        qs = AuditEntry.objects.filter(
            restaurant=self.request.user.restaurant
        ).select_related("user")
        # Простые фильтры по дате через query params: ?from=YYYY-MM-DD&to=...
        date_from = self.request.query_params.get("from")
        date_to = self.request.query_params.get("to")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response({"data": ser.data, "meta": {"total": qs.count()}})
