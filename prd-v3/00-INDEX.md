# RestOS v3 MVP — Техническое задание

**Версия:** 0.1 MVP
**Дата:** 2026-05-06
**Статус:** утверждено пользователем
**Источник правды:** текущий код RestOS v1 (`lib/types.ts`, `desktop/db.js`, `lib/supabase-queries.ts`, `lib/print-service.ts`, `app/(app)/waiter/`, `components/order/order-composer.tsx`).

> Старая серия `docs/00-INDEX.md … docs/14-TESTS.md` устарела относительно кода — для v3 не используется.

---

## Цель MVP

Получить минимальную работающую систему ресторана из трёх независимых приложений, покрывающую базовый сценарий:

> Официант на планшете открывает стол, набирает заказ из меню, отправляет на кассу. Кассир за стойкой видит заказ, принимает оплату, термопринтер печатает гостевой чек, стол освобождается.

В MVP **не входят**: кухня, склад, финансы, аналитика, смены, скидки, мульти-платежи, синхронизация с облаком, аудит-лог, отчётность. Дорожная карта — [99-ROADMAP.md](99-ROADMAP.md).

## Три отдельных приложения

| Приложение | Стек | Где работает | Назначение |
|---|---|---|---|
| **`restos-backend`** | Django 5 + DRF + PostgreSQL 16 | Main POS-машина | REST API + admin. Без UI |
| **`restos-cashier`** | PySide6 6.7 (Python 3.12) | Та же main POS-машина | Десктоп кассира, оплата и печать |
| **`restos-waiter`** | Vite + React 19 + Capacitor (PWA / APK) | Android-планшет | Столы и заказ, только в LAN |

У каждого приложения свой репозиторий, своя сборка, свой релизный цикл. Cashier и waiter общего кода не имеют, общаются только через REST API backend'а.

## Топология

```
┌─────────────────── LAN ресторана ────────────────────┐
│  ┌──────── Main POS ─────────────────────────────┐   │
│  │  PostgreSQL 16                                │   │
│  │  Django + gunicorn @ :8000                    │   │
│  │  nginx @ :80 (static + /api/ proxy)           │   │
│  │  restos-cashier (PySide6) — отдельный процесс │   │
│  │  Термопринтер ESC/POS (USB или TCP :9100)     │   │
│  └───────────────────────────────────────────────┘   │
│         ▲                                            │
│         │ http /api/v1/                              │
│  ┌──────┴───────┐  ┌──────────────┐                  │
│  │ Планшет      │  │ Планшет      │  ...             │
│  │ restos-waiter│  │ restos-waiter│                  │
│  └──────────────┘  └──────────────┘                  │
└──────────────────────────────────────────────────────┘
```

Облака нет. PWA отдаётся nginx'ом с main POS.

## Документы

| Файл | Содержание |
|---|---|
| [01-API-CONTRACT.md](01-API-CONTRACT.md) | Сквозной контракт REST API — единственный шов между приложениями |
| [backend/B-00-OVERVIEW.md](backend/B-00-OVERVIEW.md) | Стек backend, структура проекта, settings, миграции |
| [backend/B-01-AUTH.md](backend/B-01-AUTH.md) | JWT для PWA + PIN-сессия для PySide, роли cashier/waiter |
| [backend/B-02-TABLES.md](backend/B-02-TABLES.md) | Zone, Table — модели/сервисы/эндпоинты |
| [backend/B-03-MENU.md](backend/B-03-MENU.md) | Category, MenuItem |
| [backend/B-04-ORDERS.md](backend/B-04-ORDERS.md) | **Ядро.** Order, OrderItem, lifecycle, services, эндпоинты |
| [backend/B-05-PRINTING.md](backend/B-05-PRINTING.md) | Printer, PrintJob, ESC/POS service, очередь печати |
| [backend/B-06-EVENTS.md](backend/B-06-EVENTS.md) | SSE `/events/`, Postgres LISTEN/NOTIFY, каталог событий |
| [cashier/C-00-OVERVIEW.md](cashier/C-00-OVERVIEW.md) | PySide6 стек, структура проекта, сборка PyInstaller |
| [cashier/C-01-SCREENS.md](cashier/C-01-SCREENS.md) | 5 экранов MVP кассира |
| [cashier/C-02-HTTP-CLIENT.md](cashier/C-02-HTTP-CLIENT.md) | HTTP-клиент, SSE-стрим в QThread, PIN-сессия |
| [cashier/C-03-PRINTING.md](cashier/C-03-PRINTING.md) | Триггер печати на backend, статус задания |
| [waiter/W-00-OVERVIEW.md](waiter/W-00-OVERVIEW.md) | PWA стек, структура, сборка |
| [waiter/W-01-SCREENS.md](waiter/W-01-SCREENS.md) | 4 экрана MVP официанта |
| [waiter/W-02-API-CLIENT.md](waiter/W-02-API-CLIENT.md) | axios + interceptors, JWT, кэш меню |
| [waiter/W-03-DRAFTS.md](waiter/W-03-DRAFTS.md) | Черновики корзины в localStorage |
| [superadmin/SA-00-OVERVIEW.md](superadmin/SA-00-OVERVIEW.md) | **Vendor-панель** — лицензии, биллинг, телеметрия, саппорт |
| [90-DEPLOY-LAN.md](90-DEPLOY-LAN.md) | Установка на main POS, бэкапы, принтер |
| [99-ROADMAP.md](99-ROADMAP.md) | Что после MVP |

