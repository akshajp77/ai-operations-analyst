# types/

## `api.generated.ts` — do not edit

Generated from the backend's OpenAPI document by `make types`. It is
gitignored, because a generated file in version control produces a merge
conflict on every backend change and eventually gets "fixed" by hand.

Regenerate it after any backend schema change:

```bash
make types
```

## Why generate rather than hand-write

The backend's Pydantic models already describe every request and response
precisely. Restating them in TypeScript creates two sources of truth that
drift the first time someone renames a field — and the drift is silent,
because the frontend still compiles against its stale copy.

Generating from OpenAPI makes the backend the single source of truth and turns
a breaking change into a **compile error** in the frontend rather than a
runtime `undefined` in production. That is the entire value: the failure moves
from a customer's screen to an engineer's editor.

## Usage

```ts
import type { components } from "@/types/api.generated";

type Dataset = components["schemas"]["DatasetRead"];
```

Alias the ones you use often in a feature's `types.ts` so call sites stay
readable.

## What belongs here instead

Hand-written types that are genuinely frontend-only: view models, UI state
discriminated unions, chart configuration. Anything the API also knows about
should be generated.
