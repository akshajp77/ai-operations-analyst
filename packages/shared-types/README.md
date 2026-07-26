# packages/shared-types

The contract between the FastAPI backend and the Next.js frontend.

## The problem this solves

Two languages, one API. Without a mechanism, the request and response shapes
are written twice — once as Pydantic models, once as TypeScript interfaces —
and the copies drift. The drift is silent: someone renames
`created_at` → `uploaded_at` in Python, every Python test passes, and the
frontend renders "Invalid Date" for a week before anyone notices.

## The approach: generate, do not duplicate

```
Pydantic models  ──►  FastAPI OpenAPI document  ──►  TypeScript types
 (source of truth)      openapi.json (generated)      api.generated.ts (generated)
```

One command runs the whole pipeline:

```bash
make types
```

It exports the schema from the application object (no running server needed),
writes `openapi.json` here, and runs `openapi-typescript` to produce
`frontend/src/types/api.generated.ts`.

## Why the backend is the source of truth

The alternative is a schema-first workflow: hand-write an OpenAPI document and
generate both sides from it. That is defensible for a public API with many
external consumers, but it adds a file that must be kept in step with the code
and provides no runtime enforcement.

Here, the Pydantic models *are* the validation that runs on every request. A
type generated from them cannot describe a response the server will not
actually produce. And because generation is a build step, a breaking backend
change surfaces as a TypeScript compile error in CI — before it reaches a
user.

## Both generated files are gitignored

They are build outputs. Committing them means a merge conflict on every
backend change and, eventually, someone resolving that conflict by hand and
introducing exactly the drift this package exists to prevent.

CI regenerates them and fails the build if the frontend does not type-check
against the current schema.

## Operational rules

1. Run `make types` after any change to a Pydantic schema or route signature.
2. Commit the resulting frontend changes **with** the backend change, in one
   pull request. A contract change and its consumer update belong in the same
   reviewable unit.
3. Never hand-edit a generated file. The next regeneration silently discards
   the edit.
