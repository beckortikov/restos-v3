# RestOS v3 — локальные правила

**Этот файл — источник правды по стеку для restos-v3** и переопределяет родительский [../CLAUDE.md](../CLAUDE.md) для всего, что находится в `restos-v3/`.

## Стек v3 (фиксирован)

| Часть | Стек | Папка | Агент трогает |
|---|---|---|---|
| Backend | Django 5 + DRF + PostgreSQL 16 + python-escpos | `apps/backend/` | **да** |
| POS (кассир) | PySide6 6.7 + Python 3.12 + requests + sseclient-py + apsw + keyring | `apps/pos/` | **да** |
| Waiter (планшет) | Kotlin 2.1 + Jetpack Compose + Material 3 + Retrofit + Hilt + DataStore (нативный Android) | `apps/waiter/` | **да** |
| Owner-dashboard | Next.js на Vercel (Phase 9) | `apps/dashboard/` | **нет — пропускать** |

Источник правды по требованиям: [prd-v3/00-INDEX.md](prd-v3/00-INDEX.md). MVP-scope: [prd-v3/00-INDEX.md#acceptance-criteria](prd-v3/00-INDEX.md). После-MVP: [prd-v3/99-ROADMAP.md](prd-v3/99-ROADMAP.md).

## Жёсткое правило: дизайн + PRD до кода (только cashier UI)

Любая задача, затрагивающая UI кассира (`apps/pos/pos/screens/**`, `apps/pos/pos/widgets/**`, любой `QWidget`/`QStackedWidget`) — **до первой правки кода** агент обязан вызвать skill [pos-screen](.claude/skills/pos-screen/SKILL.md) и выдать пользователю сводку (Шаг 5 из SKILL.md).

### Точно по дизайну, без отсебятины

- `.pen` читается **только через pencil MCP** (`mcp__pencil__open_document`, `batch_get`, `get_screenshot`, `get_variables`). Никаких `jq`, `Read`, `grep` по `.pen`.
- **`get_screenshot` обязателен** перед кодом — визуально сверять реализацию.
- Размеры карточек/кнопок/паддингов/gap'ов — **из дизайна** (1:1). Не «удобные округлые», не «адаптивные сами по себе» если в дизайне фикс. размер.
- `fill_container` = Expanding; отсутствие = `setFixedSize`. Не путать.
- Цвета — только из `$variables` (`mcp__pencil__get_variables`). Не выдумывать hex.
- Иконки — lucide. Точное `iconFontName` из дизайна → SVG в `pos/resources/icons.py`. Если нет — **добавить SVG-строку**, не fallback.
- При расхождении PRD ↔ дизайн — **спросить пользователя**.

В MVP реализуются **только 5 экранов** из [prd-v3/cashier/C-01-SCREENS.md](prd-v3/cashier/C-01-SCREENS.md):
1. PIN Login
2. TablesScreen (карта зала)
3. ActiveOrdersScreen
4. OrderDetail (модалка)
5. Payment + ReceiptStatus (модалки)

Остальные 19 frame'ов в [design/pos_cashier.pen](design/pos_cashier.pen) (смены, стоп-лист, отчёты, настройки и т.д.) — это Phase 2–8, в MVP **не трогаем**.

Триггеры обязательного вызова skill:
- упоминание любого из 5 MVP-экранов или их компонентов;
- любая правка файла под `apps/pos/`;
- запрос на коммит с тегом `feat(cashier)|fix(cashier)|refactor(cashier)|style(cashier)`.

При расхождении дизайн ↔ PRD — **остановиться и спросить пользователя**. Не выбирать молча.

## Правило: не ломать рабочее без согласования

**Любое изменение, затрагивающее уже работающий код вне границ непосредственной задачи — требует явного предупреждения пользователю и его одобрения до коммита.**

### Что считается «выходом за границы задачи»:
- Правка глобальных настроек приложения (`QApplication.setStyle`, `setPalette`, `app.setStyleSheet`).
- Изменение общих виджетов (`pos/widgets/*`), которые используются на нескольких экранах, при работе над одним экраном.
- Изменение базовых файлов (`main.py`, `state.py`, `http_client.py`, `tokens.py`, `icons.py`) при работе над фичей одного экрана/секции.
- Откат или замена паттернов, которые сейчас работают (даже если они «не идеальны»).
- Любые «попутные» рефакторинги «заодно».

### Как действовать:
1. Делай минимальное точечное изменение для своей задачи.
2. Если по дороге видишь, что нужна правка вне границ — **остановись, опиши пользователю** что именно ломается / что нужно менять, и **жди подтверждения**.
3. После каждой фичи — пиши тест + прогоняй полный регресс. Если упало что-то ранее работавшее — это блокер, решай немедленно либо откати свою правку.
4. Не пиши «я заодно поправил X в 5 местах» — это и есть нарушение правила.

### Чек-лист при правке стилей / фона / palette:
- [ ] Затрагиваю ТОЛЬКО тот виджет/экран, о котором попросили.
- [ ] Если нужно глобально менять `QApplication`/`QPalette` — сначала спросил разрешение.
- [ ] Если правлю общий компонент (`Sidebar`, `OrderDetailPanel`, `CartPanel`) — пользователь явно попросил это сделать, или я его явно предупредил.
- [ ] Прогнал полный набор тестов перед заявлением «готово».
- [ ] Проверил визуально / через тесты, что соседние экраны не сломались.

## Архитектурное правило: НИКАКОГО хардкода бизнес-данных

**Любая бизнес-строка/список, которую владелец заведения может захотеть изменить — НЕ хардкодим в код, а кладём в БД с CRUD-эндпоинтом и UI настройки.**

Это ключевой архитектурный принцип RestOS. Каждый ресторан получает свой набор справочных данных, а агент-кассир/официант редактирует их через UI «Настройки», не зовя разработчика.

### Что обязано быть в БД (не в коде):
- **Причины отмены/возврата** (item / order / refund) — `apps/orders/models.py::CancelReason` (✓ сделано). Дефолты сидятся через миграцию + `post_save` сигнал на `Restaurant`. Источник правды для дефолтов — `apps/orders/defaults.py`.
- **Способы оплаты** — пока enum `PaymentMethod`, в Phase 2 переезжает в `PaymentProvider` (банк/терминал/наличка). Названия и комиссии — из БД.
- **Скидки и сервис** (10% / 15% / «День рождения» / «Постоянный клиент») — `apps/discounts/models.py::Discount` (Phase 4).
- **Тип печати** (kitchen / bar / receipt / pre-bill), назначение принтеров на категории — таблица `PrinterRoute` (Phase 2).
- **Шаблоны комментариев к блюдам** («Без лука», «Хорошо прожарить») — `MenuItemNote` (Phase 3).
- **Роли и права** — `User.role` enum + флаг `is_active`. Кастомные роли — Phase 5+.
- **Текстовые лейблы статусов столов/заказов** — пока `TextChoices`, локализация — i18n (Phase 6).

### Чек-лист перед мержем PR:
- [ ] Никаких хардкоженных русских/английских строк в `if/elif`-ветках бизнес-логики.
- [ ] Любой dropdown/чип-список с >2 вариантами — грузится из API, а не выписан массивом в коде.
- [ ] Если добавляется новый «справочник» — есть модель, миграция, CRUD-endpoint, UI в `pos/screens/settings_sections/`, дефолтный сидер через `post_save` Restaurant.
- [ ] В `pos/state.py` для справочника — lazy-load кэш + `invalidate_*` метод.
- [ ] В тестах — проверка cross-restaurant изоляции (один ресторан не видит причины другого).

### Что МОЖНО хардкодить:
- Технические enum'ы, которые завязаны на бизнес-логику ядра (`OrderStatus`, `TableStatus`, `OrderType`) — их семантика жёстко привязана к коду.
- Дефолтные значения для сидеров (см. `apps/orders/defaults.py`) — они нужны новым ресторанам как стартовая точка, но дальше живут в их БД.
- Layout-константы из дизайна (размеры, паддинги, hex-цвета токенов) — это технический контракт между дизайнером и кодом, не бизнес.

При сомнении: «может ли владелец `Кафе у Анвара` захотеть изменить это под себя?» → если **да**, то БД + UI; если **нет**, можно код.

## Backend-задачи

Для любой правки в `apps/backend/` — сначала прочитать соответствующий `prd-v3/backend/B-XX-*.md`:

| Тема | Документ |
|---|---|
| Скелет, settings, common | [B-00](prd-v3/backend/B-00-OVERVIEW.md) |
| Auth (JWT + PIN) | [B-01](prd-v3/backend/B-01-AUTH.md) |
| Tables / Zones | [B-02](prd-v3/backend/B-02-TABLES.md) |
| Menu | [B-03](prd-v3/backend/B-03-MENU.md) |
| Orders (ядро) | [B-04](prd-v3/backend/B-04-ORDERS.md) |
| Printing (ESC/POS) | [B-05](prd-v3/backend/B-05-PRINTING.md) |
| SSE events | [B-06](prd-v3/backend/B-06-EVENTS.md) |
| API-контракт (сквозной) | [01-API-CONTRACT.md](prd-v3/01-API-CONTRACT.md) |

Backend-инварианты (из родительского CLAUDE.md остаются актуальными в адаптированном виде):
- Все мутации БД — в `transaction.atomic()`.
- Идемпотентность: `Idempotency-Key: <uuid>` обязателен на всех write-эндпоинтах. Хранится 24ч, см. [01-API-CONTRACT.md](prd-v3/01-API-CONTRACT.md).
- `tenant_id` (`restaurant_id`) в коде каждого репозитория/сервиса (RLS у Postgres не используем).
- Validation: DRF-сериализаторы + DB CHECK constraints.
- ESC/POS hex генерация: snapshot-тесты.
- Формат ответов: `{"data": ..., "meta": ...}` / `{"error": {"code": ..., "message": ..., "detail": ...}}`. Каталог кодов — [01-API-CONTRACT.md#каталог-ошибок](prd-v3/01-API-CONTRACT.md).

## Жёсткое правило: миграции применять немедленно

**После любого `makemigrations` агент обязан в той же сессии выполнить `python manage.py migrate`** — на той же БД, что использует running-app пользователя. Не «оставить пользователю» — он работает в режиме bypass и не должен ловить `ProgrammingError: relation "X" does not exist` при следующем открытии экрана.

Тесты (pytest) создают свою тестовую БД с применением миграций — поэтому «278 passed» **не означает**, что running app работает. Running app использует продовую/dev БД, и без миграции там нет таблиц.

### Алгоритм агента при добавлении/изменении модели

1. Изменить `models.py`.
2. Сразу: `cd apps/backend && python manage.py makemigrations <app> --name <descriptive>`.
3. **Сразу**: `cd apps/backend && python manage.py migrate` (на dev-БД пользователя).
4. **Сразу после migrate** — если у пользователя запущен `runserver` (`ps aux | grep manage.py`), убить его и поднять заново. Auto-reload не сбрасывает Django ORM connection cache → можно поймать `column X does not exist` даже когда в БД колонка есть.
5. Прогнать тесты.
6. В summary в конце сообщения **отдельной строкой**:
   `✅ Migrations applied: <list of migration names>` + `✅ Backend restarted` (если был запущен).

Если миграции по какой-то причине применить нельзя (откат данных, опасные изменения) — **остановиться и спросить пользователя**, а не молча оставлять pending.

### Правило про БД

`config/settings/base.py` использует `DATABASE_URL` **без fallback** (была убрана опция `sqlite:///db.sqlite3`). Если переменной нет — приложение падает при старте с понятной ошибкой. Используем **только Postgres**.

### Если уже накопились pending-миграции

Запустить разово:
```bash
cd apps/backend && python manage.py showmigrations | grep "\[ \]"
cd apps/backend && python manage.py migrate
```

И подтвердить пользователю чек-лист, что всё применено.

## Что агент НЕ трогает

Скоуп агента в этом проекте — **backend + POS-кассир + Waiter (нативный Android)**. Всё остальное существует в плане проекта (см. PRD), но пишется не агентом.

- `apps/waiter/` (нативный Android официанта) — **в скоупе**. Stack: Kotlin 2.1 + Jetpack Compose + Material 3 + Retrofit/OkHttp + Hilt + DataStore + kotlinx.serialization + Coil. PIN-login через `POST /api/v1/auth/waiter/pin/`, JWT в DataStore. См. [prd-v3/waiter/](prd-v3/waiter/). Дизайн-референс — `/Users/behzod/Documents/projects/restos/` (React waiter v1, берём только визуал/UX).
- `apps/dashboard/` (Owner-dashboard, Next.js, Phase 9) — пропускаем. На запрос вида «сделай дашборд / owner / Next.js / Vercel» — отказать и напомнить, что это вне скоупа агента.

Owner-dashboard всё ещё вне скоупа — это для другой команды и/или Phase 9.

## Команды

```bash
# Backend
cd apps/backend && python manage.py runserver 0.0.0.0:8000
cd apps/backend && python manage.py migrate
cd apps/backend && python manage.py print_worker          # отдельный процесс
cd apps/backend && pytest

# POS (кассир)
cd apps/pos && python -m pos
cd apps/pos && pytest
cd apps/pos && pyinstaller pos.spec

# Waiter (нативный Android, Kotlin)
cd apps/waiter && ./gradlew :app:assembleDebug                 # debug APK
cd apps/waiter && ./gradlew :app:installDebug                  # установить на подключённый девайс/эмулятор
cd apps/waiter && ./gradlew :app:assembleRelease               # release APK
cd apps/waiter && ./gradlew :app:test                          # unit-тесты
# Перед сборкой APK для планшета — поменять API_BASE_URL в app/build.gradle.kts
# (по умолчанию 10.0.2.2:8000 для Android-эмулятора, на устройстве — IP машины с Django).
```

## Версии

- Python 3.12
- PostgreSQL 16
- PySide6 6.7
- Django 5.x, DRF 3.15+
- Kotlin 2.1, AGP 8.7+, JDK 17, Android compileSdk 35 / minSdk 26 (waiter)

## Коммиты

- Backend: `feat(backend): …`, `fix(backend): …`, и т.д.
- Cashier UI: первая строка обязана содержать имя frame'а из `pos_cashier.pen` слово в слово, например:
  ```
  feat(cashier): implement screen "1. PIN Login"
  ```
- Waiter (Android): `feat(waiter): …`, `fix(waiter): …`. Дизайн-референс берём из `/Users/behzod/Documents/projects/restos/` (React-приложение v1) — только визуал/UX, никакого Capacitor, никаких pnpm-команд.
