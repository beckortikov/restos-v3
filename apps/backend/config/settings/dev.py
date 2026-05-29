from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-do-not-use-in-prod")

# В dev и тестах SA включён — мы локально тестируем весь функционал.
# Прод-настройки ресторана (`config.settings.restaurant` если появится)
# остаются с дефолтом False из base.py.
SUPERADMIN_ENABLED = env.bool("SUPERADMIN_ENABLED", default=True)
