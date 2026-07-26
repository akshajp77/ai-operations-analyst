# Architecture

This document explains **why** the system is shaped the way it is. For what
lives where, see the READMEs and the package docstrings — those stay accurate
because they sit next to the code. This file records reasoning, which code
cannot.

---

## 1. The product constraint that drives everything

> An AI analyst that explains what is happening, why, what happens next, and
> what to do — not another dashboard tool.

That framing has one hard engineering consequence:

**A number a user acts on must never come from a language model.**

An operations manager who reschedules staff because we told them order volume
fell 23% needs that 23% to be arithmetic. Language models are extraordinary at
explanation and unreliable at computation, and the failure mode is silent —
a confidently wrong figure reads exactly like a correct one.

So the system is split along that line, and the split is structural rather
than a convention people are asked to remember:

```
   ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
   │  analytics   │───────▶│   findings   │───────▶│      ai      │
   │  (pure, det- │        │ (typed facts │        │  (narrative, │
   │  erministic) │        │  + evidence) │        │  no numbers) │
   └──────────────┘        └──────────────┘        └──────────────┘
     computes every          the ONLY thing          explains and
     number, tested          crossing the            recommends
     with no mocks           boundary
```

`app/ai` receives `Finding` objects, each carrying its own `Evidence` (value,
baseline, change ratio, window). It never receives a dataframe. Three benefits
fall out of one decision:

| Benefit | Why it follows |
| --- | --- |
| No hallucinated statistics | The model has no dataset to hallucinate about. Every figure it can cite was computed upstream. |
| Data minimisation | Customer rows never reach a third party. This is the first question every enterprise security review asks. |
| Bounded cost | Tokens scale with the number of findings, not the size of the upload. A 2 GB file costs roughly what a 2 MB one does. |

Everything below serves this constraint or the ordinary demands of a
multi-tenant SaaS.

---

## 2. Repository shape: monorepo

One repository holding `backend/`, `frontend/`, `packages/`, `infra/`, `docs/`.

**Why.** The frontend and backend share one contract and change together. In
split repositories, a breaking API change is two pull requests that must be
merged in the right order, and CI in neither repository can catch the
mismatch. Here, one commit changes the Pydantic model, the generated types,
and the component that consumes them — and CI verifies all three.

**The cost, acknowledged.** Monorepos need tooling discipline as they grow.
The mitigation is that CI jobs are already split by concern and the two
projects have independent dependency graphs, so introducing path filters or
Turborepo later is additive, not a restructure.

---

## 3. Backend layering

```
  api/         HTTP only. Parse → delegate to one service → return typed response.
   │
   ▼
  services/    Use-case orchestration. The only layer that coordinates others.
   │
   ├──▶ models/ + db/    persistence
   ├──▶ analytics/       pure computation
   ├──▶ ai/              narrative
   └──▶ storage/         blobs

  core/        Config, logging, errors, middleware. Everything may import it;
               it imports nothing.
```

Dependencies point one way. Three rules make the layering real rather than
aspirational:

1. **`analytics` imports no I/O.** Not the database, not HTTP, not OpenAI.
   This is what makes an engine testable with a hand-built dataframe and an
   assertion — no fixtures, no containers, no mocks — and what makes results
   reproducible.
2. **`services` never imports `fastapi`.** Business logic that knows about
   HTTP cannot be called from a worker or a CLI. Services raise domain errors
   (`app/core/exceptions.py`); the API layer translates them to status codes.
3. **`core` imports nothing above it.** It is safe to use from any context.

**Why layered rather than full hexagonal architecture.** Ports-and-adapters
everywhere would mean an interface for each repository and an assembly root to
wire them. At this stage that is ceremony: SQLAlchemy is not being replaced,
and the indirection would cost more in navigation than it returns. We apply
dependency inversion precisely where the boundary is real and likely to move —
`storage` (local ↔ S3) and `analytics.AnalysisEngine` (a plugin point that
will hold six or more implementations).

### Models and schemas are separate on purpose

ORM models (`app/models`) describe rows. Pydantic schemas (`app/schemas`)
describe the API. Serialising models directly is tempting and is a mistake:
the two diverge within weeks — a model gains `password_hash`, `deleted_at`,
internal foreign keys; a schema gains computed fields and flattened
relationships. Coupling them makes every database refactor a breaking API
change, and one forgotten `response_model` leaks a column.

---

## 4. Data engine: Polars, DuckDB, and pandas

Three libraries, three jobs.

- **Polars** is the default for transformation and profiling. Multi-threaded,
  lazily optimised, and far more predictable in memory than pandas on wide
  frames. Predictability matters most: a multi-tenant service must not be
  OOM-killed by one customer's upload.
- **DuckDB** handles anything SQL-shaped — grouped aggregations, joins across
  uploaded files, larger-than-memory scans. A window function reads better as
  SQL than as forty chained dataframe operations, and DuckDB spills to disk
  where an in-memory frame would fail.
- **pandas** stays at the edges, where a statistics or forecasting library
  requires it.

