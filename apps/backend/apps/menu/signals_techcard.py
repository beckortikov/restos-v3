"""Signals для пересчёта MenuItem.cogs при изменении техкарт.

При сохранении/удалении строки техкарты:
1. Берём связанный MenuItem
2. Пересчитываем его cogs из текущих строк
3. Если изменилось — сохраняем

Phase 7C — auto-recalc cogs.
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import MenuItemTechCardLine


def _recalc_for_line(line: MenuItemTechCardLine) -> None:
    """Перенос вычислений в сервис чтобы не цикл-импорт."""
    from apps.inventory.services import recalc_menu_item_cogs

    try:
        recalc_menu_item_cogs(line.menu_item)
    except Exception:
        # При initial migration/loaddata MenuItem может быть невалиден
        pass


@receiver(post_save, sender=MenuItemTechCardLine)
def on_techcard_save(sender, instance, **kwargs):
    _recalc_for_line(instance)


@receiver(post_delete, sender=MenuItemTechCardLine)
def on_techcard_delete(sender, instance, **kwargs):
    _recalc_for_line(instance)
