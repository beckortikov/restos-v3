# C-00 — Cashier app: обзор

Десктоп-приложение кассира на **PySide6**. Запускается на main POS-машине бок-о-бок с Django backend'ом, общается с ним по `http://127.0.0.1:8000/api/v1/`.

В MVP кассир НЕ создаёт заказ через меню — это делает официант с PWA. Кассир только:
- логинится PIN'ом,
- видит карту зала и активные заказы,
- принимает оплату по `bill_requested` заказам,
- видит статус печати чека и при ошибке нажимает «повторить».

## Стек

| Компонент | Назначение |
|---|---|
| Python 3.12 | runtime |
| PySide6 6.7 | UI |
| `requests` 2.x | HTTP-клиент к Django |
| `sseclient-py` | парсинг SSE-потока `/events/` |
| `apsw` | локальный SQLite-кэш меню (read-only) |
| `keyring` | хранение PIN-session_token в системном keychain |
| `pytest-qt` | тесты UI |
| PyInstaller 6.x | сборка одного EXE/APP |

**Не используем**: Qt for Python WebEngine, QML (всё на QtWidgets — стабильнее и быстрее на слабом железе).

## Структура проекта

```
restos-cashier/
├── pos/
│   ├── main.py                # QApplication, навигация
│   ├── config.py              # API_BASE_URL, SSE_RECONNECT_DELAY_S, RESTAURANT_ID
│   ├── http_client.py         # см. C-02
│   ├── sse_client.py          # QThread, держит SSE-стрим /events/, эмитит сигналы
│   ├── state.py               # Singleton + Qt-сигналы (orders_changed, tables_changed)
│   ├── auth/
│   │   ├── pin_login_screen.py
│   │   └── session.py         # хранение session_token в keyring
│   ├── screens/               # см. C-01
│   │   ├── tables_screen.py
│   │   ├── active_orders.py
│   │   ├── order_detail.py
│   │   ├── payment.py
│   │   └── receipt_status.py
│   ├── widgets/
│   │   ├── numpad.py
│   │   ├── order_card.py
│   │   └── status_badge.py
│   └── resources/
│       └── styles.qss
├── tests/
│   ├── test_http_client.py
│   ├── test_payment_flow.py
│   └── conftest.py            # pytest-qt fixtures
├── pyinstaller.spec
├── requirements.txt
├── README.md
└── pyproject.toml
```

## Запуск

### Dev

```bash
cd restos-cashier
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
RESTOS_API_URL=http://127.0.0.1:8000 python -m pos.main
```

### Production

PyInstaller собирает один файл:

```bash
pyinstaller pyinstaller.spec
# → dist/restos-cashier.exe / .app / .deb
```

`pos.config` читает `RESTOS_API_URL` и `RESTOS_RESTAURANT_ID` из переменных окружения, по умолчанию — `http://127.0.0.1:8000` и `1`. На production-машине эти переменные ставятся в systemd-юните или ярлыке Windows.

## Поведение и принципы

- **Никаких прямых обращений в БД.** Только REST. Это гарантирует, что cashier-app ничем не отличается от waiter-PWA с точки зрения backend'а.
- **SSE, не WebSocket.** `SseClient` (QThread) держит долгоживущий `GET /events/`, парсит поток и эмитит Qt-сигналы при поступлении событий. Экраны подписываются через `state.py`. На обрыв связи — авто-reconnect через 2 с с тем же session_token.
- **Нет shared mutable state.** Только Qt-сигналы и слоты — это чистый message-passing, проще тестировать и отлаживать.
- **Auto-lock.** Таймер бездействия (`Restaurant.pin_lock_timeout_min`, default 30 мин) перекидывает на PIN Login. Сессия на сервере не инвалидируется (в backend'е TTL продлевается только при HTTP-запросах) — повторный ввод PIN при ещё живой сессии возвращает тот же session_token.
- **Идемпотентность.** Каждый POST на `/orders/{id}/close/` шлётся с `Idempotency-Key=uuid()`. При тыке двойного клика по «Оплатить» backend ответит тем же payload, ничего не дублируется.
- **Графика.** Кассирский UI — крупный, кнопки ≥ 56 px высотой, шрифты ≥ 16 pt. Цвета статусов:
  - `free` — `#9CA3AF` (серый)
  - `occupied` — `#F59E0B` (оранжевый)
  - `bill_requested` — `#EF4444` (красный, мигает 1 раз/сек)

## Сборка PyInstaller

`pyinstaller.spec`:

```python
# pyinstaller.spec
a = Analysis(
    ['pos/main.py'],
    datas=[('pos/resources', 'pos/resources')],
    hiddenimports=['PySide6.QtSvg', 'apsw', 'keyring.backends.macOS',
                   'keyring.backends.Windows', 'keyring.backends.SecretService'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas,
          name='restos-cashier', icon='pos/resources/icon.ico', console=False)
```

Авто-обновление через GitHub Releases — Phase 2.

## Acceptance

- При запуске сразу попадаем на PIN Login.
- После успешного ввода PIN — на «Карта зала».
- При выключенном backend'е — экран «Нет связи с сервером, повтор через 5 с» с авто-retry.
- При закрытии Django (`systemctl stop restos-backend`) cashier продолжает работать; SSE-коннект обрывается, в правом нижнем углу — индикатор «Offline». При возврате backend'а — авто-reconnect, и через `event: resync` UI самовосстанавливается.
