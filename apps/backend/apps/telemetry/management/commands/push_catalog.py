"""Отправить снимок каталога меню (категории + блюда) в cloud.

Запускать:
- 1 раз в день по cron (вместе с push_telemetry или отдельно)
- При значительных изменениях меню (через signal — Phase ahead)
- Вручную после крупного обновления меню

Пример cron (раз в день в 03:00):
    0 3 * * * cd /opt/restos && .venv/bin/python manage.py push_catalog
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.telemetry.sender import TelemetryPushError, push_catalog_to_cloud
from apps.users.models import Restaurant


class Command(BaseCommand):
    help = "Отправить снимок каталога меню (без cogs/ингредиентов) в cloud."

    def handle(self, *args, **opts):
        if getattr(settings, "SUPERADMIN_ENABLED", False):
            self.stdout.write(self.style.WARNING(
                "SUPERADMIN_ENABLED=True — это cloud-инстанс, catalog push отключён."
            ))
            return

        rest = Restaurant.objects.exclude(api_key="").first()
        if rest is None:
            self.stdout.write(self.style.WARNING(
                "Не найдено ресторана с api_key."
            ))
            return

        try:
            ok = push_catalog_to_cloud(restaurant=rest)
        except TelemetryPushError as exc:
            self.stdout.write(self.style.ERROR(f"Push не прошёл: {exc}"))
            return

        if ok:
            self.stdout.write(self.style.SUCCESS(
                "✓ Каталог отправлен в cloud."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "Cloud вернул не 200 — попробуем в следующий раз."
            ))
