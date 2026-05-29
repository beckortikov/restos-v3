"""Создаём триал-лицензию для уже существующих ресторанов (которые есть в БД
до внедрения licensing). Без этого middleware заблокирует все writes."""
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Restaurant = apps.get_model("users", "Restaurant")
    License = apps.get_model("licensing", "License")
    import uuid

    now = timezone.now()
    for r in Restaurant.objects.all():
        if License.objects.filter(restaurant=r).exists():
            continue
        License.objects.create(
            restaurant=r,
            plan="trial",
            license_key=uuid.uuid4().hex,
            started_at=now,
            expires_at=now + timedelta(days=365),  # год для существующих dev-ресторанов
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("licensing", "0001_license_foundation"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
