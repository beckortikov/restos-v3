# C-02 — HTTP-клиент и SSE-стрим

## `pos/http_client.py`

Тонкая обёртка над `requests.Session` с тремя задачами:
1. Подставлять `Authorization: PIN <session_token>`.
2. Auto-retry на сетевые ошибки (3 раза, exponential backoff 0.5 / 1 / 2 с).
3. Превращать ответы `{"data": ...}` в Python-объекты, а `{"error": ...}` — в исключения.

```python
# pos/http_client.py
import time, uuid, requests
from typing import Any
from pos.auth.session import SessionStore
from pos.config import API_BASE_URL


class ApiError(Exception):
    def __init__(self, code: str, message: str, http_status: int, detail: dict | None = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail or {}
        super().__init__(f"[{code}] {message}")


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.session_store = SessionStore()

    def _headers(self, idempotent: bool) -> dict:
        h = {"Accept": "application/json"}
        token = self.session_store.token
        if token:
            h["Authorization"] = f"PIN {token}"
        if idempotent:
            h["Idempotency-Key"] = str(uuid.uuid4())
        return h

    def request(self, method: str, path: str, *, json=None, params=None,
                idempotent: bool = False, retries: int = 3) -> Any:
        url = f"{self.base}/api/v1{path}"
        last_exc = None
        for i in range(retries):
            try:
                r = self.s.request(method, url, json=json, params=params,
                                    headers=self._headers(idempotent), timeout=10)
            except requests.RequestException as e:
                last_exc = e
                time.sleep(0.5 * (2 ** i))
                continue

            try:
                payload = r.json()
            except ValueError:
                payload = {}

            if r.status_code >= 400:
                err = payload.get("error", {})
                raise ApiError(
                    code=err.get("code", "HTTP_ERROR"),
                    message=err.get("message", r.text[:200]),
                    http_status=r.status_code,
                    detail=err.get("detail", {}),
                )
            return payload.get("data", payload)
        raise ApiError("NETWORK", str(last_exc), 0)

    # convenience
    def get(self, path, **kw):  return self.request("GET", path, **kw)
    def post(self, path, **kw): return self.request("POST", path, **kw)
```

`SessionStore` — обёртка над `keyring.set_password / get_password / delete_password` под сервисным именем `restos-cashier`.

## `pos/auth/session.py`

```python
import keyring
SERVICE = "restos-cashier"

class SessionStore:
    @property
    def token(self) -> str | None:
        return keyring.get_password(SERVICE, "session_token")

    @token.setter
    def token(self, value: str | None):
        if value is None:
            try: keyring.delete_password(SERVICE, "session_token")
            except keyring.errors.PasswordDeleteError: pass
        else:
            keyring.set_password(SERVICE, "session_token", value)
```

При логине `pin_login_screen` делает `client.post("/auth/pin/", json={"pin": pin})` и сохраняет `session_token`.

## `pos/sse_client.py`

`QThread`, который держит долгоживущий `GET /api/v1/events/`, парсит SSE-поток через `sseclient-py` и эмитит Qt-сигналы.

```python
# pos/sse_client.py
import json, time
import requests
import sseclient
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from pos.config import API_BASE_URL
from pos.auth.session import SessionStore


RECONNECT_DELAY_S = 2


class SseClient(QThread):
    table_updated     = Signal(dict)   # {id, status, current_order_id, updated_at}
    order_event       = Signal(str, dict)  # event_name, payload
    print_job_updated = Signal(dict)
    menu_invalidated  = Signal()
    resync            = Signal()
    network_error     = Signal(str)
    auth_expired      = Signal()

    def __init__(self, base_url: str = API_BASE_URL):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.session_store = SessionStore()
        self._stop = False
        self._mutex = QMutex()

    def stop(self):
        with QMutexLocker(self._mutex):
            self._stop = True

    def _stopped(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stop

    def run(self):
        while not self._stopped():
            try:
                self._stream_once()
            except requests.RequestException as e:
                self.network_error.emit(str(e))
            if not self._stopped():
                time.sleep(RECONNECT_DELAY_S)

    def _stream_once(self):
        token = self.session_store.token
        if not token:
            self.auth_expired.emit()
            return

        headers = {"Authorization": f"PIN {token}", "Accept": "text/event-stream"}
        url = f"{self.base_url}/api/v1/events/"
        with requests.get(url, headers=headers, stream=True, timeout=(10, None)) as r:
            if r.status_code == 401:
                self.auth_expired.emit()
                return
            r.raise_for_status()
            client = sseclient.SSEClient(r)
            for ev in client.events():
                if self._stopped():
                    return
                self._dispatch(ev.event, ev.data)

    def _dispatch(self, event: str, raw: str):
        if not raw:    # heartbeat / empty data
            return
        try:
            payload = json.loads(raw)
        except ValueError:
            return

        if event == "table.updated":
            self.table_updated.emit(payload)
        elif event in ("order.created", "order.updated"):
            self.order_event.emit(event, payload)
        elif event == "print_job.updated":
            self.print_job_updated.emit(payload)
        elif event == "menu.invalidated":
            self.menu_invalidated.emit()
        elif event == "resync":
            self.resync.emit()
```

Что важно:

