"""Management command: архивирование старых заказов.

Запуск (ручной или через cron):
    python manage.py archive_orders --days 90
    python manage.py archive_orders --days 30 --dry-run

В production cron-крон в crontab или systemd-timer:
    0 3 * * *  python manage.py archive_orders --days 90 >> /var/log/restos/archive.log

Архивные заказы сохраняются в БД (для compliance), но скрыты из API
по умолчанию. Доступ через `GET /orders/?include_archived=true`.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Архивировать закрытые/отменённые заказы старше N дней."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--days", type=int, default=90,
            help="Возраст в днях, после которого заказы архивируются (default: 90)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Показать сколько было бы заархивировано, без записи.",
        )

    def handle(self, *args, **options) -> None:
        from datetime import timedelta

        from django.db.models import Q
        from django.utils import timezone

        from apps.orders.models import Order, OrderStatus

        days = int(options["days"])
        dry_run = bool(options.get("dry_run"))
        cutoff = timezone.now() - timedelta(days=days)

        cond = (
            Q(status=OrderStatus.DONE, closed_at__lt=cutoff)
            | Q(status=OrderStatus.CANCELLED, cancelled_at__lt=cutoff)
        )
        qs = Order.objects.filter(archived_at__isnull=True).filter(cond)
        candidates = qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] К архивации подходит {candidates} заказов "
                    f"старше {days} дней (cutoff={cutoff:%Y-%m-%d %H:%M})"
                )
            )
            return

        from apps.orders.services import archive_old_orders
        archived = archive_old_orders(days=days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Заархивировано {archived} заказов старше {days} дней"
            )
        )
