# 99 — Дорожная карта после MVP

MVP покрывает: столы, меню, заказ от официанта, оплату от кассира, печать чека. Всё остальное, что есть в текущем коде RestOS v1, разнесено по фазам ниже. Каждая фаза — самостоятельный инкремент с собственными PRD-документами.

В скобках после пункта — где это уже есть в текущем коде (как референс при имплементации).

---

## Phase 2 — Кухня и склад (M+1)

### Кухня
- Роль `cook`, отдельный экран KDS на main POS (PySide или web).
- Канбан с колонками `new → cooking → ready → served`.
- Поле `Order.kitchen_status`, переходы.
- Бегунок ESC/POS на станционные принтеры (`MenuItem.station → Printer`). Тип печати `runner`.
- Бегунок отмены при `cancel_item` уже распечатанной позиции (тип `cancel_runner`).
- Authoready-режим (`Restaurant.auto_ready_mode`, `auto_ready_buffer_min`).
- Ref: `app/(app)/operations/kitchen/`, `lib/print-service.ts:buildEscPosRunner`, `components/print-runner.tsx`.
- Перенести экран «Подключение планшета» (`pos/screens/tablet_pairing_screen.py`) в дизайн `design/pos_cashier.pen` отдельным frame'ом и переделать 1:1 (сейчас собран без фрейма, минималистично).

### Склад

Часть Phase 7 (`A-E`) и Phase 8 (`A-D`) уже разъехались по апдейтам ниже и в коде. Раздел оставлен как «карта работ» — то, что отмечено ✅, реально готово.

**Backend — модели и сервисы:**
- ✅ `Ingredient` (event-stream `IngredientStockMovement` для qty, weighted-avg cost) — Phase 7D, `apps/inventory/models.py:34-103,284-338`.
- ✅ `SemiFinishedType` + `SemiFinishedRecipeLine` + `SemiFinishedStockMovement`, сервис `produce_semi` с pre-flight check и yield_percent — Phase 7D, `apps/inventory/models.py:105-264`, `apps/inventory/services.py:209-328`.
- ✅ `MenuItemTechCardLine` (XOR ingredient/nested_semi) + сервис `consume_for_order_close(order)` — Phase 7C, `apps/menu/models.py:279-337`, `apps/inventory/services.py:374-473`.
- ✅ Сервис `record_movement` с защитой от негативных остатков (`INVENTORY_PREVENT_NEGATIVE`) и аудит-логом — `apps/inventory/services.py:38-149`.
- ✅ `BatchCookingLog` + `record_batch_cook` / `record_batch_consume_for_order` / `writeoff_prepared_batch` — Phase 7E, `apps/menu/services.py`.
- ✅ Phase 8A — документы: `Supplier`, `StockReceipt`/`StockReceiptLine` (draft→applied), `StockWriteoff`/`StockWriteoffLine`, `InventoryCheck`/`InventoryCheckLine`, `SupplyExpense` — `apps/inventory/models.py:344-607`, `apps/inventory/views_8a.py`.
- ✅ Phase 8B — глобальный тоггл `Restaurant.tech_cards_enabled` + per-item `MenuItem.auto_consume` (выкл → не списывает по техкарте).
- ✅ Phase 8D — авто-стоп блюд при нехватке ингредиентов: `MenuItem.auto_stopped`, `MenuItem.allow_oversell`, сервис `apps/menu/services_autostop.py`, хук в `record_movement`/`record_semi_movement`/`produce_semi` через `transaction.on_commit`, endpoints `POST /menu/items/{id}/allow_oversell/`, `POST /menu/items/{id}/toggle_tech_card/`, `GET /menu/items/auto_stopped/`. Блокировка добавления в заказ → `STOCK_INSUFFICIENT` с именем недостающего ингредиента (`apps/orders/services.py:198`).

