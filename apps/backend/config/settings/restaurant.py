"""Настройки для развёртывания на сервере ресторана.

Запускается на локальном сервере в LAN ресторана. POS-станции в той же сети
подключаются по `http://restos.local:8000/api/v1/`.

ВАЖНО: SA полностью отключён. Кассир/владелец не должен иметь возможности
открыть SA-логин или вызвать SA-API — иначе сломана бизнес-модель лицензий.
"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost", "restos.local"],
)
SECRET_KEY = env("DJANGO_SECRET_KEY")

# Ресторанный инстанс использует свою БД (отдельно от cloud).
# Здесь живут: Order, Menu, Table, Shift, Users (кассиры), Audit,
# LicenseTokenCache (зеркало лицензии из cloud), PendingTelemetrySnapshot.
DATABASES = {
    "default": env.db("RESTAURANT_DATABASE_URL"),
}

# КРИТИЧНО: SA выключен. /superadmin/ и /api/v1/superadmin/ вернут 404.
SUPERADMIN_ENABLED = False

# Django admin тоже отключён — кассир/владелец не должен иметь возможности
# создать локального superuser и через /admin/licensing/ отредактировать
# expires_at. На ресторанном сервере нечего администрировать вручную.
DJANGO_ADMIN_ENABLED = False
