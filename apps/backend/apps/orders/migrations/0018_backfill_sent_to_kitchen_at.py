"""Backfill OrderItem.sent_to_kitchen_at для существующих позиций.

После добавления поля (миграция 0017) у всех старых OrderItem'ов timestamp
NULL → POS UI показывает кнопку «НА КУХНЮ» как будто у заказа есть
несрафкированные позиции, что вводит в заблуждение.

Заполняем `sent_to_kitchen_at = created_at` для всех существующих позиций
с NULL — считаем, что они уже прошли через kitchen-broadcast (через
старый код enqueue_kitchen_prints, который выполнялся при create_order).
"""
from django.db import migrations


def backfill(apps, schema_editor):
    OrderItem = apps.get_model("orders", "OrderItem")
    OrderItem.objects.filter(sent_to_kitchen_at__isnull=True).update(
        sent_to_kitchen_at=models_F_created_at(),
    )


def _no_op(apps, schema_editor):
    pass


def models_F_created_at():
    from django.db.models import F
    return F("created_at")


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0017_orderitem_sent_to_kitchen_at"),
    ]

    operations = [
        migrations.RunPython(backfill, _no_op),
    ]
