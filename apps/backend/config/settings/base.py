from datetime import timedelta
from pathlib import Path

import environ
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

INSTALLED_APPS = [
    # apps.superadmin поднят первым: чтобы наш кастомный admin/index.html
    # (с KPI-дашбордом) шёл раньше unfold/admin/index.html в template-loader.
    "apps.superadmin",
    # django-unfold должен быть ДО django.contrib.admin — переопределяет admin templates.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "common",
    "apps.users",
    "apps.tables",
    "apps.menu",
    "apps.orders",
    "apps.printing",
    "apps.events",
    "apps.shifts",
    "apps.audit",
    "apps.reservations",
    "apps.kitchen",
    "apps.licensing",
    "apps.analytics",
    "apps.telemetry",
    "apps.inventory",
    "apps.payroll",
    # apps.superadmin зарегистрирован выше — для override admin templates
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "common.idempotency.IdempotencyMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # SA-7 — machine binding + license enforcement
    "apps.licensing.middleware.LicenseMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    # Только Postgres. Без fallback — если DATABASE_URL не задан, приложение
    # падает сразу при старте с понятной ошибкой, а не молча уходит в SQLite.
    "default": env.db("DATABASE_URL"),
}

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "apps.users.auth.PinSessionAuthentication",
        "apps.users.auth.TokenQueryParamAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["common.permissions.IsAuthenticatedAndLicensed"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=env.int("JWT_ACCESS_LIFETIME_HOURS", default=8)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_LIFETIME_DAYS", default=30)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://192\.168\.\d+\.\d+(:\d+)?$",
    r"^http://10\.\d+\.\d+\.\d+(:\d+)?$",
    r"^http://172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+(:\d+)?$",
    r"^http://localhost(:\d+)?$",
    r"^http://127\.0\.0\.1(:\d+)?$",
]
CORS_ALLOW_HEADERS = [
    "accept", "accept-encoding", "authorization", "content-type", "dnt",
    "origin", "user-agent", "x-csrftoken", "x-requested-with",
    "idempotency-key", "if-none-match",
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PRINTER_VIRTUAL = env.bool("PRINTER_VIRTUAL", default=True)
PRINTER_OUTPUT_DIR = BASE_DIR / env.str("PRINTER_OUTPUT_DIR", default="printouts")

PIN_SESSION_TIMEOUT_MIN = env.int("PIN_SESSION_TIMEOUT_MIN", default=30)
PIN_LOCK_THRESHOLD = 5
PIN_LOCK_DURATION_MIN = 15

MVP_RESTAURANT_ID = env.int("MVP_RESTAURANT_ID", default=1)

# ── Super-Admin gating ───────────────────────────────────────────────────
# SA endpoints (/superadmin/ web-UI + /api/v1/superadmin/ JSON API) монтируются
# ТОЛЬКО когда SUPERADMIN_ENABLED=True. В развёртывании на сервере ресторана
# это всегда False — иначе кассир/владелец заведения сможет открыть SA-логин
# в LAN и попробовать подобрать пароль/самостоятельно продлить лицензию.
#
# True ставится только на vendor cloud — центральном инстансе, где сидит
# vendor (мы). Этот инстанс держит центральные License-записи всех клиентов.
SUPERADMIN_ENABLED = env.bool("SUPERADMIN_ENABLED", default=False)
SUPERADMIN_JWT_TTL_HOURS = env.int("SUPERADMIN_JWT_TTL_HOURS", default=12)

# ── License sync (Restaurant ↔ Cloud) ────────────────────────────────────
# CLOUD_BASE_URL — куда ходит ресторанный сервер чтобы взять JWT-токен
# лицензии. Пример: https://api.restos.example/
# RESTAURANT_API_KEY — секрет конкретного ресторана (см. Restaurant.api_key
# на cloud-инстансе). Без него токен не выдадут.
CLOUD_BASE_URL = env.str("CLOUD_BASE_URL", default="")
RESTAURANT_API_KEY = env.str("RESTAURANT_API_KEY", default="")
# TTL подписи JWT (на cloud-стороне в `issue_license_token`).
# Дефолт 7 дней: подпись пере-выдаётся раз в неделю. Бизнес-лицензия
# (`license_expires_at` в claims) проверяется отдельно и обычно длиннее.
LICENSE_TOKEN_TTL_SECONDS = env.int(
    "LICENSE_TOKEN_TTL_SECONDS", default=7 * 24 * 3600,
)
# Hard-block: если ресторан не дотянулся до cloud > N дней — read-only,
# даже если бизнес-лицензия в кэше ещё валидна. Защита «забыли заплатить
# и выключили интернет». Дефолт 30 дней — типично хватает.
LICENSE_HARD_OFFLINE_DAYS = env.int("LICENSE_HARD_OFFLINE_DAYS", default=30)
# Soft-warning: после N дней без refresh показываем баннер «нет связи»,
# но запись ещё разрешена (offline-mode). Дефолт 2 дня.
LICENSE_SOFT_OFFLINE_DAYS = env.int("LICENSE_SOFT_OFFLINE_DAYS", default=2)

# Django admin (`/admin/`) включён в dev/cloud, но ОТКЛЮЧЁН в ресторанном
# деплое — там нечего администрировать локально, а если кто-то создаст
# is_staff=True пользователя на сервере ресторана, он не получит доступ к
# editing License через стандартный admin.
DJANGO_ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=True)

