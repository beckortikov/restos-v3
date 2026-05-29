"""Сидинг дефолтных способов оплаты и скидок для существующих ресторанов.

Источник правды для дефолтов — `apps/orders/defaults.py`.
Для новых ресторанов сидинг выполняется через post_save сигнал.
"""
from django.db import migrations

from apps.orders.defaults import DEFAULT_DISCOUNTS, DEFAULT_PAYMENT_PROVIDERS


def seed(apps, schema_editor):
    Restaurant = apps.get_model("users", "Restaurant")
    PaymentProvider = apps.get_model("orders", "PaymentProvider")
    Discount = apps.get_model("orders", "Discount")

    for resto in Restaurant.objects.all():
        for cfg in DEFAULT_PAYMENT_PROVIDERS:
            PaymentProvider.objects.get_or_create(
                restaurant=resto,
                kind=cfg["kind"],
                name=cfg["name"],
                defaults={
                    "description": cfg["description"],
                    "commission_pct": cfg["commission_pct"],
                    "is_active": cfg["is_active"],
                    "sort_order": cfg["sort_order"],
                },
            )
        for cfg in DEFAULT_DISCOUNTS:
            Discount.objects.get_or_create(
                restaurant=resto,
                type=cfg["type"],
                name=cfg["name"],
                defaults={
                    "description": cfg["description"],
                    "kind": cfg["kind"],
                    "value": cfg["value"],
                    "is_active": cfg["is_active"],
                    "sort_order": cfg["sort_order"],
                },
            )


def unseed(apps, schema_editor):
    apps.get_model("orders", "PaymentProvider").objects.all().delete()
    apps.get_model("orders", "Discount").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0007_discount_paymentprovider"),
    ]
    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
