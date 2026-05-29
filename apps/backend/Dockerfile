# RestOS Backend — Django 5 + DRF + PostgreSQL клиент
# Сборка: docker build -f apps/backend/Dockerfile -t restos-backend apps/backend
# Запуск: см. docker-compose.yml в корне репо

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Системные зависимости (psycopg compile-time deps, build tools для wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 1) Установка Python-зависимостей (кэшируется отдельно от кода)
COPY pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && \
    pip install -e ".[dev]"

# 2) Копируем исходники
COPY . /app

# 3) Создаём непривилегированного юзера
RUN useradd -m -u 1000 restos && \
    mkdir -p /app/printouts /app/staticfiles /app/media && \
    chown -R restos:restos /app

USER restos

EXPOSE 8000

# Entrypoint: применяет миграции, потом запускает gunicorn
COPY --chown=restos:restos docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "config.wsgi:application"]
