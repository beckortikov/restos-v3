"""Собрать агрегаты текущего дня + отправить все pending в cloud.

Запуск:
- по cron каждый час на ресторанном сервере
- вручную для отладки

Пример cron:
    0 * * * * cd /opt/restos && .venv/bin/python manage.py push_telemetry
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.telemetry.collector import collect_telemetry
from apps.telemetry.sender import (
    TelemetryPushError,
    push_pending_to_cloud,
    queue_telemetry,
)
from apps.users.models import Restaurant


class Command(BaseCommand):
    help = "Собрать телеметрию ресторана и отправить накопленные в cloud."

    def handle(self, *args, **opts):
        # На cloud-инстансе ничего не делаем — он сам себе не шлёт телеметрию.
        if getattr(settings, "SUPERADMIN_ENABLED", False):
            self.stdout.write(self.style.WARNING(
                "SUPERADMIN_ENABLED=True — это cloud-инстанс, telemetry push отключён."
            ))
            return

        # Restaurant-инстанс обычно держит ровно один Restaurant (свой).
        # Берём первого с непустым api_key (= настроенным от cloud).
        rest = Restaurant.objects.exclude(api_key="").first()
        if rest is None:
            self.stdout.write(self.style.WARNING(
                "Не найдено ресторана с api_key. "
                "Cloud SA должен сгенерировать ключ и записать в RESTAURANT_API_KEY."
            ))
            return

        # 1. Снять snapshot и положить в локальный буфер
        payload = collect_telemetry(restaurant=rest)
        snap = queue_telemetry(restaurant=rest, payload=payload)
        self.stdout.write(self.style.SUCCESS(
            f"Snapshot {snap.business_date} в буфере: "
            f"{payload['daily_revenue']} TJS / {payload['daily_orders_count']} зак."
        ))

        # 2. Попытаться отправить всё что накопилось в буфере (включая старое)
        try:
            sent, failed = push_pending_to_cloud()
        except TelemetryPushError as exc:
            self.stdout.write(self.style.ERROR(f"Push не прошёл: {exc}"))
            return

        if sent:
            self.stdout.write(self.style.SUCCESS(
                f"✓ Отправлено snapshots: {sent}"
            ))
        if failed:
            self.stdout.write(self.style.WARNING(
                f"⚠ Не удалось отправить: {failed} — попробуем в следующий раз."
            ))
