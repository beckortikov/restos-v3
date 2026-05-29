"""Сидинг дефолтных причин отмены/возврата для всех существующих ресторанов.

Архитектурно: причины не хардкодим в код, но даём осмысленный default,
который кассир/админ потом редактирует через UI настроек.
"""
from django.db import migrations

from apps.orders.defaults import DEFAULT_CANCEL_REASONS


def seed(apps, schema_editor):
    Restaurant = apps.get_model("users", "Restaurant")
    CancelReason = apps.get_model("orders", "CancelReason")

    for resto in Restaurant.objects.all():
        for kind, labels in DEFAULT_CANCEL_REASONS.items():
            for i, label in enumerate(labels):
                CancelReason.objects.get_or_create(
                    restaurant=resto,
                    kind=kind,
                    label=label,
                    defaults={"sort_order": i, "is_active": True},
                )


def unseed(apps, schema_editor):
    CancelReason = apps.get_model("orders", "CancelReason")
    CancelReason.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0005_cancelreason"),
    ]
    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
