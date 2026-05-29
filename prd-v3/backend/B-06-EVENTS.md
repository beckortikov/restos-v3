# B-06 — Real-time через SSE

В MVP реальное время делаем через **Server-Sent Events** (`text/event-stream`). Один endpoint `/api/v1/events/` транслирует все обновления — таблицы, заказы, задания печати — клиентам этого ресторана.

WebSocket не используем: он двусторонний (нам не нужно), требует Channels+Redis или Daphne, плохо переживает sleep планшетов и рестарты воркеров. SSE — обычный HTTP, переживает любой proxy/firewall, имеет встроенный авто-reconnect в браузере (`EventSource`), и его легко проксирует nginx.

## Транспорт

- Endpoint: `GET /api/v1/events/`.
- `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` (отключаем буферизацию nginx).
- Авторизация — `Authorization: Bearer <jwt>` (PWA) или `Authorization: PIN <token>` (PySide). Для `EventSource` в браузере (который не умеет ставить заголовки) — fallback `?token=<...>`.
- Heartbeat: пустой комментарий `:\n\n` каждые **15 секунд**, чтобы прокси не закрывали idle-коннекцию.
- Last-Event-ID: каждое событие имеет инкрементальный `id:`. При reconnect клиент шлёт `Last-Event-ID: N` (либо `?since=N`), сервер досылает пропущенные события.

Пример потока:

```
:ok
id: 142
event: table.updated
data: {"id": 7, "status": "bill_requested", "current_order_id": 42, "updated_at": "..."}

id: 143
event: order.updated
data: {"id": 42, "status": "bill_requested", "total": "98.00", "table_id": 7, "updated_at": "..."}

:heartbeat
```

## Каталог событий

| `event` | Кто получает | Когда отправляется | Payload |
|---|---|---|---|
| `table.updated` | оба | при `update` строки `tables` | минимальный `{id, status, current_order_id, updated_at}` |
| `order.created` | оба (waiter — только свой) | `INSERT orders` | минимальный `{id, status, table_id, waiter_id, total, updated_at}` |
| `order.updated` | оба (waiter — только свой) | `UPDATE orders` | то же |
| `print_job.updated` | cashier | `UPDATE print_jobs` | `{id, status, retries, error}` |
| `menu.invalidated` | оба | `UPDATE/INSERT menu_items|menu_categories` | `{etag}` — клиент идёт за свежим меню |

Полные данные сущностей клиент тянет по обычным `GET /orders/{id}/`, `/tables/`, `/menu/items/` — по событию он понимает, **что именно** перезапросить, а не получает в SSE всю модель.

## Архитектура

```
┌─────────────────── Backend ────────────────────────────┐
│                                                         │
│  Django models                                          │
│   ├─ post_save signal                                   │
│   │     │                                               │
│   │     ▼                                               │
│   │  apps.events.dispatch.publish(event_type, payload)  │
│   │     │                                               │
│   │     ▼                                               │
│   │  pg_notify('restos_events', json_payload)           │
│   │                                                     │
│  PostgreSQL          ◄── LISTEN restos_events ──┐       │
│                                                  │      │
│  apps.events.sse_view (StreamingHttpResponse)    │      │
│   ├─ открывает свой psycopg connect()            │      │
│   ├─ LISTEN restos_events                        │      │
│   ├─ в цикле:                                    │      │
│   │     conn.notifies.get(timeout=15)            │      │
│   │     yield event_block(...)                   │      │
│   └─ heartbeat каждые 15 секунд                  │      │
└─────────────────────────────────────────────────────────┘
```

- **Django signals** ловят `post_save` на нужных моделях и вызывают `publish()`.
- **`publish()`** делает `cursor.execute("SELECT pg_notify(%s, %s)", ('restos_events', json))`.
- **`/events/` view** — `StreamingHttpResponse`, держит свой Postgres-коннект, `LISTEN restos_events`, читает `notifies`, фильтрует по правам/ресторану, стримит клиенту.

`pg_notify` доставит событие во все процессы gunicorn'а (а значит, во все висящие SSE-коннекты), без Redis и Channels.

## gunicorn config

Чтобы long-lived SSE не съедал воркер целиком:

```ini
# /opt/restos/backend/deploy/gunicorn.conf.py
worker_class = "gthread"
workers = 3
threads = 16          # каждый воркер обслуживает 16 одновременных SSE-коннектов
timeout = 0            # без auto-kill для long requests
graceful_timeout = 30
keepalive = 75
```

