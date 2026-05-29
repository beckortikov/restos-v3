"""Signals для apps.printing.

Авто-сидинг дефолтных PrintStation при создании ресторана:
системные («Касса», «Кухня») + типовые цеха («Горячий цех», «Холодный цех»,
«Бар», «Витрина»). Кассир может удалить/добавить любые non-system станции
через UI «Настройки → Принтеры».
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import Restaurant

DEFAULT_STATIONS = [
    {"name": "Касса", "system_code": "cashier", "sort_order": 0},
    {"name": "Кухня", "system_code": "kitchen", "sort_order": 1},
    {"name": "Горячий цех", "system_code": "", "sort_order": 2},
    {"name": "Холодный цех", "system_code": "", "sort_order": 3},
    {"name": "Бар", "system_code": "", "sort_order": 4},
    {"name": "Витрина", "system_code": "", "sort_order": 5},
]


@receiver(post_save, sender=Restaurant)
def seed_default_print_stations(sender, instance: Restaurant, created: bool, **kwargs):
    if not created:
        return
    from .models import PrintStation

    for cfg in DEFAULT_STATIONS:
        PrintStation.objects.get_or_create(
            restaurant=instance,
            name=cfg["name"],
            defaults={
                "system_code": cfg["system_code"],
                "sort_order": cfg["sort_order"],
                "is_active": True,
            },
        )
