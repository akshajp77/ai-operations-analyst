"""Health probe behaviour.

Worth testing properly despite looking trivial: these endpoints decide whether
an orchestrator restarts a container or drains it from the load balancer, so a
regression here is an availability incident rather than a feature bug.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import FakeDatabase

pytestmark = pytest.mark.integration


class TestLiveness:
    async def test_returns_ok(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["environment"] == "test"

    async def test_does_not_touch_the_database(
        self, client: AsyncClient, fake_database: FakeDatabase
    ) -> None:
        """Liveness must never depend on an external service.

        If it did, a brief database outage would restart every instance at
        once and turn a recoverable blip into a full outage.
        """
        await client.get("/health/live")
        assert fake_database.healthcheck_calls == 0


class TestReadiness:
    async def test_reports_ready_when_dependencies_are_healthy(self, client: AsyncClient) -> None:
        response = await client.get("/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["dependencies"][0] == {
            "name": "postgresql",
            "healthy": True,
            "detail": None,
        }

    async def test_returns_503_when_the_database_is_down(
        self, client: AsyncClient, fake_database: FakeDatabase
    ) -> None:
        """503 is what removes this instance from the load balancer."""
        fake_database.healthy = False

        response = await client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["dependencies"][0]["healthy"] is False
        # The body still explains *which* dependency failed, so a failing
        # probe is a diagnosis rather than a mystery.
        assert body["dependencies"][0]["detail"]


class TestRequestContext:
    async def test_echoes_a_correlation_id(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")
        assert response.headers["x-request-id"]

    async def test_reuses_an_inbound_correlation_id(self, client: AsyncClient) -> None:
        """An id set at the edge must survive, or traces fragment per hop."""
        response = await client.get("/health/live", headers={"X-Request-ID": "trace-from-the-edge"})
        assert response.headers["x-request-id"] == "trace-from-the-edge"

    async def test_applies_security_headers(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"


class TestErrorContract:
    async def test_unknown_route_uses_the_standard_error_envelope(
        self, client: AsyncClient
    ) -> None:
        """Every error, including routing 404s, has one shape.

        The frontend deserialises a single error type; a bare Starlette
        ``{"detail": "Not Found"}`` would be a second shape to special-case.
        """
        response = await client.get("/no-such-route")

        assert response.status_code == 404
        error = response.json()["error"]
        assert set(error) == {"code", "message", "details", "request_id"}
        assert error["request_id"]