IDEMPOTENT_PATH_PATTERNS = [
    r"^/api/v1/orders/$",
    r"^/api/v1/orders/\d+/close/$",
    r"^/api/v1/orders/\d+/cancel/$",
    r"^/api/v1/printing/jobs/\d+/retry/$",
]
IDEMPOTENCY_TTL_HOURS = 24

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ── django-unfold (modern Django admin theme) ──────────────────────────
UNFOLD = {
    "SITE_TITLE": "RestOS Vendor Console",
    "SITE_HEADER": "RestOS",
    "SITE_SUBHEADER": "Vendor Panel — управление платформой",
    "SITE_SYMBOL": "store_mall_directory",  # material-icon
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "apps.superadmin.dashboard.dashboard_callback",
    "COLORS": {
        "primary": {
            "50":  "255 247 237",
            "100": "255 237 213",
            "200": "254 215 170",
            "300": "253 186 116",
            "400": "251 146 60",
            "500": "249 115 22",   # accent-orange
            "600": "234 88 12",
            "700": "194 65 12",
            "800": "154 52 18",
            "900": "124 45 18",
            "950": "67 20 7",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Платформа",
                "separator": True,
                "items": [
                    {
                        "title": "Рестораны",
                        "icon": "store_mall_directory",
                        "link": reverse_lazy("admin:users_restaurant_changelist"),
                    },
                    {
                        "title": "Лицензии",
                        "icon": "card_membership",
                        "link": reverse_lazy("admin:licensing_license_changelist"),
                    },
                    {
                        "title": "Пользователи",
                        "icon": "manage_accounts",
                        "link": reverse_lazy("admin:users_user_changelist"),
                    },
                ],
            },
            {
                "title": "Операции",
                "separator": True,
                "items": [
                    {
                        "title": "Заказы",
                        "icon": "receipt_long",
                        "link": reverse_lazy("admin:orders_order_changelist"),
                    },
                    {
                        "title": "Смены",
                        "icon": "point_of_sale",
                        "link": reverse_lazy("admin:shifts_cashshift_changelist"),
                    },
                    {
                        "title": "Журнал действий",
                        "icon": "history",
                        "link": reverse_lazy("admin:audit_auditentry_changelist"),
                    },
                ],
            },
            {
                "title": "Меню",
                "separator": True,
                "items": [
                    {
                        "title": "Категории",
                        "icon": "category",
                        "link": reverse_lazy("admin:menu_category_changelist"),
                    },
                    {
                        "title": "Блюда",
                        "icon": "restaurant_menu",
                        "link": reverse_lazy("admin:menu_menuitem_changelist"),
                    },
                    {
                        "title": "Модификаторы",
                        "icon": "tune",
                        "link": reverse_lazy("admin:menu_modifiergroup_changelist"),
                    },
                    {
                        "title": "Зоны зала",
                        "icon": "map",
                        "link": reverse_lazy("admin:tables_zone_changelist"),
                    },
                    {
                        "title": "Столы",
                        "icon": "table_restaurant",
                        "link": reverse_lazy("admin:tables_table_changelist"),
                    },
                ],
            },
            {
                "title": "Инфраструктура",
                "separator": True,
                "items": [
                    {
                        "title": "Принтеры",
                        "icon": "print",
                        "link": reverse_lazy("admin:printing_printer_changelist"),
                    },
                    {
                        "title": "Очередь печати",
                        "icon": "task",
                        "link": reverse_lazy("admin:printing_printjob_changelist"),
                    },
                    {
                        "title": "Резервации",
                        "icon": "bookmark",
                        "link": reverse_lazy("admin:reservations_reservation_changelist"),
                    },
                ],
            },
        ],
    },
}