**Backend — что ещё нужно:**
- Управление поставщиками с долгами (paid/credit/partial), FIFO-погашение — пока только справочник.
- Импорт меню/техкарт/ингредиентов из Excel (порт `lib/import-excel.ts`) — для меню есть, для техкарт/ингредиентов нет.
- Агрегатный endpoint `GET /inventory/ingredients/summary/?is_food=true|false` — totals + total_value (Σ qty × avg_cost) для KPI «Стоимость остатков». **План**: добавить `@action(detail=False)` в `IngredientViewSet`.
- Перенос сервиса списания на переход `cooking → ready` (сейчас — на `close_order`).

**POS UI — кассир (Tauri → PySide6):**
- ✅ Складская секция в Настройках с табами Продукты / Полуфабрикаты / Авто-стоп / Поставщики / Накладные / Списания / Расход хозтоваров / Инвентаризация — `apps/pos/pos/screens/settings_sections/inventory_section.py` (+ `inventory_panes_8a.py`).
- ✅ KPI strip (Всего / Заканчивается / Закончилось / Отключено) + search + chip-фильтры — Phase 8D redesign.
- ✅ Авто-стоп pane: список заблокированных блюд + кнопка «Продавать в минус» — Phase 8D.
- ✅ `stop_list_dialog` с ⚙ попапом настроек блюда (auto_consume / allow_oversell) — `apps/pos/pos/screens/stop_item_settings_dialog.py`.
- ✅ Кнопка «Удалить» уехала из таблицы внутрь edit-диалогов ингредиента и п/ф (Phase 8D).
- ⬜ Разделить `IngredientsPane` на две вкладки «Продукты» (is_food=True) и «Хозтовары» (is_food=False) — есть в дизайне, не в коде.
- ⬜ 5-я KPI-карточка «Стоимость остатков» на вкладке «Продукты» — зависит от агрегатного endpoint выше.
- ⬜ Полноценный workflow документов (Накладная/Списание/Инвентаризация) — заглушки в `inventory_panes_8a.py`, но без редактора-документа из дизайна (frames 37-39).
- ⬜ Модал «История движений» (`MovementsHistoryDialog`) — есть, но без нового дизайна из frame 40.

**Дизайн `design/pos_cashier.pen` — готово (volumes 1-4):**

