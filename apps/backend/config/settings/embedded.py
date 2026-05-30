"""Embedded режим: Django запускается внутри POS-exe.

Особенности:
- DATABASE_URL прокидывается из EmbeddedBackend / pgserver (локальный Postgres)
- DEBUG=False (это «production» в смысле single-machine)
- ALLOWED_HOSTS = ["127.0.0.1", "localhost", "*"] — слушает только localhost
- Static = serve через whitenoise (если установлен) или Django dev (DEBUG=True override)
- Печать — виртуальная по умолчанию (можно сменить через .env)
"""
import os

# pgserver выдаёт DATABASE_URL — он уже в env. Если нет — fallback на dev (с .env).
os.environ.setdefault("DJANGO_DEBUG", "False")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,*")
os.environ.setdefault("PRINTER_VIRTUAL", "True")

from .base import *  # noqa: E402,F401,F403

# Перечитать DEBUG/ALLOWED_HOSTS из env уже после переопределения дефолтов выше.
DEBUG = env.bool("DJANGO_DEBUG", default=False)  # noqa: F405
ALLOWED_HOSTS = env.list(  # noqa: F405
    "DJANGO_ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost", "*"],
)

# CORS — в embedded режиме backend и POS на одной машине, расширять не надо.
CORS_ALLOW_ALL_ORIGINS = True

# SuperAdmin endpoints выключены — клиент работает локально.
SUPERADMIN_ENABLED = False

# Logging — пишем в файл рядом с pgdata, в %APPDATA%/RestOS/
from pathlib import Path
import sys
def _embedded_log_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RestOS"
    else:
        base = Path.home() / ".restos-pos"
    base.mkdir(parents=True, exist_ok=True)
    return base / "embedded.log"

LOGGING = {  # noqa: F811
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_embedded_log_path()),
            "formatter": "default",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
        },
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "INFO"},
        "apps": {"handlers": ["console", "file"], "level": "INFO"},
    },
}
