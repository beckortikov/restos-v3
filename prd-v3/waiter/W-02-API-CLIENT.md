# W-02 — API-клиент, JWT, LAN-guard

## `src/api/client.ts`

Один axios-инстанс с тремя interceptor'ами:
1. **LAN-guard** — отбрасывает запрос, если хост API не приватный.
2. **Auth** — подкладывает `Authorization: Bearer <access>`. На 401 пытается refresh.
3. **Idempotency** — на write-методах добавляет `Idempotency-Key` (если не передан вручную).

```ts
// src/api/client.ts
import axios, { AxiosError, AxiosRequestConfig } from "axios";
import { authStore } from "@/store/auth";
import { isPrivateHost } from "@/lib/lan-guard";
import { API_BASE_URL } from "@/config";
import { v4 as uuid } from "uuid";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10_000,
  headers: { "Content-Type": "application/json" },
});

// 1. LAN-guard
api.interceptors.request.use((cfg) => {
  const host = new URL(cfg.baseURL ?? "", window.location.href).hostname;
  if (!isPrivateHost(host)) {
    return Promise.reject({
      code: "OUT_OF_LAN",
      message: "Вы не в сети ресторана",
    });
  }
  return cfg;
});

// 2. Auth
api.interceptors.request.use((cfg) => {
  const access = authStore.getState().accessToken;
  if (access) cfg.headers.Authorization = `Bearer ${access}`;
  return cfg;
});

// Идемпотентность: для POST добавляем Idempotency-Key, если не передан
api.interceptors.request.use((cfg) => {
  const writes = ["post", "put", "patch", "delete"];
  if (writes.includes((cfg.method ?? "get").toLowerCase())) {
    if (!cfg.headers["Idempotency-Key"]) {
      cfg.headers["Idempotency-Key"] = uuid();
    }
  }
  return cfg;
});

// 3. 401 + refresh
let refreshPromise: Promise<string> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (err: AxiosError) => {
    const cfg = err.config as (AxiosRequestConfig & { _retried?: boolean });
    if (err.response?.status === 401 && !cfg._retried) {
      cfg._retried = true;
      const newAccess = await refreshAccess();
      if (newAccess) {
        cfg.headers!.Authorization = `Bearer ${newAccess}`;
        return api.request(cfg);
      }
      authStore.getState().logout();
      window.location.href = "/login";
    }
    return Promise.reject(normalizeError(err));
  },
);

async function refreshAccess(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  const refresh = authStore.getState().refreshToken;
  if (!refresh) return null;
  refreshPromise = axios
    .post(`${API_BASE_URL}/auth/refresh/`, { refresh })
    .then((r) => {
      const access = r.data.access;
      authStore.getState().setTokens(access, refresh);
      return access;
    })
    .catch(() => null)
    .finally(() => { refreshPromise = null; });
  return refreshPromise;
}

function normalizeError(err: AxiosError): { code: string; message: string; status: number } {
  const data = err.response?.data as any;
  return {
    code: data?.error?.code ?? "NETWORK",
    message: data?.error?.message ?? err.message,
    status: err.response?.status ?? 0,
  };
}
```

## `src/lib/lan-guard.ts`

Порт из текущего `lib/waiter/lan-guard.ts`:

```ts
export function isPrivateHost(hostname: string): boolean {
  if (hostname === "localhost" || hostname === "127.0.0.1") return true;
  // IPv4 приватные диапазоны
  const m = hostname.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false; // .local mDNS — допускаем как "не публичный"? Нет, требуем явно IP.
  const [a, b] = m.slice(1).map(Number);
  if (a === 10) return true;
  if (a === 192 && b === 168) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  return false;
}
```

`<LanGuard>` обёртка:

```tsx
// src/components/LanGuard.tsx
import { isPrivateHost } from "@/lib/lan-guard";
import { API_BASE_URL } from "@/config";

export function LanGuard({ children }: { children: React.ReactNode }) {
  const host = new URL(API_BASE_URL, window.location.href).hostname;
  if (!isPrivateHost(host)) {
    return <OutOfLanScreen />;
  }
  return <>{children}</>;
}
```

`<OutOfLanScreen>` — full-screen с надписью «Вы не в сети ресторана. Подключитесь к Wi-Fi заведения и обновите страницу.»

## `src/store/auth.ts`

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

type User = { id: number; full_name: string; role: "waiter" };

type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  setTokens: (access: string, refresh: string) => void;
  setUser:   (u: User) => void;
  logout:    () => void;
};

export const authStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null, refreshToken: null, user: null,
      setTokens: (access, refresh) => set({ accessToken: access, refreshToken: refresh }),
      setUser:   (user) => set({ user }),
      logout:    () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    { name: "restos.waiter.auth" },
  ),
);
```

## API-обёртки

```ts
// src/api/auth.ts
export const authApi = {
  login:   (data: { username: string; password: string }) =>
            api.post("/auth/login/", data).then((r) => r.data.data),
  refresh: (refresh: string) =>
            api.post("/auth/refresh/", { refresh }).then((r) => r.data.access),
  me:      () => api.get("/auth/me/").then((r) => r.data.data),
};

// src/api/tables.ts
export const tablesApi = {
  zones: () => api.get("/tables/zones/").then((r) => r.data.data),
  list:  (params?: { zone?: number; status?: string }) =>
            api.get("/tables/", { params }).then((r) => r.data.data),
  open:  (id: number, body: { guests_count: number }) =>
            api.post(`/tables/${id}/open/`, body).then((r) => r.data.data),
};

