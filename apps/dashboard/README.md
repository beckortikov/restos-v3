# apps/dashboard — Owner Dashboard

Owner-dashboard для собственника сети ресторанов. Next.js на Vercel. Phase 9 ([../../prd-v3/99-ROADMAP.md](../../prd-v3/99-ROADMAP.md)).

## Статус

Папка-плейсхолдер. Реализуется в Phase 9 (после стабильного MVP + кухни/склада/смен/финансов). AI-агент эту папку не трогает (см. [../../CLAUDE.md](../../CLAUDE.md), раздел «Что агент НЕ трогает»).

## Стек (план)

- Next.js 15+
- TypeScript
- Tailwind + shadcn/ui
- React Query / SWR
- NextAuth (или собственный JWT-флоу через backend)
- Развёртывание: Vercel
- Источник данных: облачный backend Django (Phase 9), не локальный

## Команды (когда код появится)

```bash
cd apps/dashboard
pnpm install
pnpm dev
pnpm build
```
