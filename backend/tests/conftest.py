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

import io
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_database, get_object_storage
from app.core.config import Environment, Settings, StorageSettings
from app.core.exceptions import NotFoundError
from app.main import create_app
from app.storage.base import StoredObject


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Configuration for the test suite.

    Constructed explicitly rather than read from the environment so a
    developer's local ``.env`` can never change what the tests assert.

    ``local_path`` points into pytest's temp tree rather than the configured
    default of ``./.data/uploads``. Nothing in the suite should be able to
    write into the working copy, even if a future test forgets to override the
    storage dependency.
    """
    return Settings(
        environment=Environment.TEST,
        debug=True,
        log_level="WARNING",  # keep test output readable
        log_format="console",
        storage=StorageSettings(
            backend="local",
            local_path=str(tmp_path_factory.mktemp("uploads")),
        ),
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


class FakeObjectStorage:
    """In-memory stand-in for :class:`app.storage.base.ObjectStorage`.

    Keeps the service tier's tests genuinely pure — no temp directories, no
    filesystem permissions, no cleanup. Like :class:`FakeDatabase`, it is
    hand-written rather than mocked so that a change to the protocol breaks it
    at import time instead of leaving green tests behind.

    It also records ``deleted_keys``, which is how the tests assert the
    property that matters most on a rejected upload: that we do not leave
    unreferenced bytes behind.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.deleted_keys: list[str] = []

    async def put(
        self,
        key: str,
        data: AsyncIterator[bytes],
        *,
        content_type: str,
    ) -> StoredObject:
        buffer = bytearray()
        # Consuming the iterator here is the point: it is what drives the
        # service's size-limiting tee, so an over-limit upload raises from
        # inside this call exactly as it would against a real adapter.
        async for chunk in data:
            buffer.extend(chunk)

        payload = bytes(buffer)
        self.objects[key] = payload
        self.content_types[key] = content_type
        return StoredObject(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            created_at=datetime.now(UTC),
            checksum=f"sha256:{'0' * 64}",
        )

    async def get(self, key: str) -> AsyncIterator[bytes]:
        if key not in self.objects:
            raise NotFoundError(f"Object '{key}' was not found.")
        yield self.objects[key]

    async def delete(self, key: str) -> None:
        self.deleted_keys.append(key)
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def stat(self, key: str) -> StoredObject:
        if key not in self.objects:
            raise NotFoundError(f"Object '{key}' was not found.")
        return StoredObject(
            key=key,
            size_bytes=len(self.objects[key]),
            content_type=self.content_types.get(key, "application/octet-stream"),
            created_at=datetime.now(UTC),
        )

    async def signed_url(self, key: str, *, expires_in_seconds: int) -> str:
        if key not in self.objects:
            raise NotFoundError(f"Object '{key}' was not found.")
        return f"memory://{key}?expires_in={expires_in_seconds}"


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def app(
    settings: Settings,
    fake_database: FakeDatabase,
    fake_storage: FakeObjectStorage,
) -> Iterator[FastAPI]:
    """A configured application with external dependencies replaced.

    Function-scoped: each test gets a clean override map, so one test cannot
    leak a stubbed dependency into the next.
    """
    application = create_app(settings)
    application.dependency_overrides[get_database] = lambda: fake_database
    application.dependency_overrides[get_object_storage] = lambda: fake_storage
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


@pytest.fixture
def sample_frame(sample_operational_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """The sample rows as a DataFrame: 5 rows, 4 columns."""
    return pd.DataFrame(sample_operational_rows)


@pytest.fixture
def csv_bytes(sample_frame: pd.DataFrame) -> bytes:
    """The sample dataset encoded as a CSV upload."""
    return sample_frame.to_csv(index=False).encode()


@pytest.fixture
def tsv_bytes(sample_frame: pd.DataFrame) -> bytes:
    """The sample dataset encoded as a tab-separated upload."""
    return sample_frame.to_csv(index=False, sep="\t").encode()


@pytest.fixture
def xlsx_bytes(sample_frame: pd.DataFrame) -> bytes:
    """The sample dataset encoded as a real .xlsx workbook.

    Generated rather than committed as a binary fixture: a checked-in
    spreadsheet is opaque in review and drifts from the rows above without
    anyone noticing.
    """
    buffer = io.BytesIO()
    sample_frame.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


async def stream_of(payload: bytes, *, chunk_size: int = 4096) -> AsyncIterator[bytes]:
    """Present ``payload`` as the chunked async stream the service expects."""
    for start in range(0, len(payload), chunk_size):
        yield payload[start : start + chunk_size]
