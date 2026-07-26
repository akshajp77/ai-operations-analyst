<div align="center">

# AI Operations Analyst

**Upload operational data. Get an analyst, not a dashboard.**

Next.js 15 · FastAPI · PostgreSQL · Polars / DuckDB · OpenAI Responses API

</div>

---

## What this is

Operations managers, analysts, and business owners have data and no time. They
export a CSV from an ERP, open it in a spreadsheet, and either eyeball a trend
or hand it to someone who builds a chart nobody revisits.

AI Operations Analyst takes that file and answers four questions:

| Question | How |
| --- | --- |
| **What is happening?** | Automatic cleaning, data-quality scoring, and trend detection |
| **Why is it happening?** | Anomaly detection and driver analysis with evidence attached |
| **What happens next?** | Forecasting with honest confidence intervals |
| **What should I do?** | Ranked, actionable recommendations tied back to findings |

### The one rule that makes it trustworthy

> **The language model never produces a number.**

Every figure is computed by deterministic code in `backend/app/analytics`,
tested without mocks and reproducible on demand. The model receives structured
`Finding` objects — each already carrying its evidence — and writes the
explanation. It never sees the dataset.

This is enforced by the architecture, not by a code-review convention. It
means hallucinated statistics are structurally impossible, customer rows never
reach a third party, and token cost scales with the number of findings rather
than the size of the upload.

Full reasoning: [`docs/architecture.md`](docs/architecture.md).

---

## Quick start

**Everything in Docker** — no local Python or Node required:

```bash
git clone <repository-url> && cd ai-operations-analyst
make env                       # create .env files from the tracked examples
# add your OPENAI_API_KEY to backend/.env
make up
```

| Service | URL |
| --- | --- |
| Web app | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| PostgreSQL | `localhost:5432` |

**Running natively** (faster inner loop; needs Python 3.12 and Node 22):

```bash
make install       # venv + npm install
make env
docker compose up -d db
make migrate
make dev-backend   # terminal 1
make dev-frontend  # terminal 2
```

`make` on its own lists every target.

---

## Repository layout

```
ai-operations-analyst/
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── api/             HTTP layer — thin, typed, no business logic
│   │   ├── core/            Config, logging, errors, middleware, pagination
│   │   ├── db/              Engine, sessions, declarative base, migrations
│   │   ├── models/          SQLAlchemy ORM — the persistence shape
│   │   ├── schemas/         Pydantic — the API shape (deliberately separate)
│   │   ├── services/        Use-case orchestration
│   │   ├── analytics/       Pure deterministic engines — the source of truth
│   │   ├── ai/              The only package that calls a model
│   │   ├── storage/         Object storage interface + adapters
│   │   ├── workers/         Background jobs
│   │   └── utils/           Small, dependency-free helpers
│   └── tests/               unit / integration / e2e
│
├── frontend/                Next.js 15 App Router
│   └── src/
│       ├── app/             Routes and layouts only
│       ├── components/      Cross-feature components (ui/ = shadcn, vendored)
│       ├── features/        Vertical slices — the primary unit of organisation
│       ├── lib/             API client, env validation, utilities
│       ├── hooks/           App-wide React hooks
│       └── types/           Generated API types
│
├── packages/shared-types/   The frontend/backend contract
├── infra/                   Database init, deployment assets
├── docs/                    Architecture and ADRs
└── .github/workflows/       CI
```

### Why these folders

Every directory below exists to answer a question that would otherwise be
answered inconsistently by each engineer who arrives.

**`backend/app/api` — separate from everything else.** The HTTP layer parses a
request, calls one service, and returns a typed response. Keeping it thin is
what lets the same business logic run from a worker, a CLI, or a future gRPC
surface without rewriting it.

**`backend/app/core` — the inward-only layer.** Configuration, logging, error
types, and middleware. Everything may import it; it imports nothing. That
constraint is what keeps the import graph acyclic and makes `core` usable from
a script with no web server present.

