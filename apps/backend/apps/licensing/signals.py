"""Auto-trial License — только в cloud-режиме.

На restaurant-инстансе (`SUPERADMIN_ENABLED=False`) лицензия НЕ создаётся
локально — она приходит из cloud через JWT-токен. Иначе у ресторана
была бы своя «фальшивая» лицензия в локальной БД, и кассир мог бы
обойти cloud-блокировку.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


@receiver(post_save, sender="users.Restaurant")
def create_trial_license(sender, instance, created, **kwargs):
    if not created:
        return
    # На restaurant-инстансе локальные License-записи не создаём.
    if not getattr(settings, "SUPERADMIN_ENABLED", False):
        return
    from .models import License, LicensePlan

    # Если ресторан уже имеет лицензию (например, тесты создают вручную) — пропускаем
    if License.objects.filter(restaurant=instance).exists():
        return
    import uuid

    License.objects.create(
        restaurant=instance,
        plan=LicensePlan.TRIAL,
        license_key=uuid.uuid4().hex,
        started_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=30),
    )
