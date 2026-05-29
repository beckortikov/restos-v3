# Super-Admin (Vendor Panel) — обзор

Панель **поставщика** RestOS (нас, vendor'а), а не владельца ресторана.
Управляет лицензиями, биллингом, телеметрией и саппортом всех клиентов
платформы.

> **Не путать с Owner-Dashboard.** Owner-Dashboard (Phase 9, Next.js на
> Vercel) — это для **владельца ресторана**: показывает его P&L, отчёты,
> аналитику ОДНОГО ресторана. Super-Admin — это для **нас**: видим все
> рестораны на платформе, управляем подписками.

## Текущее состояние (Фаза 0 — реализовано)

`apps/backend/apps/licensing/` — базовый foundation:

- **Модель `License`** — план / срок / блокировка / ключ
- **Поля `Restaurant.last_heartbeat_at` + `app_version`** — телеметрия живых
- **Endpoints** — `GET /license/status/`, `POST /heartbeat/`
- **Permission integration** — DRF `_enforce_license`, 402 LICENSE_EXPIRED
- **Auto-trial** — каждый новый Restaurant получает триал на 30 дней
- **Django admin** — `/admin/licensing/license/` с действиями «Продлить +30/+90/+365», «Заблокировать», «Разблокировать»
- **POS LicenseBanner** — баннер сверху всех экранов с warning'ами
- **POS heartbeat** — каждые 10 минут пинг с APP_VERSION

**Лимит текущего MVP:** ручное управление через Django admin. Подходит для
5-20 клиентов. Дальше — нужны фазы ниже.

---

## Фазы развития super-admin

### Фаза SA-1 — Impersonation + базовый дашборд (~6-8 ч)

**Когда нужно:** клиентов 5-20, саппорт начинает занимать заметное время.

#### Impersonation
Войти в любой ресторан как admin для диагностики.

- `POST /superadmin/impersonate/<restaurant_id>/` → возвращает временный JWT
  для админа этого ресторана (TTL 1 час)
- Audit-лог: `impersonate_started` с обязательным полем `reason: str`
  («Жалоба клиента на неверный отчёт смены»)
- Email клиенту: «Техподдержка зашла в вашу систему. Причина: ...»
- В UI клиента — баннер «🔒 Вы в режиме саппорта, действует до HH:MM»
- `impersonate_ended` audit-event при logout / TTL

#### Дашборд (минимум)
Главная страница `/superadmin/`:

- **Кол-во активных клиентов** (heartbeat за 7 дней)
- **MRR** = сумма (price_per_month × активных лицензий по плану)
- **Распределение по тарифам** (pie: trial / start / business / pro)
- **Истекающие лицензии за 30 дней** (action-list для звонка клиенту)
- **Heartbeat heatmap** — какие клиенты молчат >24ч (проверить)
- **Top app versions** — кто отстаёт (10 на v1.0, 5 на v1.2)

#### Технически
- Отдельный Django app `apps/superadmin/`
- Permission: `IsSuperAdmin` (через flag `User.is_staff`)
- Templates через Django views (без отдельного фронта пока)
- Charts: вставка готовой JS-библиотеки (Chart.js inline)

---

### Фаза SA-2 — Биллинг (~10-15 ч)

**Когда нужно:** клиентов >10, ручной учёт через Excel становится неудобным.

#### Модели
```python
class TariffPlan(Model):
    code = CharField(unique=True)  # 'start' | 'business' | 'pro'
    name = CharField()
    price_per_month_tjs = Decimal
    features = JSON   # {max_orders: 1000, kitchen: True, ...}
    is_active = Bool

class Invoice(Model):
    restaurant = FK
    plan = FK(TariffPlan)
    period_start = Date
    period_end = Date
    amount_tjs = Decimal
    status = Choice('pending', 'paid', 'overdue', 'cancelled')
    due_date = Date
    paid_at = DateTime | null
    created_at = DateTime

class Payment(Model):
    invoice = FK
    amount_tjs = Decimal
    method = Choice('cash', 'transfer', 'card', 'stripe')
    transaction_id = Char  # ID в платёжке
    paid_at = DateTime
    created_by = FK(User)  # super-admin кто провёл вручную
```

#### Логика
- При создании License → автогенерация Invoice на первый период
- Cron `daily`: за 7 дней до `period_end` → новый Invoice + email напоминание
- `Payment.save()` → если `sum(payments) >= invoice.amount` → `invoice.status='paid'`
  → `License.renew(days=30)`
- `Invoice.due_date` пройден без оплаты → `status='overdue'` → авто-блок License
  → email клиенту

#### UI super-admin
- Раздел «Биллинг»: список Invoice'ов с фильтрами (status, date range, restaurant)
- Кнопка «Создать платёж» → форма (amount, method, transaction_id)
- История платежей по ресторану — детальная страница

---

### Фаза SA-3 — Auto-renewal (~8-12 ч)

**Когда нужно:** клиентов >30, ручной выпуск Invoice'ов не масштабируется.

#### Платёжный шлюз
Выбор зависит от юрисдикции:
- **Stripe** — мировой стандарт, лучшие docs (но не работает в РФ/РБ напрямую)
- **YooKassa** — Россия / СНГ
- **CloudPayments** — Россия, удобный API
- **Алиф / DC.tj / Зум** — Таджикистан
- **Решение:** интерфейс `PaymentGateway` с реализациями под разные шлюзы

#### Flow
1. Клиент в owner-dashboard → «Привязать карту»
2. Redirect на gateway → клиент вводит карту на их странице (PCI-compliance)
3. Webhook от gateway → сохраняем `payment_method_token` в `Restaurant.billing`
4. Cron monthly:
   - Создать Invoice
   - `gateway.charge(payment_method_token, amount)` → success/fail
   - На success → `Payment.create()` → `Invoice.paid` → `License.renew(30)`
   - На fail → 3 retry (через 1, 3, 7 дней) → если всё фейл → блок + email

#### Webhooks
- `POST /billing/webhooks/<gateway>/` — обработка событий шлюза (payment.succeeded, payment.failed, refund)
- Идемпотентность через `transaction_id`

#### Card management
- Owner может посмотреть список карт, удалить, добавить новую
- При истечении карты — email уведомление за 14 дней

---

### Фаза SA-4 — Multi-restaurant под одним owner (~8-10 ч)

**Когда нужно:** появилась хотя бы одна сеть ресторанов одного владельца.

#### Модели
```python
class Owner(Model):
    name = CharField()
    email = EmailField(unique=True)
    phone = CharField()
    billing_account = FK(BillingAccount, null=True)

class Restaurant(Model):
    # ...existing fields...
    owner = FK(Owner, on_delete=PROTECT)  # NEW
```

#### UI Owner-cabinet (для владельца сети)
- Список своих ресторанов
- Сводный отчёт «Выручка всех точек за период»
- Перевод сотрудника между ресторанами
- Один счёт сразу за все рестораны (group billing)

#### Super-admin
- Раздел «Owners» — управление владельцами
- При создании Restaurant — выбор Owner (или создание нового)

---

### Фаза SA-5 — Telemetry (~10-15 ч)

**Когда нужно:** клиентов >20, нужно знать о проблемах раньше клиента.

#### Crash reports
- POS catch unhandled exceptions → POST `/telemetry/crash/` с stacktrace
- Backend: `CrashReport(restaurant, app_version, traceback, context, created_at)`
- Super-admin раздел «Краши» с фильтрами + dedup по signature
- Опционально интеграция с Sentry / GlitchTip (если хотим продвинутый dedup)

#### Active sessions tracking
- POS отправляет `session_started/ended` события
- Backend хранит активные сессии в Redis или таблице
- Super-admin: real-time список «кто сейчас работает»
- Heatmap: пиковая нагрузка по часам и дням недели

#### Anomaly detection
- Cron daily: ищем аномалии:
  - Ресторан не открыл смену 3 дня подряд
  - Внезапный спад выручки на 50% к среднему
  - Много отмен заказов (>20% за день) — фрод?
- Алёрт в super-admin + опционально в Telegram-бот

---

### Фаза SA-6 — Расширенные фичи

#### Промокоды на лицензии
- `Promocode(code, discount_pct, valid_until, max_uses)`
- При продаже плана — ввод промокода → скидка на первый месяц / квартал

#### Реферальная программа
- Клиент приводит другого клиента → бонус месяца обоим

#### White-label
- Клиент-партнёр продаёт RestOS под своим брендом
- Свой логотип, домен, цвета

#### Cloud sync (offline-first)
- Local Django ↔ Cloud Django через event-stream `sync_log`
- При обрыве сети POS работает автономно
- При восстановлении — синхронизация

---

## Таблица приоритетов по росту бизнеса

| Кол-во клиентов | Что нужно |
|---|---|
| **0-5** | Текущий MVP (License + Django admin) |
| **5-20** | + SA-1: Impersonation + базовый дашборд |
| **20-50** | + SA-2: Биллинг (Invoice/Payment) |
| **30-100** | + SA-3: Auto-renewal через gateway |
| **+ есть сеть** | + SA-4: Multi-restaurant под Owner |
| **20-100+** | + SA-5: Telemetry (parallel с биллингом) |
| **100+** | + SA-6: Промо, рефералка, white-label |

---

## Зависимости между фазами

```
SA-0 (License + admin) ──► SA-1 (Impersonation + dashboard)
                          │
                          ├─► SA-2 (Биллинг)
                          │     └─► SA-3 (Auto-renewal)
                          │
                          ├─► SA-4 (Multi-restaurant) — независимо
                          │
                          └─► SA-5 (Telemetry) — независимо
                                └─► SA-6 (Промо / реф / white-label)
```

---

## Архитектурный выбор: где живёт super-admin?

### Вариант A: Super-admin в том же Django (текущий MVP)
- ✅ Просто, готово
- ✅ Прямой доступ к моделям
- ❌ Если local-installation у клиента — super-admin тоже у клиента

### Вариант B: Cloud super-admin + local POS (рекомендуется для SA-2+)
- Super-admin живёт у нас на cloud-сервере
- Local POS-инстансы клиентов синхронизируются через webhooks/heartbeat
- ✅ Один super-admin на всех клиентов
- ❌ Нужен cloud-сервер (хостинг + DevOps)
- ❌ Потребуется обмен данными local↔cloud

### Вариант C: Pure cloud (все клиенты на нашем сервере)
- Multi-tenancy через `restaurant_id` (уже есть в коде)
- Каждый клиент использует наш cloud
- ✅ Все апдейты централизованно
- ❌ Зависимость от интернета
- ❌ Latency до клиента

**На сегодня (MVP local-only):** Вариант A. При SA-2 → переход на Вариант B.

---

## Полезные сторонние сервисы

| Задача | Решение |
|---|---|
| Платежи (СНГ) | YooKassa, CloudPayments, Tinkoff |
| Платежи (Tj) | DC.tj, Алиф, Зум |
| Crash reports | Sentry / GlitchTip (open-source) |
| Email | Mailgun, Resend, AWS SES |
| Cron | Celery beat / Django-Q / встроенный systemd-timer |
| Charts UI | Chart.js, Recharts (если SPA), Plotly |
| Real-time dashboard | Django Channels + Postgres LISTEN/NOTIFY |
| Telemetry | Prometheus + Grafana / Datadog (платно) |