Экраны (9 frame'ов, y=8004…10000):
- `coXZo` 25. Склад — Продукты (5 KPI включая «Стоимость остатков»)
- `T6fc7` 26. Склад — Полуфабрикаты
- `EpBXi` 27. Склад — Авто-стоп блюд (с badge «3» в табе)
- `IKsIX` 28. Склад — Поставщики
- `zjQlE` 29. Склад — Накладные
- `W9pDrm` 30. Склад — Списания
- `U6vgwJ` 31. Склад — Расход хозтоваров
- `aP2fK` 32. Склад — Инвентаризация
- `pP9eD` 33. Склад — Хозтовары (отдельная вкладка для is_food=False)

Каждый экран имеет общую chrome-структуру: dark sidebar 80px (settings активен) → settings sub-nav 240px (15 секций, «Склад» подсвечен) → main с topbar + tabbar (9 вкладок) + content.

Модалки (7 frame'ов, y=11000…12000):
- `M7osIe` 34. Edit Ingredient / Хозтовар (segment Продукт/Хозтовар, поля, чекбокс Активен, Удалить-в-футере)
- `SDtxB` 35. Edit Semi-Finished + Recipe (поля + чекбокс + таблица рецепта 4 компонента + Себест. 1 кг п/ф)
- `RMwSn` 36. Stop item settings ⚙ (карточка блюда + 2 toggle + статус-info)
- `zgo7n` 37. Накладная (приёмка): шапка + метаданные + строки приёмки + ИТОГО + Применить (склад +)
- `azzCx` 38. Списание: причина + ответственный + строки + ПОТЕРИ + Применить (склад −)
- `NyjDJ` 39. Инвентаризация: тип + строки с input «Факт» + Недостача/Излишек/ИТОГО Δ + Применить (создаст корректировки)
- `fEhDy` 40. История движений: summary-bar + chip-фильтры + period-picker + таблица событий с цветными badge-pill по типу

Reusable компоненты:
- `Cgpwn` KPI-Card — value + label + цветная левая полоска через override stroke.
- `cIoG7` Status-Pill — pill-badge с overridable текстом/цветом.

**Известный риск дизайна:** модалки 37-40 не были визуально провалидированы через `get_screenshot` (баг рендера Pencil на сочетании сложных flex-структур). Данные в `.pen` корректны. Перед code-имплементацией открыть .pen в Pencil App и убедиться визуально.

Ref: `app/(app)/warehouse/*`, `lib/supabase-queries.ts:deductStockForOrder/produceSemiFab`.

---

## Phase 3 — Кассовые смены и финансы

### Смены (`CashShift`)
- Открытие смены кассиром: `POST /shifts/open/  {opening_balance, account_id}`.
- Закрытие: фактический пересчёт кассы → diff с expected → `closing_balance`.
- Инкассация (`CashShiftOperation` с типом `cash_in/cash_out`).
- `Order.shift_id` обязателен для DONE-заказов.
- Отчёт по смене: cash/card revenue, кол-во заказов, средний чек, по официантам и категориям. Экспорт XLSX.
- Ref: `app/(app)/operations/shifts/`, `lib/types.ts:CashShift/CashShiftOperation`, `lib/shift-export.ts`.

### Финансы
- `FinancialAccount` (cash/bank), `FinancialOperation` (in/out/transfer; activity op/inv/fin).
- **Авто-доход при close_order** — обязательный сервис `create_revenue_entry()` в `close_order`. В текущем коде это пропущено.
- Иммутабельность операций; сторно через `is_reversal` и FK на исходную.
- ДДС (cashflow), ОПиУ (P&L), Баланс (assets/liabilities/equity), бюджет (`BudgetLine`).
- Авто-обновление `BudgetLine.fact_amount` при создании операций.
- Ref: `app/(app)/finance/{cashflow,pnl,balance,budget,payroll}/*`.

---

## Phase 4 — Платежи: больше методов, скидки, чаевые, разделение счёта

- `OrderPayment(order, method, amount, account)` — мульти-платежи (часть наличными, часть картой). В UI кассира — поле «остаток к оплате» при выборе метода.
- `Order.discount_type/value/amount/reason` — процент или фиксированная сумма скидки. Permission `orders.discount` (по ролям).
- `Order.tip_amount` — чаевые отдельной строкой в чеке.
- `Order.service_percent/service_amount/total_with_service` — сервисный сбор (% от ресторана).
- `OrderSplit` + `split_order(order, mode='equal'|'by_items')` — разделение счёта.
- Возвраты: пока не делаем (только soft-cancel позиций до DONE).

---

## Phase 5 — Меню расширенное

- Модификаторы: `ModifierGroup` + `Modifier` + `OrderItemModifier`.
- ✅ Стоп-лист — реализован двумя путями (Phase 8D):
  - Ручной: `MenuItem.is_available=False` + `stop_reason` + `stop_until` через `POST /menu/items/{id}/stop_list/` и `POST /menu/items/{id}/restore/`.
  - Автоматический: при списании остатков ниже 1 порции по техкарте — `auto_stopped=True`. Снимается автоматически при следующем приходе. Override менеджером — `POST /menu/items/{id}/allow_oversell/`. Каталог авто-стопнутых — `GET /menu/items/auto_stopped/`.
- ✅ Weight-based блюда: `MenuItem.unit/unit_size/sale_step` (продажа по граммам) — реализовано (`apps/menu/models.py:230-243`).
- ✅ `MenuItem.is_batch_cooking` + `prepared_qty` + `low_stock_threshold` — учёт партии (Phase 7E).
- ⬜ Импорт Excel: меню (есть), техкарты, ингредиенты (нет), зоны, столы (нет).

---

## Phase 6 — Зарплата и табель

- Модель `PayrollPeriod(user, period_start, period_end, salary, bonuses, deductions, paid_at, paid_operation FK→FinancialOperation)`.
- `TimeEntry(user, clock_in, clock_out, status)` — табель.
- Сервис `calculate_period(user, from, to)` суммирует часы и считает.
- Выплата: `POST /payroll/{period_id}/pay/` создаёт `FinancialOperation(out)` и проставляет `paid_at`.

---

## Phase 7 — Аналитика

- ABC-меню/склад со снапшотами (`AbcSnapshot` + `AbcSnapshotLine`) — историческая фиксация.
- Peak-hours: распределение заказов по часам недели/месяца.
- Food-cost: % COGS от revenue по категориям и блюдам.
- Forecast: simple moving average (Phase 7), ML-модель — Phase 8.
- Аналитика по официантам: продажи, средний чек, кол-во гостей.

---

## Phase 8 — Аудит, склад-расширение, авто-стоп

Часть фазы (`A-D`) уже разъехалась по апдейтам — оставлено для истории.

- ✅ Phase 8A — складские документы: `Supplier`, `StockReceipt`, `StockWriteoff`, `InventoryCheck`, `SupplyExpense`, изоляция «Продукт / Хозтовар» через `Ingredient.is_food`.
- ✅ Phase 8B — глобальный `Restaurant.tech_cards_enabled` + per-item `MenuItem.auto_consume` (override автосписания).
- ✅ Phase 8C — `writeoff_prepared_batch` для batch-блюд (отдельно от списания сырья).
- ✅ Phase 8D — авто-стоп блюд при нехватке: `auto_stopped`, `allow_oversell`, реактивный пересчёт через `transaction.on_commit`. Подробнее — см. раздел Phase 2 «Склад» выше.
- ✅ Аудит-лог (`AuditLog`) — fire-and-forget логирование событий: создание заказа, отмена позиции, оплата, открытие/закрытие смены, изменение цены меню, инвентаризация, изменения настроек (включая stock movements и стоп-листы). `apps/audit/`.
- ⬜ Резервации (`Reservation`).
- ⬜ Объединение столов — частично есть (`Table.merged_with`).
- ⬜ Типы заказов `delivery` / `takeaway` — есть в `Order.order_type`, UI кассира упрощённый.

---

## Phase 9 — Сеть ресторанов и облако

- Multi-tenancy на уровне сервера: `restaurant_id` во всех мутациях, central database.
- Синхронизация локального Django ↔ облачного Django через event-stream `sync_log`. Версионирование через `version: int` или `updated_at` для разрешения конфликтов.
- Owner-dashboard на Next.js на Vercel — отдельный фронт для собственника сети.
- Real-time через SSE/WebSocket (Channels или `sse-starlette`).

---

## Phase 10 — Super-Admin (Vendor Panel)

Панель **поставщика** RestOS (нас, vendor'а), а не владельца ресторана.
Управляет лицензиями, биллингом, телеметрией всех клиентов платформы.

> Не путать с Owner-Dashboard (Phase 9): тот для **владельца ресторана**;
> Super-Admin — для **нас (vendor'а)**.

Подробный план — [superadmin/SA-00-OVERVIEW.md](superadmin/SA-00-OVERVIEW.md).

### SA-0 — License foundation ✅ СДЕЛАНО
- Модель `License`, `Restaurant.heartbeat`, endpoints, Django admin, POS banner.
- Хватит для 5-20 первых клиентов.

### SA-7 — Hardware-binding (node-locked) ✅ СДЕЛАНО (Phase 8E)

Привязка одной лицензии к одной физической машине. Защита от размножения ключа.

**Backend:**
- `License.hardware_uuid` + `License.activated_at` (миграция `0004_license_hardware_uuid`).
- `POST /api/v1/license/activate/  {license_key, hardware_uuid}` — без user-auth, идемпотентно.
  - Первый раз — сохраняет UUID. Повтор с тем же UUID — OK. Чужой UUID — 403 `MACHINE_MISMATCH`.
  - Невалидный HWID (нули, < 32 chars, VirtualBox/Hyper-V default) — 400 `INVALID_VALUE`.
- DRF-permission `_enforce_license` сверяет `X-Machine-UUID` header с `License.hardware_uuid` на write-методах; mismatch → 403.
- Django admin: action «Сбросить привязку машины» (`reset_machine_binding`) для разрешения перепривязки при смене железа.
- Audit-log на каждое `license_activate`.
- 12 тестов в `apps/backend/apps/licensing/tests/test_machine_binding.py`.

**POS:**
- `apps/pos/pos/resources/hwid.py` — `collect_hardware_uuid()` (Windows: WMIC + PowerShell fallback; Linux: `/etc/machine-id`; macOS: `ioreg`; last-resort: MAC-based UUID).
- `apps/pos/pos/resources/license_store.py` — local storage в `%APPDATA%/RestOS/license.json` (Win) / `~/.restos-pos/license.json` (Linux/Mac).
- `apps/pos/pos/screens/license_activation_screen.py` — UI с HWID + кнопка «Копировать» + поле ключа + «Активировать».
- `apps/pos/pos/main.py` bootstrap: если local license отсутствует → показывает `LicenseActivationScreen` перед PIN-login.
- `apps/pos/pos/http_client.py` — добавляет `X-Machine-UUID` header ко всем запросам.

**Поток (manual flow):**
1. Юзер устанавливает POS на новую машину
2. Запускает POS → показывается activation screen с HWID
3. Копирует HWID, отсылает вендору
4. Вендор в Django admin создаёт `License` (или находит существующую) → вводит `hardware_uuid` → отправляет `license_key`
5. Юзер вводит ключ → «Активировать» → POST `/license/activate/` → save в local
6. PIN-login → штатная работа

**Смена железа:** вендор кликает action «Сбросить привязку машины» → юзер на новой машине проходит активацию заново.

### SA-1 — Impersonation + базовый дашборд (~6-8 ч)
- «Войти как admin клиента» для саппорта (с audit + email-уведомлением)
- Dashboard: MRR, активные клиенты, истекающие лицензии, top app versions

### SA-2 — Биллинг (~10-15 ч)
- Модели `TariffPlan`, `Invoice`, `Payment`
- Авто-Invoice за 7 дней до окончания, оплата → продление
- Раздел «Биллинг» с историей

### SA-3 — Auto-renewal (~8-12 ч)
- Платёжный шлюз (Stripe / YooKassa / DC.tj — выбор по юрисдикции)
- Tokenization карты + monthly cron + retry-логика
- Webhooks с идемпотентностью

### SA-4 — Multi-restaurant под Owner (~8-10 ч)
- Модель `Owner` (физ-лицо), `Restaurant.owner = FK`
- Owner-cabinet: список ресторанов сети, group billing, перевод сотрудников

### SA-5 — Telemetry (~10-15 ч)
- `CrashReport` + endpoint `/telemetry/crash/`
- Active sessions tracking (Redis / Postgres)
- Anomaly detection: смена не открыта 3 дня, спад выручки 50%

### SA-6 — Расширенные фичи
- Промокоды на лицензии
- Реферальная программа
- White-label (партнёр продаёт под своим брендом)
- Cloud sync (offline-first POS ↔ cloud)

---

## Никогда (или в очень дальней перспективе)

- Замена нашего Django на сторонний POS-движок.
- Поддержка фискальных регистраторов конкретных юрисдикций — только если бизнес явно потребует.
- Платёжные шлюзы (приём оплаты картой через интернет) — обычно делается через внешний терминал.

---

## Зависимости между фазами

```
MVP ─┬─► Phase 2 (Кухня + Склад)
     │     ├─► Phase 5 (Модификаторы / стоп-лист) — нужны ингредиенты
     │     └─► Phase 7 (Аналитика food-cost) — нужны COGS/техкарты
     │
     └─► Phase 3 (Смены + Финансы)
           ├─► Phase 4 (Мульти-платежи + скидки) — расширяет close_order
           ├─► Phase 6 (ЗП) — нужны FinancialOperation для выплат
           └─► Phase 7 (Аналитика revenue) — нужны смены и financial_operations
                 │
                 └─► Phase 8 (Аудит + Резервации) — независимо

Phase 9 (Облако) — последним, на стабильной локальной системе.

Phase 10 (Super-Admin) — параллельный трек, начат с SA-0 (License foundation),
расширяется по мере роста кол-ва клиентов.
```

В каждой фазе документация будет следовать той же схеме: модель → сериализатор → сервис → views/URLs/permissions → UI на стороне cashier и/или waiter, плюс матрицы прав по ролям.
