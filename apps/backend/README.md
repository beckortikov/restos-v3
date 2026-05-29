# apps/backend — Django REST API

Backend для RestOS v3. Django 5 + DRF + PostgreSQL 16 + python-escpos. Без UI — только REST API + Django admin для seed/конфигурации.

ТЗ: [../../prd-v3/backend/B-00-OVERVIEW.md](../../prd-v3/backend/B-00-OVERVIEW.md). API-контракт: [../../prd-v3/01-API-CONTRACT.md](../../prd-v3/01-API-CONTRACT.md).

## Структура

```
apps/backend/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── users/        User, Restaurant, PinSession, JWT (B-01)
│   ├── tables/       Zone, Table (B-02)
│   ├── menu/         Category, MenuItem (B-03)
│   ├── orders/       Order, OrderItem, services (B-04)
│   ├── printing/     Printer, PrintJob, ESC/POS, worker (B-05)
│   └── events/       SSE /events/, pg_notify (B-06)
├── common/
│   ├── exceptions.py     BusinessError, custom_exception_handler
│   ├── pagination.py     StandardPagination
│   ├── permissions.py    IsCashier, IsWaiter
│   ├── idempotency.py    IdempotencyMiddleware + IdempotencyRecord
│   └── utils.py
├── deploy/
│   ├── systemd/
│   ├── nginx/
│   └── windows/
├── fixtures/             initial_restaurant.json
├── manage.py
├── pyproject.toml
└── pytest.ini
```

## Команды

```bash
# из корня репо
cd apps/backend

# установка
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# база
createdb restos_dev
python manage.py migrate
python manage.py loaddata fixtures/initial_restaurant.json

# dev
python manage.py runserver 0.0.0.0:8000
python manage.py print_worker          # отдельный процесс

# prod (Linux)
gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --worker-class gthread \
    --workers 3 --threads 16 \
    --timeout 0 --keepalive 75

# тесты
pytest
```

`--timeout 0` обязателен для SSE — long-lived requests.

## Окружение

См. [.env.example](.env.example). Скопировать в `.env` и заполнить.

## Порядок реализации

1. B-00 — скелет, settings, common
2. B-01 — auth (JWT для PWA + PIN-сессия для PySide)
3. B-02 + B-03 (можно параллельно) — tables, menu
4. B-04 — orders (ядро)
5. B-05 — printing (сначала с `PRINTER_VIRTUAL=True`)
6. B-06 — SSE + LISTEN/NOTIFY
