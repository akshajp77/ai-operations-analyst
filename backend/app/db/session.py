"""Async database engine and session lifecycle.

The engine is created during application startup and disposed at shutdown —
never at import time. Import-time engine creation is a common FastAPI mistake
that breaks in three ways: tests import the module and open sockets they
never close; ``uvicorn --workers N`` forks after import and the children
inherit an unusable connection pool; and ``alembic``/CLI scripts pay for a
connection they do not use.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import DatabaseSettings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

log = get_logger(__name__)


class Database:
    """Owns the engine and session factory for one application instance.

    Encapsulated in a class rather than kept as module-level globals so that
    a test can construct an isolated instance pointing at a throwaway
    database, and so the lifetime is explicit rather than implicit in import
    order.
    """

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        """Create the engine and session factory.

        Cheap and synchronous: SQLAlchemy pools are lazy, so no TCP connection
        is opened until the first query. Use :meth:`healthcheck` when you need
        to prove the database is actually reachable.
        """
        if self._engine is not None:
            return

        self._engine = create_async_engine(
            str(self._settings.url),
            echo=self._settings.echo_sql,
            pool_size=self._settings.pool_size,
            max_overflow=self._settings.max_overflow,
            pool_timeout=self._settings.pool_timeout_seconds,
            # Recycle connections before a proxy or the server can silently
            # close them; without this you get intermittent "server closed the
            # connection unexpectedly" errors after idle periods.
            pool_recycle=self._settings.pool_recycle_seconds,
            # Validate a pooled connection before handing it out. One extra
            # round-trip, in exchange for surviving database failovers.
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            # Keep attributes loaded after commit. With the default (True),
            # touching any attribute of a returned ORM object triggers a
            # refresh — which raises once the session is closed, a confusing
            # failure mode when returning models from a service.
            expire_on_commit=False,
            autoflush=False,
        )
        log.info(
            "database.engine_created",
            pool_size=self._settings.pool_size,
            max_overflow=self._settings.max_overflow,
        )

    async def disconnect(self) -> None:
        """Close every pooled connection. Called on shutdown."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            log.info("database.engine_disposed")

    # -- access ------------------------------------------------------------
    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise ConfigurationError("Database.connect() was not called before use.")
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session wrapped in a transaction.

        The unit of work is the whole block: commit on success, roll back on
        any exception. Service code therefore never calls ``commit()`` itself,
        which is what stops half-applied writes from escaping when a later
        step in the same operation fails.
        """
        if self._session_factory is None:
            raise ConfigurationError("Database.connect() was not called before use.")

        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    async def healthcheck(self) -> bool:
        """Return True if the database answers a trivial query.

        Used by the readiness probe. Deliberately does not raise: a probe
        wants a boolean, and turning an outage into an unhandled exception
        would produce a 500 where a clear "not ready" is more useful.
        """
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            log.warning("database.healthcheck_failed", error=str(exc))
            return False
        return True
