# Backend — AI Operations Analyst

FastAPI service providing data ingestion, deterministic analytics, and
AI-generated narrative over operational datasets.

Full architecture and rationale: [`../docs/architecture.md`](../docs/architecture.md).
Coding standards: [`../CLAUDE.md`](../CLAUDE.md).

## Layout

| Path             | Responsibility                                                          |
| ---------------- | ----------------------------------------------------------------------- |
| `app/api/`       | HTTP only. Parse, delegate to one service, return a typed response.      |
| `app/core/`      | Config, logging, errors, middleware, pagination. Imports nothing above.  |
| `app/db/`        | Engine, session lifecycle, declarative base, Alembic migrations.         |
| `app/models/`    | SQLAlchemy ORM — the persistence shape.                                  |
| `app/schemas/`   | Pydantic — the API shape. Deliberately separate from models.             |
| `app/services/`  | Use-case orchestration. The only layer that coordinates others.          |
| `app/analytics/` | Pure, deterministic engines. No I/O. The product's source of truth.      |
| `app/ai/`        | The only package that calls a model. Narrates findings, never invents.   |
| `app/storage/`   | Object storage interface plus swappable adapters.                        |
| `app/workers/`   | Background jobs.                                                         |
| `app/utils/`     | Small, dependency-free helpers. Deliberately restricted.                 |

Each package's `__init__.py` documents its own rules and planned contents.

## The dependency rule

```
api  ->  services  ->  { models | analytics | ai | storage }
              \
               ->  core   (everything may import core; core imports nothing)
```

Arrows point one way. `analytics` never imports `db`. `services` never imports
`fastapi`. Breaking this is the change most likely to be rejected in review,
because the layering is what keeps the analytics engines testable in
milliseconds and the business logic reusable outside HTTP.

## Local development

Requires Python 3.12 — the pinned, tested runtime. If you do not have it,
`make up` from the repository root runs everything in Docker instead.

```bash
make install-backend    # from the repo root
make env
make migrate
make dev-backend        # http://localhost:8000/docs
```

## Commands

```bash
make test-unit     # fast inner loop — pure tests only
make test-backend  # full suite
make lint-backend  # ruff check + ruff format --check
make typecheck     # mypy --strict
make coverage      # HTML report at backend/htmlcov/index.html
```

## Migrations

```bash
make migration m="add datasets table"   # generate
make migrate                            # apply
make migrate-down                       # roll back one
```

Autogenerate produces a **draft**. Always read the generated file: it cannot
know that adding a `NOT NULL` column to a live table takes an exclusive lock,
and it will happily emit a migration that drops a table you forgot to import
in `app/models/__init__.py`. The generated file's docstring carries the full
review checklist.
