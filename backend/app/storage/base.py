"""Object storage abstraction.

Uploaded files do not belong in PostgreSQL and do not belong on a container's
local disk in production. This module defines the interface; concrete
adapters implement it for local disk (development) and S3-compatible storage
(deployed).

Defining the interface here — rather than importing ``boto3`` in a service —
is dependency inversion applied where it actually pays off: services depend
on this abstraction, adapters depend on it too, and neither depends on the
other. The practical benefit is that the entire test suite runs against an
in-memory implementation with no network and no credentials.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class StoredObject(BaseModel):
    """Metadata describing one object in storage."""

    model_config = ConfigDict(frozen=True)

    key: str
    size_bytes: int
    content_type: str
    created_at: datetime
    checksum: str | None = None


@runtime_checkable
class ObjectStorage(Protocol):
    """Async interface for durable blob storage.

    Keys are namespaced by tenant — ``{organization_id}/{dataset_id}/{name}``.
    Putting the tenant first is not cosmetic: it makes per-tenant lifecycle
    rules, deletion on account closure, and cost attribution simple prefix
    operations rather than a full-bucket scan.
    """

    async def put(
        self,
        key: str,
        data: AsyncIterator[bytes],
        *,
        content_type: str,
    ) -> StoredObject:
        """Write an object, streaming from ``data``.

        Takes an async iterator rather than ``bytes`` so a 200 MiB upload is
        never fully resident in memory. This is the difference between a
        service that handles ten concurrent uploads and one that is OOM-killed
        by three.
        """
        ...

    def get(self, key: str) -> AsyncIterator[bytes]:
        """Stream an object's contents back.

        Returns the iterator directly rather than being an ``async def``, so
        callers write ``async for chunk in storage.get(key)`` without an
        intermediate await.
        """
        ...

    async def delete(self, key: str) -> None:
        """Remove an object. Idempotent: deleting an absent key is not an error."""
        ...

    async def exists(self, key: str) -> bool:
        """Return whether an object is present."""
        ...

    async def stat(self, key: str) -> StoredObject:
        """Return metadata without transferring the body.

        Raises:
            app.core.exceptions.NotFoundError: If the key does not exist.
        """
        ...

    async def signed_url(self, key: str, *, expires_in_seconds: int) -> str:
        """Return a time-limited URL for direct client access.

        Lets the browser download a generated report straight from storage
        instead of streaming it through the API, which keeps large transfers
        off our request path entirely.
        """
        ...
