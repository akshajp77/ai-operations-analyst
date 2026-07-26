"""FastAPI dependency providers.

Every shared resource an endpoint needs is obtained through a dependency
declared here. Two reasons:

1. **Testability.** ``app.dependency_overrides[get_db] = fake`` swaps a real
   database for a fake without patching imports.
2. **Discoverability.** The full set of things a route can reach is one short
   file, rather than scattered module-level singletons.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError
from app.db.session import Database


def get_app_settings(request: Request) -> Settings:
    """Return the settings this application instance was built with.

    Reads ``app.state.settings`` — the object handed to
    :func:`app.main.create_app` — rather than calling
    :func:`~app.core.config.get_settings` directly.

    That distinction matters. ``get_settings`` is a process-wide LRU cache, so
    resolving through it would ignore any settings injected into ``create_app``
    and leave the application with two disagreeing sources of configuration:
    one used to build the middleware stack, another seen by every endpoint.
    Tests would inject a test configuration and silently observe production
    defaults.

    The fallback covers code paths that build a bare app without the factory.
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings if settings is not None else get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def get_database(request: Request) -> Database:
    """Return the process-wide :class:`Database` created during startup.

    Read from ``app.state`` rather than a module global so that two apps in
    the same interpreter (common in tests) do not share one engine.
    """
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise ConfigurationError("Database was not initialised during application startup.")
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]


async def get_db(database: DatabaseDep) -> AsyncIterator[AsyncSession]:
    """Yield a transactional session for the lifetime of one request.

    Commit/rollback is handled by the context manager, so endpoints and
    services never manage the transaction themselves. One request is one
    transaction — a deliberate simplification that keeps consistency easy to
    reason about. Long-running analysis work does not hold this session; it
    runs in a background job with its own shorter transactions.
    """
    async with database.session() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
