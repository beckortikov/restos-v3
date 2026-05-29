from rest_framework import serializers

from .models import PaperSize, Printer, PrintJob, PrintJobKind, PrintStation


class PrinterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Printer
        fields = [
            "id", "name", "kind", "address", "paper_size",
            "is_default", "is_active",
        ]

    def validate_paper_size(self, value: str) -> str:
        if value not in PaperSize.values:
            raise serializers.ValidationError("paper_size: 58mm/76mm/80mm")
        return value


class PrintJobSerializer(serializers.ModelSerializer):
    printer_name = serializers.CharField(
        source="printer.name", read_only=True, default=None
    )

    class Meta:
        model = PrintJob
        fields = [
            "id",
            "kind",
            "status",
            "retries",
            "error",
            "printer",
            "printer_name",
            "order",
            "scheduled_at",
            "started_at",
            "finished_at",
            "created_at",
        ]


class PrintStationSerializer(serializers.ModelSerializer):
    printer_name = serializers.CharField(
        source="printer.name", read_only=True, default=None
    )
    is_system = serializers.BooleanField(read_only=True)

    class Meta:
        model = PrintStation
        fields = [
            "id", "name", "system_code", "is_system",
            "printer", "printer_name",
            "is_active", "sort_order",
        ]
        read_only_fields = ["system_code", "is_system"]
