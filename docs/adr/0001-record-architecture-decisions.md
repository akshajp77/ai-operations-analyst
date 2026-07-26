# ADR 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

Six months from now someone will look at a boundary in this codebase — the one
keeping computed numbers away from the language model, say — and see only
overhead. Without the reasoning written down, the cheapest move is to remove
it, and the incident that follows re-teaches a lesson we already paid for.

Git history does not solve this. A commit records *what* changed; the
trade-off that was considered and rejected is exactly what does not survive
into the diff.

## Decision

Significant architectural decisions are recorded as ADRs in `docs/adr/`, one
Markdown file per decision, numbered sequentially and never renumbered.

**What warrants an ADR:** anything expensive to reverse. Choosing a database, a
tenancy model, an async strategy, an auth approach, a public contract format.
Roughly: if undoing it would take more than a week, write it down.

**What does not:** library choices with a cheap exit, naming conventions,
directory layout. Those belong in `CLAUDE.md` or a package docstring.

**Format:** Context (the forces at play), Decision (what we chose),
Consequences (what we accept as a result, including the bad parts).

**ADRs are immutable.** A decision that gets reversed is not edited — its
status becomes `Superseded by ADR-00NN`, and a new ADR explains the change.
The record of having believed something is part of the history.

## Consequences

**Good.** New engineers can read the reasoning instead of reverse-engineering
it. Reversals become deliberate — "ADR-0004 assumed X, and X is no longer
true" — rather than accidental. Writing the Consequences section forces
honesty about costs at the moment of choosing, when it is cheapest to change
course.

**Bad.** It is a habit that has to be maintained, and an unmaintained ADR
directory is worse than none: it implies decisions are recorded when they are
not. The mitigation is a narrow bar for what qualifies, so the practice stays
light enough to actually follow.

## Backlog

Decisions already made in `docs/architecture.md` that should be promoted to
their own ADRs as they are challenged:

- 0002 — Deterministic analytics as the sole source of numeric truth
- 0003 — Shared-schema multi-tenancy
- 0004 — Polars + DuckDB + pandas, bridged by Arrow
- 0005 — OpenAPI-generated TypeScript as the frontend/backend contract
- 0006 — In-process background jobs with database-backed state
