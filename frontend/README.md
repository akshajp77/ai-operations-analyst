# Frontend — AI Operations Analyst

Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui.

Full architecture: [`../docs/architecture.md`](../docs/architecture.md).
Coding standards: [`../CLAUDE.md`](../CLAUDE.md).

## Layout

| Path              | Responsibility                                                 |
| ----------------- | -------------------------------------------------------------- |
| `src/app/`        | Routes, layouts, and route handlers. Composition only.          |
| `src/features/`   | Vertical slices — the primary unit of organisation.             |
| `src/components/` | Cross-feature components. `ui/` is vendored shadcn/ui source.   |
| `src/lib/`        | API client, env validation, shared utilities.                   |
| `src/hooks/`      | App-wide React hooks.                                           |
| `src/types/`      | Generated API types. Do not hand-edit `api.generated.ts`.       |

Each directory has its own `README.md` stating its rules.

## Getting started

```bash
npm install
cp .env.example .env.local
npm run dev          # http://localhost:3000
```

The backend must be running for anything beyond static pages. From the
repository root, `make up` starts the whole stack.

## Commands

```bash
npm run dev            # dev server (Turbopack)
npm run check          # lint + format + typecheck + test — what CI runs
npm run test           # Vitest, watch mode
npm run generate:types # regenerate API types (prefer `make types` from the root)
```

## Three rules that matter most

**1. Server Components by default.** Add `"use client"` only for state,
effects, or browser APIs — and push it to the leaves of the tree. Marking a
page as a client component drags its entire subtree into the JavaScript bundle
the user downloads.

**2. All HTTP goes through `@/lib/api/client`.** Never call `fetch` directly.
The client owns base-URL resolution, timeouts, correlation ids, credentials,
and error normalisation. Bypassing it means re-implementing five things, each
slightly differently.

**3. `NEXT_PUBLIC_` means public.** Any variable with that prefix is inlined
into the browser bundle. Read configuration through `@/lib/env`, which
validates at startup and separates client-safe values from server-only ones.

## The API contract

TypeScript types are generated from the backend's OpenAPI document, so a
renamed Pydantic field becomes a compile error here rather than a runtime
`undefined` in production.

```bash
make types    # from the repository root, after any backend schema change
```

`src/types/api.generated.ts` is a build output and is gitignored. Never edit
it — the next regeneration discards the change.
