"""Cross-cutting HTTP middleware.

Middleware is reserved for concerns that apply to *every* request and that no
individual endpoint should have to remember. Anything narrower belongs in a
FastAPI dependency, where it is explicit at the call site and easy to test.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.correlation import REQUEST_ID_HEADER, request_id_var
from app.core.logging import get_logger

log = get_logger(__name__)

# Endpoints polled by the orchestrator many times a minute. Logging them
# drowns the signal and inflates log spend for zero diagnostic value.
_UNLOGGED_PATHS = frozenset({"/health", "/health/live", "/health/ready", "/metrics"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a correlation id and emit one structured access log per request.

    We reuse an inbound ``X-Request-ID`` when a proxy or the frontend supplies
    one, so a single id spans the browser, the edge, and this service. The id
    is echoed back on the response, which is what lets a user paste it into a
    support ticket and have us find the exact request.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = request_id_var.set(request_id)

        # perf_counter, not time.time: it is monotonic, so an NTP correction
        # mid-request cannot produce a negative duration.
        started = time.perf_counter()
        should_log = request.url.path not in _UNLOGGED_PATHS

        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers produce the response; this block exists
            # only so that a failed request still records its latency, which
            # is exactly the number you want when diagnosing a timeout.
            duration_ms = (time.perf_counter() - started) * 1000
            log.exception(
                "http.request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise
        else:
            duration_ms = (time.perf_counter() - started) * 1000
            if should_log:
                log.info(
                    "http.request",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=round(duration_ms, 2),
                    # request.client is None behind some ASGI servers.
                    client_ip=request.client.host if request.client else None,
                )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            # Reset rather than set-to-None: ContextVar tokens restore the
            # previous value, which keeps nested scopes correct.
            request_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply baseline security headers to every response.

    This API serves JSON to a browser-based client, so the headers that matter
    are the ones preventing content-type confusion and framing. A full CSP
    belongs on the Next.js layer that actually serves HTML.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class MaxBodySizeMiddleware:
    """Reject oversized uploads before they are buffered into memory.

    Written as raw ASGI rather than :class:`BaseHTTPMiddleware` on purpose:
    ``BaseHTTPMiddleware`` reads the request body to pass it along, which is
    precisely the work we are trying to avoid. Here we can inspect
    ``Content-Length`` and short-circuit while the body is still on the wire.

    This is a cheap first gate, not the only one. A client can lie about or
    omit ``Content-Length`` under chunked encoding, so the streaming ingestion
    reader must also enforce the ceiling as it consumes bytes.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _header_value(scope, b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = 0
            if declared > self.max_body_bytes:
                log.warning(
                    "http.body_too_large",
                    declared_bytes=declared,
                    limit_bytes=self.max_body_bytes,
                )
                await _send_json_413(send, declared, self.max_body_bytes)
                return

        await self.app(scope, receive, send)


def _header_value(scope: Scope, name: bytes) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for key, value in headers:
        if key == name:
            return value.decode("latin-1")
    return None


async def _send_json_413(send: Send, declared: int, limit: int) -> None:
    """Emit the standard error envelope without going through FastAPI.

    Hand-rolled because we are below the routing layer here, so the registered
    exception handlers are not available.
    """
    payload: dict[str, Any] = {
        "error": {
            "code": "payload_too_large",
            "message": f"Upload is {declared} bytes; the limit is {limit} bytes.",
            "details": {"limit_bytes": limit, "declared_bytes": declared},
            "request_id": request_id_var.get(),
        }
    }
    body = json.dumps(payload).encode()

    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