Conversions go through **Arrow**, so they are zero-copy rather than a
serialisation tax. That is precisely why holding all three is affordable.

---

## 5. Multi-tenancy

Shared schema with an indexed `organization_id` discriminator
(`TenantMixin` in `app/db/base.py`), present from the first migration.

**Why not schema-per-tenant.** At thousands of tenants, running a migration
means iterating thousands of schemas, and connection pooling degrades. Shared
schema keeps one migration and one pool.

**Why from day one, before organisations are a user-facing feature.**
Retrofitting tenancy means backfilling every table, rewriting every query, and
auditing every endpoint — while customer data is already live. It is the single
most expensive thing to add late. The column costs nothing now.

**How isolation is enforced.** Repositories filter by `organization_id`.
PostgreSQL row-level security is the intended second line once auth lands, so
a forgotten filter becomes a failed query rather than a data leak. Defence in
depth, because "every developer always remembers" is not a security control.

---

## 6. Asynchronous work

Analysis takes longer than a browser will wait. The API accepts the work,
returns `202 Accepted` with a job id, and the client polls.

**Starting point:** FastAPI `BackgroundTasks` plus a `jobs` table. No extra
infrastructure to run or pay for at launch.

**The known limit, stated rather than discovered:** in-process tasks die with
the process, so a deploy mid-analysis interrupts a job. Because job state is
in PostgreSQL, work is resumable and never silently lost — a restarted
instance requeues anything left `running`.

**The upgrade path:** services are pure orchestration with injected
dependencies, so moving to Celery or ARQ means writing a task shim that calls
the same service method. No service or analytics code changes. Trigger for
that move: meaningful requeue volume, or analyses regularly exceeding ~60s.

---

## 7. The frontend/backend contract

```
Pydantic models  ──►  OpenAPI document  ──►  TypeScript types
 (source of truth)      (generated)            (generated)
```

`make types` runs the pipeline. Both generated artefacts are gitignored, and a
dedicated CI job regenerates them and type-checks the frontend against the
current schema.

**Why this matters more than it looks.** It converts a class of silent runtime
bug — renamed field, changed nullability, removed endpoint — into a compile
error in CI. The failure moves from a customer's screen to an engineer's
editor. Hand-written TypeScript interfaces cannot do that, because they keep
compiling happily against a schema that no longer exists.

---

## 8. Errors

One envelope for every failure, from any endpoint:

```json
{
  "error": {
    "code": "dataset_parse_failed",
    "message": "Row 42 could not be parsed as a date.",
    "details": { "row": 42, "column": "order_date" },
    "request_id": "0f9c1b2e-..."
  }
}
```

`code` is stable and machine-readable — clients branch on it. `message` is for
humans and may be reworded, so clients must never parse it. `request_id` ties
the browser, the access log, and every server-side event together; a user can
paste it into a support ticket and we find the exact request.

Unexpected exceptions log a full traceback server-side and return an opaque
`internal_error`. A leaked stack trace tells an attacker your file layout,
library versions, and sometimes your connection string.

---

## 9. Configuration

Every value enters through `app/core/config.py` and nowhere else. No module
reads `os.environ`.

The part worth highlighting is **fail-fast validation**: in staging and
production the application refuses to boot with a placeholder `SECRET_KEY`, a
missing `OPENAI_API_KEY`, wildcard CORS, or SQL echo enabled. Each check
represents an incident we would rather have at deploy time than at 3am.
Secrets are `SecretStr`, so an accidental log line prints `**********`.

---

## 10. Testing

| Tier | Scope | Speed | Needs |
| --- | --- | --- | --- |
| unit | Pure functions, analytics engines | ms | nothing |
| integration | HTTP app in-process, deps faked | fast | nothing |
| e2e | Real PostgreSQL, real migrations | slow | Docker |

The property that matters: **`pytest` passes on a fresh clone with no
database, no server, and no API key.** A test suite that needs setup is a test
suite people stop running. The e2e tier exists for the things only a real
database can prove — that migrations apply to an empty schema, that
constraints behave as intended.

We prefer hand-written fakes (`FakeDatabase`) over mocks where practical. A
fake is typed, so it breaks loudly when the real interface changes shape; a
mock keeps passing while the code it stands for no longer exists.

---

## 11. Decisions deliberately deferred

Recorded so they read as choices rather than oversights.

| Deferred | Why now is too early | Revisit when |
| --- | --- | --- |
| Redis / task queue | In-process jobs plus a jobs table cover launch load. | Requeue volume rises, or analyses exceed ~60s. |
| Kubernetes | Compose locally, a container platform for deploy. K8s is an operational commitment before it is a benefit. | Multi-region, or autoscaling becomes a real requirement. |
| Row-level security | Repository filtering is sufficient before real auth exists. | Immediately after multi-user auth ships. |
| Read replicas | Analytics reads are heavy but volume is low. | Read load measurably affects write latency. |
| Event sourcing | Ordinary CRUD plus an audit table meets the compliance need. | Point-in-time reconstruction becomes a product requirement. |
| Feature flags | Small team, trunk-based development. | Team or release cadence outgrows a single branch. |
