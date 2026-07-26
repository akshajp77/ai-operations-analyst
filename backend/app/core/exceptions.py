"""Domain exception hierarchy and the single HTTP error contract.

Design rules this module enforces:

**Services raise domain errors, not HTTP errors.** A service says
``raise DatasetNotFoundError(dataset_id)``. It does not know or care that the
caller is HTTP. This keeps the business layer reusable from a worker, a CLI,
or a future gRPC surface, and it keeps status-code policy in exactly one
place.

**Every error response has the same shape.** The frontend deserialises one
type, no matter which endpoint failed::

    {
      "error": {
        "code": "dataset_not_found",
        "message": "Dataset 'ds_123' was not found.",
        "details": {"dataset_id": "ds_123"},
        "request_id": "0f9c1b2e-..."
      }
    }

``code`` is a stable machine-readable identifier the client may branch on.
``message`` is human-readable and may change. Clients must never parse
``message``.

**Unexpected exceptions never leak internals.** The catch-all handler logs the
full traceback server-side and returns an opaque ``internal_error`` to the
client. Leaking a stack trace tells an attacker your file layout, library
versions, and sometimes your connection string.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import request_id_var
from app.core.logging import get_logger

log = get_logger(__name__)

# Starlette renamed two of its status constants: HTTP_413_REQUEST_ENTITY_TOO_LARGE
# became HTTP_413_CONTENT_TOO_LARGE, and HTTP_422_UNPROCESSABLE_ENTITY became
# HTTP_422_UNPROCESSABLE_CONTENT. The old names emit a DeprecationWarning on
# current versions and the new names are absent from older ones, so neither
# spelling works across the range we support. Plain integers work on both, and
# these two codes are readable without a constant anyway.
HTTP_413_CONTENT_TOO_LARGE = 413
HTTP_422_UNPROCESSABLE_CONTENT = 422


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------
class AppError(Exception):
    """Base class for every error this application raises deliberately.

    A single ``except AppError`` at the boundary can therefore distinguish
    "a condition we modelled and understand" from "a bug", and treat the two
    very differently.

    Attributes:
        code: Stable, machine-readable identifier (snake_case). Part of our
            public API contract — changing one is a breaking change.
        message: Human-readable explanation, safe to show to the end user.
        status_code: HTTP status used when this surfaces over HTTP.
        details: Structured context. Must never contain secrets or raw
            customer data, because it is serialised to the client.
    """

    code: str = "app_error"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_payload(self) -> dict[str, Any]:
        """Render the public error envelope."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id_var.get(),
            }
        }


# --- Client-caused (4xx) ---------------------------------------------------
class NotFoundError(AppError):
    """A referenced resource does not exist, or is not visible to the caller.

    We deliberately do not distinguish "absent" from "belongs to another
    tenant": doing so turns the endpoint into an existence oracle that leaks
    other customers' identifiers.
    """

    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class ValidationFailedError(AppError):
    """Input is well-formed but semantically invalid."""

    code = "validation_failed"
    status_code = HTTP_422_UNPROCESSABLE_CONTENT


class ConflictError(AppError):
    """The request conflicts with the current state of the resource."""

    code = "conflict"
    status_code = status.HTTP_409_CONFLICT


class UnauthorizedError(AppError):
    """No valid credentials were presented."""

    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(AppError):
    """Credentials are valid but insufficient for this action."""

    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN


class RateLimitedError(AppError):
    """The caller exceeded a quota."""

    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


class PayloadTooLargeError(AppError):
    """Upload exceeded ``INGEST_MAX_UPLOAD_BYTES``."""

    code = "payload_too_large"
    status_code = HTTP_413_CONTENT_TOO_LARGE


# --- Domain-specific -------------------------------------------------------
class DatasetError(AppError):
    """Base for problems with a user-supplied dataset.

    Separated from generic validation because these errors are *product
    surface*: the UI renders them as actionable guidance ("row 42 has a date
    we could not parse"), not as a generic failure toast.
    """

    code = "dataset_error"
    status_code = HTTP_422_UNPROCESSABLE_CONTENT


class UnsupportedFileTypeError(DatasetError):
    code = "unsupported_file_type"
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


class DatasetParseError(DatasetError):
    """The file could not be decoded into a table."""

    code = "dataset_parse_failed"


class InsufficientDataError(DatasetError):
    """The dataset is valid but too small or too sparse for this analysis.

    Forecasting six months from four data points is not an error the maths
    layer should silently absorb — it is a result the user must be told
    about honestly.
    """

    code = "insufficient_data"


class AnalysisError(AppError):
    """An analysis engine could not produce a result."""

    code = "analysis_failed"
    status_code = HTTP_422_UNPROCESSABLE_CONTENT


# --- Dependency failures (5xx) --------------------------------------------
class ExternalServiceError(AppError):
    """A downstream dependency failed or timed out."""

    code = "external_service_error"
    status_code = status.HTTP_502_BAD_GATEWAY


class AIProviderError(ExternalServiceError):
    """The model provider errored, timed out, or returned unusable output.

    Its own type because the recovery strategy is distinct: we can often
    degrade gracefully by returning the deterministic analysis without the
    generated narrative, which is still valuable to the user.
    """

    code = "ai_provider_error"


class StorageError(AppError):
    """Object storage read/write failed."""

    code = "storage_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR


class ConfigurationError(AppError):
    """The service is misconfigured. Almost always fatal at startup."""

    code = "configuration_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# HTTP boundary handlers
# ---------------------------------------------------------------------------
def _envelope(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


async def _handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    """Render a deliberate domain error.

    Logged at WARNING, not ERROR: these are expected outcomes of a running
    system (a user asked for a dataset that does not exist), and paging an
    engineer for them would train the team to ignore alerts.
    """
    if not isinstance(exc, AppError):  # pragma: no cover — registration guarantees this
        return await _handle_unexpected_error(_request, exc)
    log.warning(
        "request.domain_error",
        error_code=exc.code,
        status_code=exc.status_code,
        detail=exc.message,
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    """Reshape FastAPI's validation failure into our standard envelope.

    FastAPI's default 422 body is a bare ``{"detail": [...]}`` list, which is
    a second error shape the frontend would otherwise have to special-case.
    We keep the per-field information — it is genuinely useful for forms — but
    move it under ``details.fields``.
    """
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        return await _handle_unexpected_error(_request, exc)
    fields = [
        {
            # `loc` is like ("body", "dataset", "name"); drop the first
            # element, which only says where in the request it came from.
            "field": ".".join(str(part) for part in error["loc"][1:]) or "__root__",
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    log.warning("request.validation_error", field_count=len(fields))
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content=_envelope(
            "validation_failed",
            "The request payload failed validation.",
            {"fields": fields},
        ),
    )


async def _handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    """Normalise Starlette's own HTTPException (404 routing, 405, ...)."""
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        return await _handle_unexpected_error(_request, exc)
    try:
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    except ValueError:  # non-standard status code
        code = "http_error"
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


async def _handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Last line of defence: an exception we did not model.

    This is always a bug. Log the full traceback with the request id so it can
    be correlated, then return a deliberately uninformative body.
    """
    log.exception("request.unhandled_exception", exc_type=type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            "internal_error",
            "An unexpected error occurred. The incident has been logged.",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the handlers above onto the application.

    Order matters only in that FastAPI resolves the most specific registered
    class first; ``Exception`` is the catch-all and must be present, or
    Starlette will return an untyped ``text/plain`` 500.
    """
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
