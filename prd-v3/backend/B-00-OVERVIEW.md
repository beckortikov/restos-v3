# B-00 — Backend overview

## Стек

| Компонент | Версия |
|---|---|
| Python | 3.12 |
| Django | 5.x |
| DRF | 3.15+ |
| `djangorestframework-simplejwt` | 5.x |
| PostgreSQL | 16 |
| `python-escpos` | 3.1+ |
| `psycopg[binary]` | 3.x — нужен LISTEN/NOTIFY для SSE |
| `gunicorn` (Linux) с `--worker-class gthread` | last |
| `waitress` (Windows) — поддерживает long requests из коробки | last |
| `django-environ` | last |
| `django-filter`, `django-cors-headers` | last |

В MVP **не используем**: Celery, Redis, Channels. Фоновые задачи — отдельный поток или management-command под systemd.

## Структура проекта

```
restos-backend/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py          # DEBUG=True, sqlite допустимо для тестов
│   │   └── prod.py         # PostgreSQL, gunicorn, локальный файловый logger
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── users/              # User, PinSession, JWT-views
│   ├── tables/             # Zone, Table
│   ├── menu/               # Category, MenuItem
│   ├── orders/             # Order, OrderItem, services
│   ├── printing/           # Printer, PrintJob, ESC/POS service, worker
│   └── events/             # SSE endpoint /events/, signals → pg_notify (B-06)
├── common/
│   ├── exceptions.py       # BusinessError, custom_exception_handler
│   ├── pagination.py       # StandardPagination
│   ├── permissions.py      # IsCashier, IsWaiter
│   ├── idempotency.py      # IdempotencyMiddleware + IdempotencyRecord model
│   └── utils.py
├── deploy/
│   ├── systemd/
│   │   ├── restos-backend.service
│   │   └── restos-print-worker.service
│   ├── nginx/restos.conf
│   └── windows/install-service.ps1
├── manage.py
├── requirements.txt
├── pytest.ini
└── docker-compose.yml      # postgres + nginx + gunicorn (для dev)
```

Каждое приложение содержит: `models.py`, `serializers.py`, `views.py`, `urls.py`, `services.py`, `permissions.py` (если есть специфика), `admin.py`, `tests/`.

## Settings (ключевые блоки)

```python
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.staticfiles",
    "rest_framework", "rest_framework_simplejwt", "django_filters", "corsheaders",
    "apps.users", "apps.tables", "apps.menu", "apps.orders",
    "apps.printing", "apps.events",
    "common",
]

AUTH_USER_MODEL = "users.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "apps.users.auth.PinSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
}

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "common.idempotency.IdempotencyMiddleware",   # перед common middleware
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://192\.168\.\d+\.\d+(:\d+)?$",
    r"^http://10\.\d+\.\d+\.\d+(:\d+)?$",
    r"^http://172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+(:\d+)?$",
    r"^http://localhost(:\d+)?$",
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"      # храним в UTC, фронт сам показывает в Asia/Dushanbe

PRINTER_VIRTUAL = env.bool("PRINTER_VIRTUAL", default=False)
PRINTER_OUTPUT_DIR = BASE_DIR / "printouts"
```

## Сквозные общие компоненты

### `common/exceptions.py`

```python
class BusinessError(Exception):
    def __init__(self, code, message, status_code=422, detail=None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}

def custom_exception_handler(exc, ctx):
    if isinstance(exc, BusinessError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
            status=exc.status_code,
        )
    return drf_exception_handler(exc, ctx)
```

### `common/pagination.py`

```python
class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500

    def get_paginated_response(self, data):
        return Response({
            "data": data,
            "meta": {
                "total": self.page.paginator.count,
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "pages": self.page.paginator.num_pages,
            },
        })
```

### `common/permissions.py`

```python
class IsCashier(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "cashier")

class IsWaiter(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "waiter")
```

## Миграции

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py loaddata fixtures/initial_restaurant.json   # 1 ресторан, 1 кассир, 1 принтер
```

Никаких хитрых data-migrations в MVP. Все ручные действия — через Django admin.

## Запуск

```bash
# dev
python manage.py runserver 0.0.0.0:8000

# prod (Linux). gthread обязателен для SSE — long-lived requests
gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --worker-class gthread \
    --workers 3 --threads 16 \
    --timeout 0 --keepalive 75
python manage.py print_worker     # отдельный systemd-юнит
```

`--timeout 0` критично: дефолтные 30 с убьют SSE-стрим. `--threads 16` × 3 воркера = 48 одновременных SSE-коннектов — с запасом для LAN ресторана.
