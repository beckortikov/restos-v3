from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.exceptions import BusinessError
from common.permissions import IsCashier

from .models import Printer, PrintJob, PrintJobKind, PrintJobStatus
from .serializers import PrinterSerializer, PrintJobSerializer
from .services import WORKER_EVENT


class PrinterViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD по принтерам ресторана. Frame 18 — настройки."""

    serializer_class = PrinterSerializer
    permission_classes = [IsCashier]
    pagination_class = None

    def get_queryset(self):
        return Printer.objects.filter(restaurant=self.request.user.restaurant)

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {"data": PrinterSerializer(qs, many=True).data, "meta": {"total": qs.count()}}
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": PrinterSerializer(self.get_object()).data})

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        return Response({"data": ser.data}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"data": ser.data})

    @action(detail=True, methods=["post"], url_path="test_print")
    def test_print(self, request, pk=None):
        """Создаёт PrintJob с тестовым payload — для frame 18 кнопка «Тест печати»."""
        printer = self.get_object()
        payload = {
            "restaurant": {
                "name": printer.restaurant.name,
                "address": printer.restaurant.address,
                "phone": printer.restaurant.phone,
                "currency": printer.restaurant.currency,
            },
            "order": {
                "id": "TEST",
                "table": "ТЕСТ",
                "guests": 0,
                "waiter": request.user.full_name,
                "cashier": request.user.full_name,
                "closed_at": timezone.now().isoformat(),
                "payment_method": "cash",
                "total": "0.00",
            },
            "items": [
                {
                    "name": "Тестовая печать",
                    "qty": 1,
                    "price": "0.00",
                    "subtotal": "0.00",
                }
            ],
        }
        job = PrintJob.objects.create(
            restaurant=printer.restaurant,
            printer=printer,
            kind=PrintJobKind.GUEST_RECEIPT,
            payload=payload,
            scheduled_at=timezone.now(),
        )
        WORKER_EVENT.set()
        return Response(
            {"data": {"print_job": {"id": job.id, "status": job.status}}}
        )


class PrintJobViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet,
):
    serializer_class = PrintJobSerializer
    permission_classes = [IsCashier]

    def get_queryset(self):
        qs = PrintJob.objects.filter(
            restaurant=self.request.user.restaurant
        ).select_related("printer").order_by("-id")
        status_filter = self.request.query_params.get("status")
        kind_filter = self.request.query_params.get("kind")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if kind_filter:
            qs = qs.filter(kind=kind_filter)
        return qs

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": PrintJobSerializer(self.get_object()).data})

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()[:100]
        return Response({"data": PrintJobSerializer(qs, many=True).data})

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        """Текстовое превью чека — для journal-viewer'а в POS UI.

        Для virtual принтеров рендерим/читаем с диска, для физических —
        тоже рендерим тот же шаблон (даём кассиру возможность увидеть, что
        ушло на печать).
        """
        from pathlib import Path
        from django.conf import settings

        from .escpos_sender import _render_preview

        job = self.get_object()
        out_dir = Path(settings.PRINTER_OUTPUT_DIR)
        f = out_dir / f"{job.id}.txt"
        if f.exists():
            text = f.read_text(encoding="utf-8")
        else:
            text = _render_preview(job)
        return Response({"data": {"text": text, "job_id": job.id}})

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        job = self.get_object()
        if job.status == PrintJobStatus.DONE:
            return Response({"data": PrintJobSerializer(job).data})
        job.status = PrintJobStatus.PENDING
        job.scheduled_at = timezone.now()
        job.error = ""
        job.save(update_fields=["status", "scheduled_at", "error"])
        WORKER_EVENT.set()
        return Response({"data": PrintJobSerializer(job).data})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Отменить pending/failed job — статус → DEAD, worker не возьмёт.

        - DONE/DEAD → idempotent 200 (без изменений).
        - PRINTING → 409: job уже отправляется на принтер, отмена небезопасна.
        - PENDING/FAILED → DEAD + finished_at=now + пометка в error.
        SSE-событие `print_job.updated` эмитится автоматически post_save сигналом.
        """
        job = self.get_object()
        if job.status in (PrintJobStatus.DONE, PrintJobStatus.DEAD):
            return Response({"data": PrintJobSerializer(job).data})
        if job.status == PrintJobStatus.PRINTING:
            return Response(
                {"error": {
                    "code": "JOB_IN_PROGRESS",
                    "message": "Нельзя отменить job в статусе PRINTING",
                }},
                status=409,
            )
        job.status = PrintJobStatus.DEAD
        job.finished_at = timezone.now()
        job.error = (job.error or "") + "\n[cancelled by user]"
        job.save(update_fields=["status", "finished_at", "error"])
        return Response({"data": PrintJobSerializer(job).data})


class PrintStationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD цехов / станций печати — frame 18 «Цеха».

    System-станции (system_code != '') нельзя удалить (но можно менять
    printer и is_active)."""

    from .models import PrintStation
    from .serializers import PrintStationSerializer

    serializer_class = PrintStationSerializer
    permission_classes = [IsCashier]
    pagination_class = None

    def get_queryset(self):
        from .models import PrintStation
        return PrintStation.objects.filter(restaurant=self.request.user.restaurant)

    def list(self, request, *args, **kwargs):
        from .serializers import PrintStationSerializer
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {"data": PrintStationSerializer(qs, many=True).data, "meta": {"total": qs.count()}}
        )

    def perform_create(self, serializer):
        serializer.save(restaurant=self.request.user.restaurant)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        return Response({"data": ser.data}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"data": ser.data})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system:
            raise BusinessError(
                "STATION_SYSTEM",
                "Системную станцию нельзя удалить — только отключить.",
                400,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
