"""Signals для apps.orders.

Авто-сидинг дефолтных причин отмены при создании нового ресторана.
Список причин лежит в `apps.orders.defaults` — единый источник правды
для миграции и ранtime-сидера.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import Restaurant


@receiver(post_save, sender=Restaurant)
def seed_default_cancel_reasons(sender, instance: Restaurant, created: bool, **kwargs):
    if not created:
        return
    from .defaults import DEFAULT_CANCEL_REASONS
    from .models import CancelReason

    for kind, labels in DEFAULT_CANCEL_REASONS.items():
        for i, label in enumerate(labels):
            CancelReason.objects.get_or_create(
                restaurant=instance,
                kind=kind,
                label=label,
                defaults={"sort_order": i, "is_active": True},
            )


@receiver(post_save, sender=Restaurant)
def seed_default_payment_providers(sender, instance: Restaurant, created: bool, **kwargs):
    if not created:
        return
    from .defaults import DEFAULT_PAYMENT_PROVIDERS
    from .models import PaymentProvider

    for cfg in DEFAULT_PAYMENT_PROVIDERS:
        PaymentProvider.objects.get_or_create(
            restaurant=instance,
            kind=cfg["kind"],
            name=cfg["name"],
            defaults={
                "description": cfg["description"],
                "commission_pct": cfg["commission_pct"],
                "is_active": cfg["is_active"],
                "sort_order": cfg["sort_order"],
            },
        )


@receiver(post_save, sender=Restaurant)
def seed_default_discounts(sender, instance: Restaurant, created: bool, **kwargs):
    if not created:
        return
    from .defaults import DEFAULT_DISCOUNTS
    from .models import Discount

    for cfg in DEFAULT_DISCOUNTS:
        Discount.objects.get_or_create(
            restaurant=instance,
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