Для 3 × 16 = 48 одновременных подключений хватит на LAN ресторана с большим запасом (3 кассира × 1 SSE + 20 планшетов × 1 SSE).

`timeout = 0` — критично: дефолтные 30 с убьют поток через полминуты.

## nginx

```nginx
location /api/v1/events/ {
    proxy_pass http://restos_backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 24h;
    proxy_send_timeout 24h;
    chunked_transfer_encoding on;
    add_header X-Accel-Buffering no;
}
```

Без `proxy_buffering off` nginx копит ответ и отдаёт пакетами по 8 KB — задержка обновления вырастает до 5–10 секунд.

## Реализация: триггеры на моделях

```python
# apps/events/dispatch.py
import json
from django.db import connection

CHANNEL = "restos_events"

def publish(event_type: str, restaurant_id: int, payload: dict):
    msg = json.dumps({
        "type": event_type,
        "restaurant_id": restaurant_id,
        "payload": payload,
    }, default=str)
    with connection.cursor() as c:
        c.execute("SELECT pg_notify(%s, %s)", [CHANNEL, msg])
```

```python
# apps/events/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.tables.models import Table
from apps.orders.models import Order
from apps.printing.models import PrintJob
from apps.menu.models import MenuItem, Category

from .dispatch import publish


@receiver(post_save, sender=Table)
def _table_saved(sender, instance: Table, **kw):
    publish("table.updated", instance.restaurant_id, {
        "id": instance.id,
        "status": instance.status,
        "current_order_id": instance.current_order_id,
        "updated_at": instance.updated_at.isoformat(),
    })

@receiver(post_save, sender=Order)
def _order_saved(sender, instance: Order, created, **kw):
    publish("order.created" if created else "order.updated",
            instance.restaurant_id, {
        "id": instance.id,
        "status": instance.status,
        "table_id": instance.table_id,
        "waiter_id": instance.waiter_id,
        "total": str(instance.total),
        "updated_at": instance.updated_at.isoformat(),
    })

@receiver(post_save, sender=PrintJob)
def _printjob_saved(sender, instance: PrintJob, **kw):
    publish("print_job.updated", instance.restaurant_id, {
        "id": instance.id,
        "status": instance.status,
        "retries": instance.retries,
        "error": instance.error[:200],
    })

@receiver(post_save, sender=MenuItem)
@receiver(post_save, sender=Category)
def _menu_changed(sender, instance, **kw):
    publish("menu.invalidated", instance.restaurant_id, {})
```

`apps/events/apps.py`:

```python
class EventsConfig(AppConfig):
    name = "apps.events"
    def ready(self):
        from . import signals   # noqa: F401
```

**Важно:** `publish()` вызывается из той же транзакции, что и `save()`. Pg_notify работает on commit (по умолчанию для psycopg в default isolation). Если транзакция откатится — события не уйдёт. Это правильное поведение.

## Реализация: SSE view

```python
# apps/events/views.py
import json, time, queue
import psycopg
from django.conf import settings
from django.http import StreamingHttpResponse, HttpResponseForbidden
from rest_framework.permissions import IsAuthenticated

from .dispatch import CHANNEL


HEARTBEAT_INTERVAL = 15
QUEUE_TIMEOUT = 15


def event_stream(request):
    user = request.user
    restaurant_id = user.restaurant_id
    role = user.role

    since = request.GET.get("since") or request.headers.get("Last-Event-ID") or "0"
    last_id = [int(since)]

    def gen():
        # отдельный коннект, чтобы LISTEN не блокировал общий пул
        with psycopg.connect(settings.DATABASES["default"]["URL"], autocommit=True) as conn:
            conn.execute(f"LISTEN {CHANNEL}")
            yield ":ok\n\n"

            last_heartbeat = time.time()
            while True:
                # ждём следующего notify не дольше, чем до heartbeat
                wait = max(1, HEARTBEAT_INTERVAL - (time.time() - last_heartbeat))
                conn.execute("SELECT 1")  # пинг
                got_notify = False
                for n in conn.notifies(timeout=wait):
                    got_notify = True
                    msg = json.loads(n.payload)
                    if msg["restaurant_id"] != restaurant_id:
                        continue
                    if not _allowed(msg, user):
                        continue
                    last_id[0] += 1
                    yield (f"id: {last_id[0]}\n"
                           f"event: {msg['type']}\n"
                           f"data: {json.dumps(msg['payload'])}\n\n")
                if not got_notify and (time.time() - last_heartbeat) >= HEARTBEAT_INTERVAL:
                    yield ":heartbeat\n\n"
                    last_heartbeat = time.time()


def _allowed(msg: dict, user) -> bool:
    """Минимальная фильтрация по ролям. Полные данные клиент всё равно тянет
    через REST с правами; здесь только избавляемся от шума."""
    t = msg["type"]
    p = msg["payload"]
    if user.role == "waiter":
        if t in ("order.created", "order.updated") and p.get("waiter_id") not in (None, user.id):
            return False
        if t == "print_job.updated":
            return False     # официанту чек неинтересен
    return True


class EventStreamView(View):
    def get(self, request):
        # auth — DRF authenticators (см. apps.users.auth)
        if not request.user.is_authenticated:
            return HttpResponseForbidden()
        resp = StreamingHttpResponse(event_stream(request),
                                     content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp
```