---

## Сквозные соглашения API

- База: `http://<main-pos>:80/api/v1/`
- Авторизация: `Authorization: Bearer <jwt>` (PWA) или `Authorization: PIN <session_token>` (PySide)
- Формат успеха: `{"data": {...}, "meta": {...}}`
- Формат ошибки: `{"error": {"code": "ORDER_ALREADY_CLOSED", "message": "...", "detail": {}}}`
- Все мутации в `transaction.atomic()`. На write-эндпоинты — заголовок `Idempotency-Key: <uuid>`.
- Реалтайм через **Server-Sent Events**: один endpoint `GET /api/v1/events/` стримит изменения столов, заказов, заданий печати. Транспорт — Postgres `LISTEN/NOTIFY` под капотом, без Redis и Channels. Heartbeat каждые 15 секунд. Полный каталог событий — [backend/B-06-EVENTS.md](backend/B-06-EVENTS.md).
- Все суммы — `Decimal(14, 2)`, валюта из `Restaurant.currency` (TJS).
- Все datetime — UTC, отображение в `Asia/Dushanbe`.

## Каталог ошибок

| Код | HTTP | Смысл |
|---|---|---|
| `AUTH_INVALID_PIN` | 401 | Неверный PIN кассира |
| `AUTH_INVALID_CREDENTIALS` | 401 | Неверный логин/пароль официанта |
| `AUTH_TOKEN_EXPIRED` | 401 | JWT просрочен |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | Не передан `Idempotency-Key` на write-эндпоинт |
| `PERMISSION_DENIED` | 403 | Роль не имеет доступа |
| `TABLE_NOT_FOUND` | 404 | Стол не существует |
| `TABLE_OCCUPIED` | 409 | Стол уже занят активным заказом |
| `ORDER_NOT_FOUND` | 404 | Заказ не существует |
| `ORDER_ALREADY_CLOSED` | 409 | Заказ уже оплачен |
| `ORDER_EMPTY` | 422 | Нельзя закрыть пустой заказ |
| `INVALID_TRANSITION` | 422 | Недопустимый переход статуса |
| `MENU_ITEM_UNAVAILABLE` | 422 | Блюдо `is_available=false` |
| `PRINTER_UNAVAILABLE` | 503 | Принтер недоступен (заказ всё равно закрывается, чек уйдёт в очередь) |

## Acceptance criteria

MVP сдан, когда:

1. `deploy/install.sh` (Linux) разворачивает backend + nginx + cashier + PWA-статику за < 15 минут.
2. Из Django admin создаются: 1 ресторан, 1 кассир + 2 официанта, 2 зоны, 6 столов, 3 категории, 12 блюд, 1 принтер.
3. Официант: логин → 6 столов → открывает свободный → 4 блюда → отправляет.
4. Кассир: PIN-логин → видит `bill_requested` → нажимает «Оплатить наличными».
5. Принтер печатает читаемый кириллический чек с шапкой, позициями и итогом.
6. Стол на обоих устройствах становится `free` в течение 1 секунды (через SSE).
7. При выдернутом сетевом кабеле планшета PWA показывает «нет сети ресторана» и не позволяет отправить заказ.
8. При выключенном принтере заказ всё равно закрывается, чек попадает в очередь, ретраится.
9. Двойной POST на `/orders/` с одинаковым `Idempotency-Key` создаёт один заказ.
