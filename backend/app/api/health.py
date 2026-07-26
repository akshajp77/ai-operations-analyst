"""Liveness and readiness endpoints.

Mounted at the application root, *outside* the ``/api/v1`` prefix, because
probes are infrastructure rather than product. A deployment manifest that
hardcodes ``/health/live`` should not need editing the day we ship ``/api/v2``.

The two probes are split because orchestrators do genuinely different things
with them, and conflating them causes outages:

* **Liveness** — "is this process wedged?" A failure restarts the container.
  It must therefore depend on *nothing external*. If liveness checked the
  database, a brief database blip would restart every pod simultaneously,
  turning a recoverable incident into a total outage.

* **Readiness** — "can this instance serve traffic right now?" A failure
  removes the pod from the load balancer but leaves it running. This one
  *should* check dependencies, so an instance with a broken pool stops
  receiving requests and rejoins on its own once healthy.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app import __version__
from app.api.deps import DatabaseDep, SettingsDep

# `include_in_schema=False` on the router keeps infrastructure endpoints out
# of the OpenAPI document, and therefore out of the generated TypeScript
# client, where they would only be noise.
router = APIRouter(tags=["health"], include_in_schema=False)


class LivenessResponse(BaseModel):
    """Payload for the liveness probe."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str


class DependencyStatus(BaseModel):
    """Health of a single downstream dependency."""

    name: str
    healthy: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Payload for the readiness probe."""

    status: Literal["ready", "degraded"]
    dependencies: list[DependencyStatus] = Field(default_factory=list)


@router.get("/health/live", response_model=LivenessResponse, summary="Liveness probe")
async def liveness(settings: SettingsDep) -> LivenessResponse:
    """Return 200 as long as the process can serve a request."""
    return LivenessResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment.value,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(database: DatabaseDep, response: Response) -> ReadinessResponse:
    """Report whether this instance can currently serve real traffic.

    Returns 503 when any hard dependency is unhealthy so the load balancer
    drains this instance. The body still lists each dependency, which turns a
    failing probe into a diagnosis rather than a mystery.
    """
    database_healthy = await database.healthcheck()

    dependencies = [
        DependencyStatus(
            name="postgresql",
            healthy=database_healthy,
            detail=None if database_healthy else "Connection or query failed.",
        )
    ]

    all_healthy = all(dependency.healthy for dependency in dependencies)
    if not all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if all_healthy else "degraded",
        dependencies=dependencies,
    )
