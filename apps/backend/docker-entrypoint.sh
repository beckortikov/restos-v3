#!/bin/sh
# RestOS Backend entrypoint
# 1. Ждём готовности Postgres
# 2. Применяем миграции
# 3. Опционально создаём суперюзера (admin/admin) при первом запуске
# 4. Запускаем переданную команду (по умолчанию gunicorn)
set -e

# Извлечь host/port из DATABASE_URL (postgres://user:pass@host:port/dbname)
DB_HOST=$(echo "${DATABASE_URL}" | sed -E 's|.*@([^:/]+).*|\1|')
DB_PORT=$(echo "${DATABASE_URL}" | sed -E 's|.*:([0-9]+)/.*|\1|')
DB_HOST=${DB_HOST:-postgres}
DB_PORT=${DB_PORT:-5432}

echo "→ Waiting for Postgres at ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
    if (echo > /dev/tcp/${DB_HOST}/${DB_PORT}) 2>/dev/null; then
        echo "  Postgres is ready."
        break
    fi
    sleep 1
done

echo "→ Applying migrations..."
python manage.py migrate --noinput

# Создать суперюзера если задан DJANGO_SUPERUSER_* (только при первом запуске)
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "→ Creating superuser (idempotent)..."
    python manage.py createsuperuser --noinput 2>/dev/null || echo "  (superuser already exists)"
fi

# collectstatic для admin
echo "→ Collecting static files..."
python manage.py collectstatic --noinput --clear 2>&1 | tail -1

echo "→ Starting: $@"
exec "$@"
