"""Request-scoped correlation identifiers.

A :class:`~contextvars.ContextVar` is the correct primitive here: asyncio
gives every task its own copy, so concurrent requests cannot observe each
other's id, and no function in the call chain needs a ``request_id``
parameter it does not otherwise care about.

This lives in its own module (rather than inside ``logging`` or
``middleware``) purely to break an import cycle: the logging processors read
the variable, and the middleware writes it.
"""

from __future__ import annotations

from contextvars import ContextVar

# Header name follows the de-facto convention understood by most reverse
# proxies and API gateways, so an id created at the edge survives into here.
REQUEST_ID_HEADER = "X-Request-ID"

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