- **Reconnect.** При обрыве (network error, рестарт backend, sleep планшета) поток ловит исключение, ждёт 2 с, открывает заново. На каждое подключение backend сразу шлёт `event: resync` — UI знает, что нужно перечитать базовое состояние.
- **401.** Если сервер отказал в авторизации — эмитим `auth_expired`, главное окно переключается на PIN Login.
- **Heartbeat.** `sseclient-py` обрабатывает `:heartbeat` как пустую строку и не пробрасывает наверх — нам ничего не надо делать.
- **Один поток на клиента.** Нет необходимости в periodic timer — UI обновляется по push'у.

## Resync-протокол

`event: resync` приходит сразу после `:ok` каждого нового соединения. Получатель в `state.py` форсированно делает:

```python
def on_resync():
    state.tables_full.emit(client.get("/tables/"))
    state.orders_full.emit(client.get("/orders/?status=new,bill_requested"))
```

Это снимает риск пропустить событие при обрыве — мы просто заново получаем «снимок», а дальше идём по push'ам.

## `pos/state.py`

Singleton, держит текущие данные (tables и orders как dict id→row) и проксирует сигналы. Поддерживает «full snapshot» (приходит на resync) и инкрементальные обновления.

```python
# pos/state.py
from PySide6.QtCore import QObject, Signal
from pos.http_client import ApiClient
from pos.sse_client import SseClient


class State(QObject):
    tables_changed = Signal(list)   # full list[dict]
    orders_changed = Signal(list)
    online_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.client = ApiClient()
        self.sse: SseClient | None = None
        self.is_online = True
        self._tables: dict[int, dict] = {}
        self._orders: dict[int, dict] = {}

    def start_stream(self):
        self.sse = SseClient()
        self.sse.resync.connect(self._on_resync)
        self.sse.table_updated.connect(self._on_table)
        self.sse.order_event.connect(self._on_order)
        self.sse.network_error.connect(lambda _: self._set_online(False))
        self.sse.start()

    def stop_stream(self):
        if self.sse:
            self.sse.stop()
            self.sse.wait()
            self.sse = None

    def _on_resync(self):
        self._set_online(True)
        try:
            tables = self.client.get("/tables/")
            self._tables = {t["id"]: t for t in tables}
            self.tables_changed.emit(list(self._tables.values()))

            orders = self.client.get("/orders/", params={"status": "new,bill_requested"})
            self._orders = {o["id"]: o for o in orders}
            self.orders_changed.emit(list(self._orders.values()))
        except ApiError as e:
            self._set_online(False)

    def _on_table(self, row: dict):
        self._set_online(True)
        self._tables[row["id"]] = {**self._tables.get(row["id"], {}), **row}
        self.tables_changed.emit(list(self._tables.values()))

    def _on_order(self, event: str, row: dict):
        self._set_online(True)
        if row.get("status") in ("done", "cancelled"):
            self._orders.pop(row["id"], None)
        else:
            self._orders[row["id"]] = {**self._orders.get(row["id"], {}), **row}
        self.orders_changed.emit(list(self._orders.values()))

    def _set_online(self, value: bool):
        if value != self.is_online:
            self.is_online = value
            self.online_changed.emit(value)


state = State()
```

## Idempotency

Любая функция-обёртка для мутаций ставит `idempotent=True`:

```python
# pos/api/orders.py
def close_order(order_id: int, payment_method: str) -> dict:
    return state.client.post(
        f"/orders/{order_id}/close/",
        json={"payment_method": payment_method},
        idempotent=True,
    )
```

Двойной клик «Оплатить» в UI:
- Первый запрос ушёл с `Idempotency-Key=K1`, backend выполнил.
- Второй запрос (UI всё ещё лагает / клик прошёл дважды) — UUID **другой**; чтобы получить идемпотентность, мы должны сгенерировать ключ один раз и переиспользовать.

Поэтому правильный паттерн в UI:

```python
def on_pay_clicked(self):
    self.btn.setEnabled(False)
    self.idem_key = str(uuid.uuid4())
    self._submit()

def _submit(self):
    try:
        result = state.client.post(
            f"/orders/{self.order_id}/close/",
            json={"payment_method": self.method},
            extra_headers={"Idempotency-Key": self.idem_key},
        )
    except ApiError as e:
        if e.code == "NETWORK":
            QTimer.singleShot(2000, self._submit)   # ретрай с тем же ключом
            return
        ...
```

То есть `extra_headers` — параметр, расширение `request()`, чтобы переиспользовать тот же ключ при ретраях.

## Тесты

`tests/test_http_client.py`:

1. `test_pin_header_added` — после `session.token = "abc"` все запросы несут `Authorization: PIN abc`.
2. `test_idempotent_key_generated` — `idempotent=True` добавляет UUID-заголовок.
3. `test_4xx_raises_apierror_with_code` — backend возвращает `{"error": {"code": "TABLE_OCCUPIED", ...}}` → ApiError(code="TABLE_OCCUPIED", http_status=409).
4. `test_network_retry` — `requests` поднимает `ConnectionError` 2 раза, на 3-й возвращает 200 → результат получен.
5. `test_401_does_not_retry` — `network_error` НЕ ретраится, `ApiError` сразу.

`tests/test_sse_client.py`:

1. Mock SSE-сервер шлёт `:ok\n\nevent: resync\ndata: {}\n\n` → `resync` сигнал эмитится.
2. Шлёт `event: table.updated\ndata: {"id":7,...}` → `table_updated.emit({...})`.
3. Сервер отвечает 401 → `auth_expired` сигнал, поток завершается.
4. Сервер обрывает коннект → через 2 с поток поднимается заново; на новом коннекте снова приходит `resync`.
