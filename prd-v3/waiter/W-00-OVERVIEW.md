# W-00 — Waiter PWA: обзор

Приложение официанта — отдельное от кассира. Запускается на Android-планшете (Chrome, либо как APK через Capacitor). Работает **только в LAN ресторана**.

## Onboarding (QR-pairing)

Первый запуск на новом планшете: кассир на POS открывает диалог «📱 Подключить планшет» (кнопка на PIN-экране), там показан QR с URL вида `http://<lan-ip>/`. Официант наводит камеру Android на QR → Chrome открывает waiter PWA → PIN-экран официанта → ввод PIN → готов работать. После первого захода Chrome предлагает «Добавить на главный экран» — дальше открывается как иконка.

Никаких device-токенов и pairing-кодов backend не выдаёт: per-device идентичность не нужна, аутентификация — по [waiter-PIN](W-01-SCREENS.md#1-loginpage-login). Любой планшет в той же Wi-Fi сети, отсканировавший QR, попадает на тот же логин-экран; LAN-guard + PIN+lockout — единственные защиты.

URL внутри QR определяется на стороне POS: `pos.config.get_pair_url()` берёт `RESTOS_PAIR_URL` если задан, иначе `http://<lan-ip>/` (LAN-IP определяется через socket-трюк). Подробности экрана POS — `prd-v3/cashier/C-01-SCREENS.md` § «(post-MVP) Подключение планшета».

## Стек

| Компонент | Назначение |
|---|---|
| Vite 5 + React 19 + TypeScript | UI |
| Tailwind CSS + Radix UI | дизайн-система |
| `axios` | HTTP-клиент к Django |
| `zustand` | state-store (auth, drafts, cart) |
| `@tanstack/react-query` | кэш+invalidation для menu/tables/orders |
| Native `EventSource` | SSE-подписка на `/api/v1/events/` |
| `event-source-polyfill` | EventSource с поддержкой кастомных заголовков (на случай APK) |
| `react-router` 7 | роутинг |
| Capacitor 8 | сборка APK (опционально) |
| Workbox / vite-plugin-pwa | service worker и кэш меню |
| Playwright | e2e-тесты |

**Удаляем (по сравнению с текущим кодом RestOS v1):**
- `@electric-sql/pglite` — больше нет локальной БД
- `Dexie` / `lib/offline/` — больше нет двусторонней синхронизации
- `@supabase/supabase-js` — Supabase больше не используется
- старый `lib/realtime.ts` (Supabase realtime) — заменён на наш собственный SSE-хук, см. W-02

**Сохраняем:**
- `lib/waiter/drafts.ts` — черновики корзины в localStorage
- `lib/waiter/lan-guard.ts` — проверка приватного IP
- `lib/waiter/view-mode.ts` — стартовый экран

## Структура проекта

```
restos-waiter/
├── src/
│   ├── api/
│   │   ├── client.ts          # axios + interceptors
│   │   ├── auth.ts
│   │   ├── tables.ts
│   │   ├── menu.ts
│   │   └── orders.ts
│   ├── pages/
│   │   ├── LoginPage.tsx
│   │   ├── TablesPage.tsx
│   │   ├── MenuPage.tsx
│   │   └── OrderPage.tsx
│   ├── components/
│   │   ├── TableCard.tsx
│   │   ├── ZoneTabs.tsx
│   │   ├── DishTile.tsx
│   │   ├── CartDrawer.tsx
│   │   ├── GuestsDialog.tsx
│   │   └── LanGuard.tsx
│   ├── store/
│   │   ├── auth.ts            # zustand
│   │   ├── cart.ts
│   │   └── drafts.ts          # localStorage adapter
│   ├── lib/
│   │   ├── lan-guard.ts       # порт из текущего lib/waiter/lan-guard.ts
│   │   ├── format.ts
│   │   └── idempotency.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── service-worker.ts
├── public/
│   ├── manifest.webmanifest
│   └── icons/
├── tests/
│   └── e2e/
│       ├── login.spec.ts
│       ├── happy-path.spec.ts
│       └── lan-guard.spec.ts
├── android/                   # Capacitor — для APK
├── capacitor.config.ts
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
└── README.md
```

## Конфиги

```ts
// src/config.ts
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || `http://${window.location.hostname}/api/v1`;
export const POLL_INTERVAL_MS = 5000;
export const MENU_CACHE_MAX_AGE_S = 300;
```

В production `nginx` на main POS отдаёт `index.html` и проксирует `/api/` на gunicorn — тогда `window.location.hostname` уже укажет на main POS, и LAN-guard будет happy.

## Скрипты

```json
{
  "scripts": {
    "dev":         "vite --host 0.0.0.0",
    "build":       "tsc -b && vite build",
    "preview":     "vite preview",
    "apk":         "vite build && cap sync && cd android && ./gradlew assembleRelease",
    "apk:debug":   "vite build && cap sync && cd android && ./gradlew assembleDebug",
    "test:e2e":    "playwright test"
  }
}
```

## Принципы

1. **LAN-only.** Перед запуском приложения и перед каждым запросом проверяется, что host API — приватный IP. Иначе экран «Вы вне сети ресторана».
2. **SSE, не polling.** Один `EventSource` на `/api/v1/events/`. Хук `useEventStream()` мапит входящие события в `queryClient.invalidateQueries()` — react-query сам подтягивает свежие данные. На обрыв связи — авто-reconnect; backend сразу шлёт `event: resync`, и UI делает full refetch базовых ресурсов (см. W-02).
3. **Idempotency.** Каждый POST на `/orders/`, `/orders/*/close/`, `/orders/*/cancel/` несёт `Idempotency-Key`. Ключ генерируется в момент намерения (открытие cart drawer для отправки) и переиспользуется при ретраях.
4. **Service worker — для меню и картинок.** Меню кешируется агрессивно, заказы и столы — никогда (всегда сеть, иначе на втором планшете будет старая картинка).
5. **Никаких прямых обращений в БД, никаких Supabase, никакого PGlite.** Только REST к Django.
6. **Drafts в localStorage** (как в текущем `lib/waiter/drafts.ts`): корзина автосохраняется при каждом изменении, восстанавливается при возврате на тот же стол.

## Acceptance

- В Chrome на планшете в сети ресторана — открывается логин, после ввода доступен полный флоу.
- Тот же URL вне сети ресторана — экран «Не в сети ресторана» без полей логина.
- При обрыве сети во время сборки заказа — кнопка «Отправить» сообщает «Нет связи, повтор через 3 с» и **не теряет** черновик; после восстановления связи отправка с тем же `Idempotency-Key` идёт автоматически.
- При открытии в режиме APK (Capacitor) на Android — то же самое плюс system bar prefs из manifest.
