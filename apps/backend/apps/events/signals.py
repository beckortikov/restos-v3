from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.menu.models import Category, MenuItem
from apps.orders.models import Order
from apps.printing.models import PrintJob
from apps.tables.models import Table

from .dispatch import publish


@receiver(post_save, sender=Table)
def _table_saved(sender, instance: Table, **kw):
    publish(
        "table.updated",
        instance.restaurant_id,
        {
            "id": instance.id,
            "status": instance.status,
            "current_order_id": instance.current_order_id,
            "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
        },
    )


@receiver(post_save, sender=Order)
def _order_saved(sender, instance: Order, created: bool, **kw):
    publish(
        "order.created" if created else "order.updated",
        instance.restaurant_id,
        {
            "id": instance.id,
            "status": instance.status,
            "order_type": instance.order_type,
            "table_id": instance.table_id,
            "waiter_id": instance.waiter_id,
            "total": str(instance.total),
            "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
        },
    )


@receiver(post_save, sender=PrintJob)
def _printjob_saved(sender, instance: PrintJob, **kw):
    publish(
        "print_job.updated",
        instance.restaurant_id,
        {
            "id": instance.id,
            "status": instance.status,
            "retries": instance.retries,
            "error": (instance.error or "")[:200],
        },
    )


@receiver(post_save, sender=MenuItem)
@receiver(post_save, sender=Category)
def _menu_changed(sender, instance, **kw):
    publish("menu.invalidated", instance.restaurant_id, {})
