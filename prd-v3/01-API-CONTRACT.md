# 01 — API-контракт

Этот документ — **единственный шов** между тремя приложениями. Cashier и waiter общаются с backend только через эти эндпоинты.

База: `http://<main-pos>/api/v1/`. Все запросы — JSON, кодировка UTF-8.

## Заголовки

| Заголовок | Когда |
|---|---|
| `Authorization: Bearer <jwt>` | Запросы от waiter (PWA) |
| `Authorization: PIN <session_token>` | Запросы от cashier (PySide) |
| `Idempotency-Key: <uuid>` | Все `POST` на write-эндпоинты (`/orders/`, `/orders/*/close/`, `/orders/*/cancel/`) |
| `If-None-Match: "<etag>"` | На `GET /menu/items/` для cache-аware клиента |

## Формат ответов

Успех:
```json
{ "data": { "...": "..." }, "meta": { "total": 42, "page": 1 } }
```

Ошибка:
```json
{ "error": { "code": "ORDER_ALREADY_CLOSED", "message": "Заказ уже закрыт", "detail": {} } }
```

## Реестр эндпоинтов

### Auth

```
POST   /api/v1/auth/login/           PWA: {username, password} → {access, refresh, user}
POST   /api/v1/auth/refresh/         PWA: {refresh} → {access}
POST   /api/v1/auth/pin/             PySide: {pin} → {session_token, user, expires_at}
POST   /api/v1/auth/pin/logout/      PySide: invalidate session_token
GET    /api/v1/auth/me/              текущий user + restaurant
```

Пример `POST /auth/pin/`:
```json
// req
{ "pin": "1234" }
// resp 200
{ "data": {
    "session_token": "8f3e...c2",
    "user": { "id": 1, "full_name": "Анна", "role": "cashier" },
    "expires_at": "2026-05-06T17:00:00Z"
}}
```

### Tables

```
GET    /api/v1/tables/zones/          → [{id, name, sort_order}]
GET    /api/v1/tables/                 ?zone=1&status=free
POST   /api/v1/tables/{id}/open/       waiter: {guests_count} → table
```

Обновления столов идут через SSE (`event: table.updated`), не через polling.

### Menu

```
GET    /api/v1/menu/categories/        → [{id, name, sort_order}]
GET    /api/v1/menu/items/             ?category=1&is_available=true
                                        ETag в заголовке, 304 если не изменилось
```

Пример `GET /menu/items/?category=2`:
```json
{ "data": [
    {"id":17,"category":2,"name":"Плов","price":"45.00","emoji":"🍚",
     "image_url":"/media/menu/plov.jpg","is_available":true,"sort_order":1}
], "meta":{"total":1}}
```

### Orders

```
GET    /api/v1/orders/                ?status=bill_requested
POST   /api/v1/orders/                создать (idempotency обяз.)
GET    /api/v1/orders/{id}/            детали с items
POST   /api/v1/orders/{id}/add_items/  {items:[{menu_item_id,qty}]}
POST   /api/v1/orders/{id}/cancel_item/ {item_id, reason}
POST   /api/v1/orders/{id}/request_bill/ waiter
POST   /api/v1/orders/{id}/close/      cashier: {payment_method}
POST   /api/v1/orders/{id}/cancel/     {reason}
```

Обновления заказов идут через SSE (`event: order.created` / `order.updated`).

Пример `POST /orders/`:
```json
// req
{
  "table_id": 12,
  "guests_count": 3,
  "items": [
    { "menu_item_id": 17, "qty": 2 },
    { "menu_item_id": 23, "qty": 1 }
  ]
}
// headers: Idempotency-Key: 9f7a...

// resp 201
{ "data": {
  "id": 1042,
  "status": "new",
  "table": {"id":12, "name":"Стол 5"},
  "waiter": {"id":3, "full_name":"Карим"},
  "guests_count": 3,
  "items": [
    {"id":2087, "menu_item_id":17, "name_at_order":"Плов",
     "price_at_order":"45.00", "qty":2, "subtotal":"90.00"},
    {"id":2088, "menu_item_id":23, "name_at_order":"Чай",
     "price_at_order":"8.00", "qty":1, "subtotal":"8.00"}
  ],
  "total": "98.00",
  "created_at": "2026-05-06T13:42:11Z"
}}
```

Пример `POST /orders/1042/close/`:
```json
// req
{ "payment_method": "cash" }
// headers: Idempotency-Key: <uuid>

// resp 200
{ "data": {
  "order": { "id": 1042, "status": "done", "closed_at":"...", "total":"98.00" },
  "print_job": { "id": 7711, "status": "pending" }
}}
```

### Printing

```
GET    /api/v1/printing/printers/      список принтеров
GET    /api/v1/printing/jobs/{id}/     {id,status,retries,error,scheduled_at}
POST   /api/v1/printing/jobs/{id}/retry/ форсировать повтор
```

Статус задания печати идёт через SSE (`event: print_job.updated`).

### Events (SSE)

```
GET    /api/v1/events/                 text/event-stream
       Headers: Authorization: Bearer <jwt> | PIN <token>
       Или для EventSource из браузера: ?token=<jwt>
       Опц.: Last-Event-ID или ?since=<n>
```

Один поток на клиента. Сервер шлёт:

| event | payload |
|---|---|
| `table.updated` | `{id, status, current_order_id, updated_at}` |
| `order.created` | `{id, status, table_id, waiter_id, total, updated_at}` |
| `order.updated` | то же |
| `print_job.updated` | `{id, status, retries, error}` (только cashier) |
| `menu.invalidated` | `{}` — клиент идёт за свежим меню по ETag |
| `resync` | `{}` — синтетическое сразу после reconnect, клиент перечитывает базовое состояние |

Heartbeat — `:heartbeat\n\n` каждые 15 секунд, чтобы прокси не закрывали idle-соединение.

## Server-Sent Events vs polling

В MVP **используем SSE**, не polling. Причины:
- Меньше латентность (мгновенно vs 5 с).
- Меньше нагрузка: один long-lived коннект на клиента вместо N запросов в минуту.
- Транспорт — обычный HTTP, проксируется любым nginx без особой настройки.
- Без Redis/Channels: используем Postgres `LISTEN/NOTIFY` (см. backend/B-06-EVENTS.md).
- `EventSource` в браузере имеет встроенный auto-reconnect, не надо писать heartbeat-логику.

WebSocket не нужен: двусторонняя связь нам не требуется, всё, что нам нужно от сервера в реальном времени — push, и SSE его покрывает.

## Идемпотентность

Все `POST` на `/orders/`, `/orders/*/close/`, `/orders/*/cancel/` обязаны нести `Idempotency-Key: <uuid>`.

Сервер хранит таблицу `IdempotencyRecord(key, response_body, response_status, created_at)` 24 часа. При повторе с тем же ключом — возвращает тот же ответ без повторного выполнения.

Без ключа → `400 IDEMPOTENCY_KEY_REQUIRED`.
