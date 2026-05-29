"""Обновить кэш JWT-токена лицензии с cloud-сервера.

Запускается:
- на старте ресторанного приложения (systemd ExecStartPre)
- по cron каждые N минут (чтобы блокировки в SA быстро доходили)
- вручную после правок env-конфига

Пример cron (каждые 15 минут):
    */15 * * * * cd /opt/restos && .venv/bin/python manage.py refresh_license
"""
from django.core.management.base import BaseCommand, CommandError

from apps.licensing.sync import LicenseSyncError, refresh_license_token


class Command(BaseCommand):
    help = "Обновить JWT-токен лицензии из vendor cloud."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app-version", default="",
            help="Версия POS-клиента (попутно отдаётся в heartbeat)",
        )

    def handle(self, *args, **opts):
        try:
            cache = refresh_license_token(app_version=opts.get("app_version", ""))
        except LicenseSyncError as exc:
            raise CommandError(f"Ошибка sync: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(
            f"Лицензия обновлена: plan={cache.plan} "
            f"expires={cache.expires_at} blocked={cache.is_blocked}"
        ))
