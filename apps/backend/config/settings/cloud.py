"""Настройки для развёртывания на vendor-облаке (нашем сервере).

Этот инстанс — центральный для всех клиентов RestOS. Содержит:
- SA UI (`/superadmin/`) и SA API (`/api/v1/superadmin/`) — управление лицензиями
- Центральные License-записи всех ресторанов
- Telemetry / heartbeat / биллинг

POS-станции и кассирский UI сюда НЕ ходят напрямую — они работают со своим
локальным сервером (config.settings.restaurant). Sync лицензий между cloud
и restaurant — отдельный механизм (Phase ahead).
"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
SECRET_KEY = env("DJANGO_SECRET_KEY")

# Cloud-инстанс использует свою БД (отдельно от ресторанов).
# Здесь живут: Restaurant (master), License, TelemetrySnapshot, SA-Users.
DATABASES = {
    "default": env.db("CLOUD_DATABASE_URL"),
}

# В облаке SA включён.
SUPERADMIN_ENABLED = True
