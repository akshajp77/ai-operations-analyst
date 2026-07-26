"""Schemas shared across the API surface.

The error models here exist so the error envelope appears in the OpenAPI
document. Without them, ``openapi-typescript`` generates responses typed as
``unknown`` for every non-2xx status, and the frontend's error handling
degrades into casting. Declaring the shape once means the client gets a
precise ``ApiError`` type for free.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """The body of an error response.

    Mirrors ``app.core.exceptions.AppError.to_payload``. The two are asserted
    against each other in ``tests/unit/test_exceptions.py`` — a schema that
    silently drifts from the runtime shape is worse than no schema.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "dataset_parse_failed",
                "message": "Row 42 could not be parsed as a date.",
                "details": {"row": 42, "column": "order_date"},
                "request_id": "0f9c1b2e-6b3a-4a1e-9f0b-2c7d5a8e1234",
            }
        }
    )

    code: str = Field(description="Stable, machine-readable error identifier.")
    message: str = Field(description="Human-readable explanation. Do not parse this.")
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(
        default=None,
        description="Correlation id. Include it in any support request.",
    )


class ErrorResponse(BaseModel):
    """Top-level envelope for every non-2xx response."""

    error: ErrorDetail


class FieldError(BaseModel):
    """One field-level validation failure, for form rendering."""

    field: str
    message: str
    type: str


# Attach to routers so error responses are documented once rather than
# repeated on every endpoint:
#
#     router = APIRouter(responses=ERROR_RESPONSES)
#
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Malformed request."},
    401: {"model": ErrorResponse, "description": "Authentication required."},
    403: {"model": ErrorResponse, "description": "Insufficient permissions."},
    404: {"model": ErrorResponse, "description": "Resource not found."},
    409: {"model": ErrorResponse, "description": "Conflicts with current state."},
    413: {"model": ErrorResponse, "description": "Upload exceeds the size limit."},
    415: {"model": ErrorResponse, "description": "Unsupported file type."},
    422: {"model": ErrorResponse, "description": "Validation failed."},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded."},
    500: {"model": ErrorResponse, "description": "Unexpected server error."},
    502: {"model": ErrorResponse, "description": "A downstream dependency failed."},
}
