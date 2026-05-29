# apps/pos — Cashier desktop (PySide6)

Десктоп-приложение кассира для RestOS v3. PySide6 6.7 + Python 3.12. Запускается на main POS-машине бок-о-бок с backend'ом, общается с ним по `http://127.0.0.1:8000/api/v1/`.

ТЗ: [../../prd-v3/cashier/C-00-OVERVIEW.md](../../prd-v3/cashier/C-00-OVERVIEW.md). Экраны: [../../prd-v3/cashier/C-01-SCREENS.md](../../prd-v3/cashier/C-01-SCREENS.md). Дизайн: [../../design/pos_cashier.pen](../../design/pos_cashier.pen).

## Скоуп MVP (5 экранов)

1. PIN Login
2. TablesScreen (карта зала)
3. ActiveOrdersScreen
4. OrderDetail (модалка)
5. Payment + ReceiptStatus (модалки)

Остальные 19 frame'ов в `pos_cashier.pen` — Phase 2..8, в MVP не реализуются. Перед любой UI-задачей агент обязан вызвать skill `pos-screen` (см. [../../CLAUDE.md](../../CLAUDE.md)).

## Структура

```
apps/pos/
├── pos/
│   ├── __init__.py
│   ├── __main__.py            python -m pos
│   ├── app.py                 QApplication + main window
│   ├── state.py               глобальное состояние (auth, current_table)
│   ├── http_client.py         requests + PIN-session (C-02)
│   ├── sse_client.py          QThread + sseclient-py (C-02)
│   ├── screens/
│   │   ├── pin_login.py       1. PIN Login
│   │   ├── tables.py          2. TablesScreen
│   │   ├── active_orders.py   3. ActiveOrdersScreen
│   │   ├── order_detail.py    4. OrderDetail (модалка)
│   │   └── payment.py         5. Payment + ReceiptStatus
│   ├── widgets/               numpad.py, table_card.py, ...
│   └── services/              menu_cache.py (apsw), keyring helpers
├── tests/
├── resources/                 иконки, qrc
├── pos.spec                   PyInstaller (генерируется позже)
├── pyproject.toml
└── .python-version
```

## Команды

```bash
# из корня репо
cd apps/pos

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# dev (бэкенд должен быть запущен на :8000)
python -m pos

# тесты
pytest

# сборка
pyinstaller pos.spec
```

## Backend dependency

POS не запустится без работающего backend на `http://127.0.0.1:8000`. Стартовать backend: `cd ../backend && python manage.py runserver`.
