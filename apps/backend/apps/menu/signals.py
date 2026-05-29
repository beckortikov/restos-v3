"""Signals для apps.menu — авто-сидинг шаблонов комментариев."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import Restaurant


@receiver(post_save, sender=Restaurant)
def seed_default_item_notes(sender, instance: Restaurant, created: bool, **kwargs):
    if not created:
        return
    from .defaults import DEFAULT_ITEM_NOTES
    from .models import MenuItemNote

    for i, label in enumerate(DEFAULT_ITEM_NOTES):
        MenuItemNote.objects.get_or_create(
            restaurant=instance, label=label,
            defaults={"sort_order": i, "is_active": True},
        )
