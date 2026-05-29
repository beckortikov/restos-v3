# RestOS v3

POS-система для ресторана: столы → заказ от официанта → оплата кассиром → печать гостевого чека. Локальная LAN-установка без облака.

ТЗ: [prd-v3/00-INDEX.md](prd-v3/00-INDEX.md). Дизайн кассира: [design/pos_cashier.pen](design/pos_cashier.pen). Гайдлайны для агента: [CLAUDE.md](CLAUDE.md).

## Структура

```
restos-v3/
├── apps/
│   ├── backend/      Django 5 + DRF + PostgreSQL 16 — REST API + admin
│   ├── pos/          PySide6 — десктоп кассира (на той же main POS-машине)
│   ├── waiter/       Vite + React + Capacitor — PWA официанта (порт из v1)
│   └── dashboard/    Next.js — Owner-dashboard (Phase 9)
├── prd-v3/           ТЗ
├── design/           Дизайн (Pencil .pen)
└── CLAUDE.md         Правила для AI-агента
```

Каждый `apps/<name>/` — отдельная единица сборки и релизного цикла. Общаются между собой только через REST API backend'а ([prd-v3/01-API-CONTRACT.md](prd-v3/01-API-CONTRACT.md)).

## Скоуп AI-агента

Агент работает только над `apps/backend/` и `apps/pos/`. `apps/waiter/` и `apps/dashboard/` существуют в плане проекта, но пишутся не агентом — см. [CLAUDE.md](CLAUDE.md).

## Топология (LAN)

```
┌─────────── LAN ресторана ────────────┐
│  Main POS:                            │
│   • PostgreSQL 16                     │
│   • apps/backend (Django @ :8000)     │
│   • nginx @ :80 (static + /api/)      │
│   • apps/pos (PySide6, отдельный proc)│
│   • Принтер ESC/POS (USB или TCP)     │
│         ▲                             │
│   ┌─────┴─────┐  ┌──────────┐         │
│   │ Планшет   │  │ Планшет  │ …       │
│   │ apps/waiter│  │apps/waiter│        │
│   └───────────┘  └──────────┘         │
└───────────────────────────────────────┘
```

## Версии

| Компонент | Версия |
|---|---|
| Python | 3.12 |
| PostgreSQL | 16 |
| Django | 5.x |
| DRF | 3.15+ |
| PySide6 | 6.7 |
| Node | 22 (для waiter и dashboard) |
| pnpm | 9.x |

## Быстрый запуск (Docker Compose)

Backend + Postgres поднимаются одной командой:

```bash
cp .env.example .env
# отредактируй .env — поменяй DJANGO_SECRET_KEY и DJANGO_SUPERUSER_PASSWORD
docker compose up -d

# проверка
curl http://localhost:8000/api/v1/health/   # {"status":"ok","db":true}
open http://localhost:8000/admin/           # admin / задал в .env
```

Что произойдёт:
1. `postgres:16-alpine` контейнер стартует с persistent volume `postgres_data`
2. Backend `restos-backend` ждёт `pg_isready` → применяет миграции → создаёт суперюзера (если задан `DJANGO_SUPERUSER_*`) → стартует gunicorn на `:8000`
3. Healthcheck `/api/v1/health/` каждые 15с

Управление:
```bash
docker compose logs -f backend     # стрим логов
docker compose restart backend     # рестарт после правки кода
docker compose down                # стоп (данные сохраняются)
docker compose down -v             # стоп + удаление БД (полный сброс)
```

Образ backend опубликован в GHCR (собирается на push в main / тег v*):
```bash
docker pull ghcr.io/beckortikov/restos-v3/backend:latest
```

## Команды

См. README в каждом `apps/<name>/`.

## Сборка Windows .exe (PySide6 кассир)

CI собирает exe автоматически при push'е тега `v*` или вручную через **Actions → Build Windows EXE → Run workflow**.

Локально:

```bash
cd apps/pos
.venv/bin/pip install -e ".[dev]"
.venv/bin/pyinstaller pos.spec --noconfirm --clean
# Результат: apps/pos/dist/RestOS-POS/RestOS-POS.exe
```

Создать релиз:

```bash
git tag v0.1.0
git push origin v0.1.0
# GitHub Actions соберёт exe и опубликует в Releases
```

## SA-7 — Активация на конкретной машине

POS привязывается к Windows BIOS UUID. Поток:
1. Поставщик создаёт `License` в Django admin (`/admin/licensing/license/`)
2. Клиент запускает POS → видит экран «Активация» с HWID
3. Клиент копирует HWID → шлёт поставщику
4. Поставщик вписывает `hardware_uuid` в `License` → выдаёт `license_key`
5. Клиент вводит ключ → POST `/license/activate/` → готово

Подробности — [prd-v3/99-ROADMAP.md → SA-7](prd-v3/99-ROADMAP.md).
