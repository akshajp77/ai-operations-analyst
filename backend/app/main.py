"""Application composition root.

This is the only module allowed to know how the pieces fit together: it
builds settings, installs logging, opens the database, mounts middleware, and
registers routes. Everything else receives what it needs by injection.

Exposed as a ``create_app()`` factory rather than a module-level ``app``
singleton so tests can build an isolated instance with overridden
dependencies. The module-level ``app`` at the bottom exists only because
``uvicorn app.main:app`` needs something to import.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app import __version__
from app.api import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    MaxBodySizeMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import Database

log = get_logger(__name__)


def _generate_operation_id(route: APIRoute) -> str:
    """Produce clean, stable operation ids for the OpenAPI document.

    FastAPI's default is ``list_datasets_api_v1_datasets_get`` — which becomes
    the method name in the generated TypeScript client. Using the first tag
    plus the function name yields ``datasets_list_datasets``, so the frontend
    reads sensibly instead of drowning in path fragments.

    Because these ids are part of the client's surface, renaming a route
    function is a breaking change for the frontend. That is a feature: the
    rename shows up in the generated diff during code review.
    """
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}_{route.name}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage resources whose lifetime matches the application's.

    Everything acquired before ``yield`` is released after it, in reverse
    order. A failure here aborts startup — which is correct: a process that
    cannot construct its dependencies should never enter the load balancer.
    """
    settings: Settings = app.state.settings

    database = Database(settings.database)
    database.connect()
    app.state.database = database

    log.info(
        "application.startup",
        environment=settings.environment.value,
        version=__version__,
        debug=settings.debug,
    )

    try:
        yield
    finally:
        await database.disconnect()
        log.info("application.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and wire the FastAPI application.

    Args:
        settings: Injected configuration. Defaults to the process-wide
            settings; tests pass a purpose-built instance.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        summary="Upload operational data; receive analysis, forecasts, and recommendations.",
        # Interactive docs are a development and internal-tooling affordance.
        # In a deployed environment they are a free description of the attack
        # surface, so they are switched off.
        docs_url=None if settings.environment.is_deployed else "/docs",
        redoc_url=None if settings.environment.is_deployed else "/redoc",
        openapi_url=None if settings.environment.is_deployed else "/openapi.json",
        # No custom response class. Current FastAPI serialises straight to JSON
        # bytes through Pydantic whenever a return type or `response_model` is
        # declared, which is faster than routing through ORJSONResponse and
        # keeps one serialisation path. Every endpoint here is annotated, so we
        # get that path for free — which is also why annotations are mandatory
        # rather than merely encouraged.
        generate_unique_id_function=_generate_operation_id,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # -- Middleware --------------------------------------------------------
    # `add_middleware` prepends, so the LAST registered is the OUTERMOST.
    # Effective request order:
    #   CORS -> RequestContext -> MaxBodySize -> SecurityHeaders -> routes
    #
    # CORS must be outermost, or an error response produced by an inner
    # middleware arrives without CORS headers and the browser reports an
    # opaque network failure instead of the real status code.
    #
    # RequestContext sits above MaxBodySize so that even a rejected oversized
    # upload is logged and carries a correlation id.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        MaxBodySizeMiddleware,
        max_body_bytes=settings.ingest.max_upload_bytes,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        # Lets the browser client read the correlation id off the response so
        # it can attach it to client-side error reports.
        expose_headers=["X-Request-ID"],
    )

    # -- Errors ------------------------------------------------------------
    register_exception_handlers(app)

    # -- Routes ------------------------------------------------------------
    # Probes are unversioned infrastructure; product routes are versioned.
    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
