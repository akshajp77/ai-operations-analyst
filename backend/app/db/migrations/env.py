"""Alembic migration environment.

Two decisions worth stating:

**The URL comes from Settings, not from alembic.ini.** One source of truth for
the connection string, and no credential in a committed file.

**Migrations run synchronously.** Alembic's async support exists, but the
migration path is a short-lived CLI process where the event loop buys nothing
and costs clarity. ``DatabaseSettings.sync_url`` derives the psycopg DSN from
the asyncpg one, so the two can never drift apart.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models package registers every mapped class on
# `Base.metadata`. Without this import, autogenerate sees an empty schema and
# emits a migration that drops every table.
import app.models  # noqa: F401  (imported for its registration side effect)
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# What autogenerate diffs the live database against.
target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database.sync_url)

# Tables owned by a PostgreSQL extension rather than by our migrations.
# Autogenerate would otherwise see them as unexpected and emit a DROP.
EXCLUDED_TABLES = frozenset({"spatial_ref_sys"})


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Filter objects out of autogenerate.

    Extension-owned tables (PostGIS, pg_stat_statements) and anything created
    outside our migrations must be excluded, or Alembic will generate a
    migration to drop them.
    """
    del obj, reflected, compare_to  # part of the Alembic callback signature
    return not (type_ == "table" and name in EXCLUDED_TABLES)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used to produce a reviewable script for a DBA-gated production change:
    ``alembic upgrade head --sql > migration.sql``.
    """
    context.configure(
        url=settings.database.sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: this process runs a handful of statements and exits.
        # A connection pool would only delay shutdown.
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # Detect column type and server-default changes, which Alembic
            # ignores by default. Silently missing a type change is how a
            # staging schema drifts from production.
            compare_type=True,
            compare_server_default=True,
            # Wrap the whole upgrade in one transaction. PostgreSQL has
            # transactional DDL, so a failed migration rolls back cleanly
            # rather than leaving the schema half-applied.
            transaction_per_migration=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
