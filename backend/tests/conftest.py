"""Shared pytest fixtures.

The test strategy is a pyramid, and the fixtures here exist to keep its base
wide:

* **unit** — pure functions and analytics engines. No fixtures beyond plain
  data. Milliseconds. These are the tests that must stay fast enough that
  nobody hesitates to run them.
* **integration** — the HTTP app in-process via ASGI transport, with
  dependencies overridden. No real network. Fast enough for every commit.
* **e2e** — real PostgreSQL from Docker Compose. Run in CI and before release.

The important property: no test requires a running server, a real database,
or an OpenAI key *by default*. A new engineer clones the repository, installs
dependencies, runs ``pytest``, and everything passes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_database
from app.core.config import Environment, Settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Configuration for the test suite.

    Constructed explicitly rather than read from the environment so a
    developer's local ``.env`` can never change what the tests assert.
    """
    return Settings(
        environment=Environment.TEST,
        debug=True,
        log_level="WARNING",  # keep test output readable
        log_format="console",
    )


class FakeDatabase:
    """Stand-in for :class:`app.db.session.Database`.

    Satisfies the surface the API layer actually uses. A hand-written fake
    beats a mock here: it is typed, it fails loudly if the real interface
    changes shape, and the readiness-degraded path becomes a one-line
    parameter rather than a mock configuration incantation.
    """

    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.healthcheck_calls = 0

    async def healthcheck(self) -> bool:
        self.healthcheck_calls += 1
        return self.healthy


@pytest.fixture
def fake_database() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def app(settings: Settings, fake_database: FakeDatabase) -> Iterator[FastAPI]:
    """A configured application with external dependencies replaced.

    Function-scoped: each test gets a clean override map, so one test cannot
    leak a stubbed dependency into the next.
    """
    application = create_app(settings)
    application.dependency_overrides[get_database] = lambda: fake_database
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client speaking to the app in-process.

    ``ASGITransport`` skips the network entirely — no port binding, no socket,
    no flakiness from a race between server startup and the first request.
    ``LifespanManager`` still runs startup and shutdown, so lifespan bugs are
    caught here rather than in production.
    """
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
    ):
        yield http_client


@pytest.fixture
def sample_operational_rows() -> list[dict[str, Any]]:
    """A tiny, synthetic operations dataset.

    Deliberately imperfect: it carries a missing value, a repeated revenue
    figure, and an obvious outlier, because the cleaning and quality engines
    must be tested against realistic mess rather than against tidy data.
    """
    return [
        {"order_date": "2026-01-01", "region": "north", "units": 120, "revenue": 2400.0},
        {"order_date": "2026-01-02", "region": "north", "units": 135, "revenue": 2700.0},
        {"order_date": "2026-01-03", "region": "south", "units": None, "revenue": 1980.0},
        {"order_date": "2026-01-04", "region": "south", "units": 99, "revenue": 1980.0},
        {"order_date": "2026-01-05", "region": "north", "units": 9999, "revenue": 199_980.0},
    ]
