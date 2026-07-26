# CLAUDE.md

Project context and coding standards. Read this before writing code here.

---

## 1. What we are building

**AI Operations Analyst** — a SaaS that turns an uploaded operational dataset
(CSV/Excel) into cleaning, quality analysis, trends, forecasts, anomaly
detection, dashboards, and written recommendations.

We are not building a dashboard tool. We are building an analyst that explains
what is happening, why, what happens next, and what to do.

### The rule that overrides everything

> **The language model never produces a number.**

Every figure a user sees is computed by deterministic code in
`backend/app/analytics`. The AI layer receives typed `Finding` objects — each
carrying its own `Evidence` — and writes prose about them. It never receives a
dataframe.

If a change would let a model-generated value reach the UI as a statistic, it
is wrong regardless of how well it is written. This is the product.

---

## 2. Architecture in one screen

```
frontend (Next.js 15)  ──HTTP──▶  backend (FastAPI)
                                     │
    api/  ──▶  services/  ──▶  { models+db | analytics | ai | storage }
                    │
                    └──▶ core/   (everything imports core; core imports nothing)
```

**Dependency rules — a violation is a blocking review comment:**

| Rule | Why |
| --- | --- |
| `core` imports nothing from `app` | Keeps the graph acyclic; usable from any context |
| `analytics` performs no I/O | Millisecond tests, reproducible results, the trust boundary |
| `services` never imports `fastapi` | Business logic must run from a worker or CLI too |
| `api` contains no business logic | Route = parse, call one service, return |
| Features never import other features | The first step towards an untanglable cycle |

Full reasoning: `docs/architecture.md`.

---

## 3. Non-negotiables

1. **No hardcoded secrets, ever.** Configuration enters through
   `app/core/config.py` (backend) or `src/lib/env.ts` (frontend). Nothing else
   reads `os.environ` or `process.env`.
2. **No `print()` in the backend.** Use `get_logger(__name__)`. Ruff's `T20`
   enforces this.
3. **No `console.log` in the frontend.** ESLint enforces this;
   `console.warn`/`console.error` are allowed.
4. **No `any` in TypeScript.** Use `unknown` and narrow.
5. **No bare `except:` in Python.** Catch the specific exception, or
   `except Exception` with a re-raise or an explicit, commented decision.
6. **Types are not optional.** mypy runs `--strict`; TypeScript runs strict.
   Silencing a checker requires a comment saying why.
7. **Customer data does not reach logs.** Log identifiers, shapes, and counts —
   never cell values.

---

## 4. Python standards

**Style:** Ruff for both linting and formatting. 100 columns. Double quotes.
Run `make format`.

**Typing:**

```python
# Modern syntax. `from __future__ import annotations` at the top of every module.
def profile(frame: pl.DataFrame, columns: list[str] | None = None) -> DatasetProfile: ...
```

- Never `Any` where a real type exists.
- `Protocol` over ABC for interfaces — structural typing keeps implementations
  independently testable and lets a test pass a three-line stub.
- Pydantic for anything crossing a boundary (config, API, AI output).
  Dataclasses for internal value objects.

**Docstrings:** Google style. Every public function, class, and module.

The important part: **document why, not what.** The signature already says what
it takes and returns.

```python
def _require_async_driver(cls, value: PostgresDsn) -> PostgresDsn:
    """Reject a sync DSN early.

    A ``postgresql://`` URL loads fine and then deadlocks the event loop on
    the first query. Catching it at boot is far cheaper than debugging it
    under load.
    """
```

**Errors:** raise domain exceptions from `app/core/exceptions.py`. Never raise
`HTTPException` outside `app/api`. Never invent a second error shape.

**Async:** any function performing I/O is `async`. Never call a blocking
function from an async one — a synchronous `pandas.read_csv` inside a
coroutine stalls the entire event loop for every concurrent user. Use
`anyio.to_thread.run_sync` for CPU-bound or blocking work.

**Naming:** `snake_case` functions, `PascalCase` classes, `_leading_underscore`
private, `UPPER_SNAKE` constants. Names say what a thing is: `dataset_profile`,
not `dp`.