// src/api/menu.ts
export const menuApi = {
  categories: () => api.get("/menu/categories/").then((r) => r.data.data),
  items:      () => api.get("/menu/items/").then((r) => r.data.data),
};

// src/api/orders.ts
export const ordersApi = {
  create:       (body: any, idempotencyKey: string) =>
                  api.post("/orders/", body, {
                    headers: { "Idempotency-Key": idempotencyKey },
                  }).then((r) => r.data.data),
  detail:       (id: number) => api.get(`/orders/${id}/`).then((r) => r.data.data),
  addItems:     (id: number, items: any[], idempotencyKey: string) =>
                  api.post(`/orders/${id}/add_items/`, { items }, {
                    headers: { "Idempotency-Key": idempotencyKey },
                  }).then((r) => r.data.data),
  cancelItem:   (id: number, body: { item_id: number; reason: string }) =>
                  api.post(`/orders/${id}/cancel_item/`, body).then((r) => r.data.data),
  requestBill:  (id: number) =>
                  api.post(`/orders/${id}/request_bill/`).then((r) => r.data.data),
  cancel:       (id: number, body: { reason: string }) =>
                  api.post(`/orders/${id}/cancel/`, body).then((r) => r.data.data),
};
```

## Идемпотентные мутации

В UI создаём ключ один раз и переиспользуем при ретраях:

```ts
// src/pages/MenuPage.tsx (фрагмент)
const idemKeyRef = useRef<string>(uuid());

const send = async () => {
  try {
    const order = await ordersApi.create(
      { table_id: tableId, guests_count, items: cart.items },
      idemKeyRef.current,
    );
    drafts.clear(tableId);
    navigate(`/order/${order.id}`);
  } catch (e: any) {
    if (e.code === "NETWORK") {
      toast.error("Нет связи, повтор через 3 с");
      setTimeout(send, 3000);                 // тот же ключ
    } else {
      toast.error(e.message);
    }
  }
};
```

## SSE: `useEventStream`

Один глобальный хук, монтируется в корне приложения после логина. Слушает `/api/v1/events/` и инвалидирует react-query-кэш на каждое событие.

```ts
// src/api/events.ts
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { authStore } from "@/store/auth";
import { API_BASE_URL } from "@/config";

export function useEventStream() {
  const qc = useQueryClient();
  const token = authStore((s) => s.accessToken);

  useEffect(() => {
    if (!token) return;
    // EventSource не умеет ставить заголовки — передаём токен как ?token=...
    const url = `${API_BASE_URL}/events/?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.addEventListener("resync", () => {
      qc.invalidateQueries({ queryKey: ["tables"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["menu"] });
    });

    es.addEventListener("table.updated", () => {
      qc.invalidateQueries({ queryKey: ["tables"] });
    });

    es.addEventListener("order.created", (e) => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      const p = JSON.parse((e as MessageEvent).data);
      qc.invalidateQueries({ queryKey: ["order", p.id] });
    });

    es.addEventListener("order.updated", (e) => {
      const p = JSON.parse((e as MessageEvent).data);
      qc.invalidateQueries({ queryKey: ["order", p.id] });
      qc.invalidateQueries({ queryKey: ["orders"] });
    });

    es.addEventListener("menu.invalidated", () => {
      qc.invalidateQueries({ queryKey: ["menu"] });
    });

    es.onerror = () => {
      // браузерный EventSource сам реконнектится с экспоненциальным backoff.
      // Сервер пришлёт resync на новом коннекте — UI ресинхронизируется.
    };

    return () => es.close();
  }, [token, qc]);
}
```

Использование:

```tsx
// src/App.tsx
function AppShell() {
  useEventStream();
  return <Outlet />;
}
```

### Почему `?token=` в URL, а не заголовок

Нативный `EventSource` в браузерах **не позволяет ставить заголовки**. У нас два варианта:
1. **Cookie auth** — переключить waiter PWA на session-cookie (потребуется CSRF-токен на write-методах).
2. **Токен в query-параметре** — backend поддерживает `?token=<jwt>` именно для `/events/` (см. B-01 `TokenQueryParamAuthentication`).

Выбран вариант 2 — он не меняет остальной auth-стек. Безопасно: токен в URL появляется только в логах backend'а, который и так знает токены, а HTTPS внутри LAN не обязателен (мы и так в LAN).

**Если очень захотим заголовки** — ставим polyfill `event-source-polyfill`, который под капотом делает `fetch + ReadableStream`:

```ts
import { EventSourcePolyfill } from "event-source-polyfill";
const es = new EventSourcePolyfill(`${API_BASE_URL}/events/`, {
  headers: { Authorization: `Bearer ${token}` },
  heartbeatTimeout: 60_000,
});
```

В Capacitor APK polyfill работает стабильнее (нативный EventSource в WebView иногда виснет на background).

## Service worker

`vite-plugin-pwa` со стратегиями:

```ts
// vite.config.ts (ключевой блок)
VitePWA({
  registerType: "autoUpdate",
  workbox: {
    runtimeCaching: [
      {
        urlPattern: ({ url }) => url.pathname.startsWith("/api/v1/menu/"),
        handler: "StaleWhileRevalidate",
        options: { cacheName: "menu", expiration: { maxAgeSeconds: 300 } },
      },
      {
        urlPattern: ({ url }) => url.pathname.startsWith("/media/menu/"),
        handler: "CacheFirst",
        options: { cacheName: "menu-images", expiration: { maxAgeSeconds: 86400 } },
      },
    ],
  },
});
```

`/orders/`, `/tables/`, `/auth/` всегда идут в сеть — иначе риск показывать мёртвые данные.
