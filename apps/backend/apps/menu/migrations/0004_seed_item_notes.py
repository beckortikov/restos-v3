"""Сидинг дефолтных шаблонов комментариев для существующих ресторанов."""
from django.db import migrations

from apps.menu.defaults import DEFAULT_ITEM_NOTES


def seed(apps, schema_editor):
    Restaurant = apps.get_model("users", "Restaurant")
    MenuItemNote = apps.get_model("menu", "MenuItemNote")

    for resto in Restaurant.objects.all():
        for i, label in enumerate(DEFAULT_ITEM_NOTES):
            MenuItemNote.objects.get_or_create(
                restaurant=resto, label=label,
                defaults={"sort_order": i, "is_active": True},
            )


def unseed(apps, schema_editor):
    apps.get_model("menu", "MenuItemNote").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("menu", "0003_menuitemnote"),
    ]
    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