---

## 5. TypeScript / React standards

**Server Components by default.** Add `"use client"` only for state, effects,
or browser APIs — and push it to the leaves. Marking a page client-side drags
its whole subtree into the bundle.

**Types:**

```ts
// Prefer generated API types over hand-written duplicates.
import type { components } from "@/types/api.generated";
type Dataset = components["schemas"]["DatasetRead"];
```

- `interface` for object shapes, `type` for unions and mapped types.
- `import type` for type-only imports — erased at compile time.
- No non-null assertions (`!`). Narrow properly.

**Components:**

- One component per file, named export, `PascalCase` filename.
- Every component accepts `className` and merges via `cn()`.
- Presentational components never fetch; data arrives as props.
- Model UI state as a discriminated union, not four independent booleans:

```ts
type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: Dataset }
  | { status: "error"; error: ApiError };
```

The union makes "loading and error at once" unrepresentable rather than merely
unlikely.

**Data:** all HTTP goes through `@/lib/api/client`. Never call `fetch`
directly. Server state belongs to TanStack Query; `useState` is for UI state
only.

---

## 6. Testing

| Tier | Scope | Marker |
| --- | --- | --- |
| unit | Pure functions, analytics engines. No I/O. Milliseconds. | `@pytest.mark.unit` |
| integration | App in-process, dependencies faked. | `@pytest.mark.integration` |
| e2e | Real PostgreSQL, real migrations. | `@pytest.mark.e2e` |

**`pytest` must pass on a fresh clone with no database, no server, and no API
key.** A suite that needs setup is a suite people stop running.

**Test names state behaviour, not method names:**

```python
def test_returns_503_when_the_database_is_down(self) -> None: ...   # good
def test_readiness(self) -> None: ...                               # useless
```

**Prefer fakes to mocks.** A typed `FakeDatabase` breaks loudly when the real
interface changes; a mock keeps passing while the thing it stands for no
longer exists.

**Every bug fix starts with a failing test.** Otherwise there is no evidence
the fix works, and no protection against its return.

---

## 7. Comments

Comment the **why**. The code already shows the what.

```python
# Good — explains a decision the reader cannot infer:
# perf_counter, not time.time: it is monotonic, so an NTP correction
# mid-request cannot produce a negative duration.

# Useless — restates the line:
# increment the counter
counter += 1
```

Comment-worthy: non-obvious trade-offs, workarounds (with a link), security
reasoning, performance decisions backed by measurement, and anything that
looks wrong but is not.

Delete commented-out code. Git remembers.

---

## 8. Git

Conventional commits:

```
feat(analytics): add seasonality detection to the trend engine
fix(api): return 413 before buffering an oversized upload
refactor(services): extract profiling from dataset_service
```

Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`.

- Branch from `main`: `feat/<short-description>`.
- One logical change per pull request.
- A schema change and its regenerated types belong in the **same** PR.
- `make check` must pass before opening.

---

## 9. Adding a feature — the expected shape

**Backend**

1. Pydantic schemas in `app/schemas/<resource>.py`
2. ORM models in `app/models/<resource>.py`, then `make migration m="..."` and
   **read the generated file**
3. Business logic in `app/services/<resource>_service.py`
4. Pure computation in `app/analytics/<engine>.py`, satisfying
   `AnalysisEngine`
5. Routes in `app/api/v1/routes/<resource>.py`, registered in `router.py`
6. Tests alongside, at the right tier

**Frontend**

1. `make types` to pick up the new API surface
2. Feature slice in `src/features/<feature>/`
3. Route in `src/app/` that composes the feature's components
4. Component tests with Testing Library

---

## 10. Working in this repository

- Read the package `__init__.py` docstring before adding to a package. Each one
  states that package's rules and planned contents.
- Prefer the smallest change that solves the problem. This codebase is young;
  the temptation to build the general case before the second use case is the
  main risk to it.
- If a decision is expensive to reverse, write an ADR in `docs/adr/`.
- If a comment would need to change when unrelated code changes, it is in the
  wrong place.
- When a rule here is wrong, change the rule in a PR — do not quietly work
  around it.