**`backend/app/services` — where the decisions live.** The only layer that
coordinates persistence, analytics, AI, and storage. It receives a session and
never manages the transaction, so "one request, one transaction" actually
holds.

**`backend/app/analytics` — pure, and separate for a product reason.** No
database, no network, no model calls. This is where every number the customer
sees is computed. Purity buys millisecond tests with no mocks, reproducible
results, and the trust boundary described above.

**`backend/app/ai` — isolated so it is governable.** One package calls the
model, so cost, latency, prompt versions, retry policy, and graceful
degradation are configured in one place rather than scattered across services.

**`backend/app/models` vs `backend/app/schemas` — two shapes, not one.** Rows
and API payloads diverge within weeks. Coupling them makes every database
refactor a breaking API change and turns one forgotten `response_model` into a
leaked column.

**`backend/app/storage` — an interface with adapters.** Services depend on the
`ObjectStorage` protocol, not on `boto3`. Local disk in development, S3 when
deployed, in-memory in tests — and the whole suite runs with no credentials.

**`backend/app/utils` — deliberately restricted.** "Utils" is where
architecture goes to die. Two rules keep it honest: it may not import from any
other app package, and a helper only moves here when it has a second caller.

**`backend/tests` — split by cost, not by module.** `unit` needs nothing and
runs in milliseconds; `integration` runs the app in-process with fakes; `e2e`
needs real PostgreSQL. Splitting by cost is what lets the fast tier stay fast
enough that people actually run it.

**`frontend/src/features` — vertical slices.** Organising by file type
(`components/`, `hooks/`, `api/`) looks tidy in an empty repository and breaks
around thirty components: one product change touches four distant directories.
A feature slice can be read, owned, and deleted as a unit.

**`frontend/src/components` — only what is genuinely shared.** Single-feature
components stay with their feature. `ui/` holds vendored shadcn/ui source,
excluded from formatting so `npx shadcn diff` remains useful.

**`frontend/src/lib` — the boundaries.** One HTTP client, one env validator,
one class-name helper. Every network call goes through `lib/api/client.ts`, so
timeouts, correlation ids, and error normalisation are decided once.

**`packages/shared-types` — the contract.** Pydantic → OpenAPI → TypeScript,
regenerated by `make types` and verified in CI. This is what turns a renamed
backend field into a compile error instead of a runtime `undefined`.

**`docs/` — reasoning that code cannot hold.** Git records what changed; it
does not record the alternative you rejected and why.

**`infra/` — infrastructure as reviewable files**, so environment setup is a
diff rather than a memory.

---

## Development

```bash
make check         # lint + typecheck + test, both projects. Run before a PR.
make format        # auto-fix
make test-unit     # fast inner loop
make types         # regenerate the API contract after a backend change
make migration m="add datasets table"
make migrate
```

### Quality gates

| Concern | Backend | Frontend |
| --- | --- | --- |
| Lint | Ruff (incl. bandit, bugbear, async checks) | ESLint 9 flat config |
| Format | `ruff format` | Prettier + Tailwind plugin |
| Types | mypy `--strict` | `tsc --noEmit`, strict |
| Tests | pytest (unit/integration/e2e) | Vitest + Testing Library |

CI runs exactly these commands. A green local `make check` means a green CI.

---

## Configuration

Nothing is hardcoded. Every value enters through `backend/app/core/config.py`,
which validates it at startup.

Copy the examples and fill them in:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

In staging and production the application **refuses to boot** with a
placeholder `SECRET_KEY`, a missing `OPENAI_API_KEY`, wildcard CORS, or SQL
echo enabled. Better a failed deploy than a quiet vulnerability.

---

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | Every architectural decision and its rationale |
| [`docs/adr/`](docs/adr/) | Decision records |
| [`CLAUDE.md`](CLAUDE.md) | Coding standards and project context |
| [`backend/README.md`](backend/README.md) | Backend layout, commands, migrations |
| [`packages/shared-types/README.md`](packages/shared-types/README.md) | How the API contract is generated |

---

## Licence

Proprietary. All rights reserved.
