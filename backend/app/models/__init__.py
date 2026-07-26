"""SQLAlchemy ORM models — the persistence shape of the domain.

Kept strictly separate from ``app/schemas`` (the API shape). It is tempting
to serialise ORM objects directly; resist it. The two shapes diverge almost
immediately — a model has ``password_hash``, ``deleted_at``, and internal
foreign keys that must never reach a client, while a schema has computed
fields and flattened relationships that have no column. Coupling them means
every database refactor becomes a breaking API change, and one careless
``response_model`` omission leaks a column.

Planned tables: ``organizations``, ``users``, ``datasets``,
``dataset_versions``, ``analyses``, ``analysis_findings``, ``reports``,
``jobs``, ``audit_events``.

Every model must be importable from this package, or Alembic autogenerate
will not see it and will cheerfully generate a migration that drops the
table.
"""