`urls.py`:

```python
urlpatterns = [
    path("events/", EventStreamView.as_view(), name="sse-events"),
]
```

DRF authenticator для PIN-сессии и JWT тут используется через стандартный middleware (мы их подключили в `DEFAULT_AUTHENTICATION_CLASSES`). Также нужно поддержать `?token=...` для браузерного `EventSource`:

```python
# apps/users/auth.py — расширение

class TokenQueryParamAuthentication(BaseAuthentication):
    """Используется только для GET /events/ (EventSource не умеет заголовки)."""
    def authenticate(self, request):
        if request.path != "/api/v1/events/":
            return None
        token = request.GET.get("token")
        if not token:
            return None
        # пробуем как JWT
        try:
            validated = JWTAuthentication().get_validated_token(token)
            user = JWTAuthentication().get_user(validated)
            return (user, validated)
        except Exception:
            pass
        # пробуем как PIN session
        try:
            session = PinSession.objects.select_related("user").get(token=token)
            if session.is_valid():
                return (session.user, session)
        except PinSession.DoesNotExist:
            pass
        raise AuthenticationFailed("invalid token")
```

## Last-Event-ID и пропущенные события

Поскольку события у нас идут через `pg_notify` (он не персистентный), при reconnect мы не можем «доиграть» точные пропуски. Подход проще:

1. Клиент сохраняет `Last-Event-ID` в localStorage.
2. На reconnect — отдаёт его в заголовке. Сервер игнорирует, **но** в первом сообщении после `:ok` стримит синтетический `event: resync` с пустым payload.
3. Клиент на `resync` форсированно перезапрашивает `/tables/`, `/orders/?status=new,bill_requested`, `/menu/items/` (если ETag поменялся) — точечная репликация состояния.

Это компромисс: вместо сложной системы хранения events мы просто говорим клиенту «sync!». Для нашего профиля нагрузки — окей.

```python
# в gen() сразу после :ok:
yield "event: resync\ndata: {}\n\n"
```

Клиент всегда стартует с full sync — это упрощает сценарии и одновременно устраняет нужду в Last-Event-ID на сервере.

## Что меняется в других модулях

- **B-02 Tables, B-03 Menu, B-04 Orders** — убираются `/poll/` actions. Клиент получает уведомление «что-то в orders изменилось» и сам идёт за деталями.
- **C-02 Cashier HTTP-client** — `Poller` (QThread) переименовывается в `EventClient` (см. C-02 в обновлённой версии). Использует `requests.get(stream=True)` + парсинг SSE-формата (либо `sseclient-py`).
- **W-02 Waiter API-client** — `react-query` `refetchInterval` убирается. Вместо этого один `useEventSource` хук, который слушает `/events/` и через `queryClient.invalidateQueries(...)` дёргает react-query на пересборку.
- **00-INDEX, 01-API-CONTRACT** — secured: всюду «polling 5 сек» заменено на «SSE с heartbeat 15 сек».

## Acceptance criteria для SSE

1. Открыть DevTools на waiter-планшете → `Network` → `EventStream` → видны heartbeat'ы каждые 15 с.
2. На втором планшете запросить счёт → у первого в DevTools EventStream появляется `event: order.updated` за < 1 с.
3. `kill -9` Django backend → клиент через 1–2 с показывает `Offline`. После рестарта — авто-reconnect, и `event: resync` приводит UI в актуальное состояние.
4. Открыть 30 SSE-сессий одновременно → gunicorn `gthread` × 3 × 16 = 48 — все обслужены, нагрузка CPU < 10 %.
5. Положить планшет «спать» на 5 минут → при пробуждении EventSource сам пересоединится (heartbeat пропуска ломает коннект, browser/Capacitor открывают новый), приходит `resync`.
