# W-03 — Черновики корзины (drafts)

Чтобы официант не терял набранный заказ при случайном свайпе/перезагрузке/смене стола, корзина автоматически сохраняется в `localStorage`. Логика — порт текущего `lib/waiter/drafts.ts`.

## Хранилище

Ключ: `restos.waiter.drafts`
Формат:

```ts
type DraftItem = {
  menuItemId: number;
  name: string;        // на момент добавления — для оффлайн-показа без меню
  price: string;       // тоже снапшот
  qty: number;
};

type Draft = {
  tableId: number;
  guestsCount: number;
  items: DraftItem[];
  updatedAt: string;   // ISO
  idempotencyKey: string; // создан при первом изменении, используется при отправке
};

type Drafts = Record<number /* tableId */, Draft>;
```

Один draft на стол. Если на одном столе работают параллельно два официанта — UX этого не предусматривает; backend всё равно поймает гонку (`TABLE_OCCUPIED` или `INVALID_TRANSITION`).

## Adapter

```ts
// src/store/drafts.ts
import { v4 as uuid } from "uuid";

const KEY = "restos.waiter.drafts";

function read(): Drafts {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}"); }
  catch { return {}; }
}
function write(d: Drafts) { localStorage.setItem(KEY, JSON.stringify(d)); }

export const drafts = {
  get(tableId: number): Draft | null {
    return read()[tableId] ?? null;
  },

  upsert(tableId: number, patch: Partial<Omit<Draft, "tableId" | "updatedAt">>): Draft {
    const all = read();
    const cur = all[tableId];
    const next: Draft = {
      tableId,
      guestsCount: patch.guestsCount ?? cur?.guestsCount ?? 1,
      items:       patch.items ?? cur?.items ?? [],
      idempotencyKey: cur?.idempotencyKey ?? uuid(),
      updatedAt:   new Date().toISOString(),
    };
    all[tableId] = next;
    write(all);
    return next;
  },

  clear(tableId: number) {
    const all = read();
    delete all[tableId];
    write(all);
  },

  list(): Draft[] {
    return Object.values(read());
  },

  // удалить все драфты столов, которые сейчас free (вызывается при заходе на TablesPage)
  prune(freeTableIds: Set<number>) {
    const all = read();
    let dirty = false;
    for (const id of Object.keys(all).map(Number)) {
      if (freeTableIds.has(id)) {
        delete all[id];
        dirty = true;
      }
    }
    if (dirty) write(all);
  },
};
```

## Жизненный цикл

```
[Officiant жмёт +1 на DishTile]
   → cart.add(menuItem)
   → drafts.upsert(tableId, { items: cart.items, guestsCount })
   → setSubmittingDisabled(false)

[Жмёт «Отправить»]
   → ordersApi.create({...}, draft.idempotencyKey)
   → on success: drafts.clear(tableId); navigate(/order/{id})

[Сетевая ошибка]
   → toast «Нет связи, повтор через 3с»
   → setTimeout(send, 3000)   с тем же idempotencyKey
   draft остаётся, при крэше планшета восстановится

[Возврат на /menu/:tableId]
   → const d = drafts.get(tableId)
   → если есть — пред-наполнить cart

[Заход на TablesPage / SSE table.updated]
   → free-столы → drafts.prune(...) убирает их драфты
   (например, если кассир закрыл стол вручную или другой officiant перевёл его в free)
```

## UI-индикация

На карточке стола (`<TableCard>`), если для него есть draft:

```
┌────┐
│ 5  │
│OCCU│  ← обычный цвет occupied
│98.0│
│  • │  ← маленький значок «есть несохранённый черновик»
└────┘
```

При тапе на такой стол открывается `MenuPage` с уже подгруженной корзиной.

## Лимиты

- Максимум 50 драфтов одновременно (если кто-то наколотил больше — самые старые удаляются по `updatedAt`).
- Размер draft ≤ 16 KB. localStorage в браузерах обычно даёт 5+ МБ — с большим запасом.

## Phase 2 (не в MVP)

- **Синхронизация драфтов между планшетами** — пока нет. Каждый планшет видит свои черновики.
- **Draft TTL** — пока бесконечный (только prune при освобождении стола). Можно добавить «удалять драфты старше 24 ч».
- **Сервер-сайд драфт** — Phase 2: новая сущность `OrderDraft` в backend, чтобы официант мог продолжить с другого устройства.
