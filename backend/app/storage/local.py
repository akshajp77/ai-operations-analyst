"""Filesystem-backed :class:`~app.storage.base.ObjectStorage`.

The development and single-node adapter. It exists so the upload path can be
built, tested, and demonstrated without an S3 account, while services stay
written against the protocol rather than against a directory.

**This adapter is not durable.** A container's disk vanishes when the
container does, so deployed environments use the S3 adapter. That switch is a
change to ``STORAGE_BACKEND``, not a change to any service.

Every filesystem call is dispatched through :func:`anyio.to_thread.run_sync`.
``open()`` and ``write()`` look instant on a warm local SSD and are anything
but on a network mount — a blocking write inside a coroutine stalls the event
loop for *every* concurrent request, not just its own.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import anyio.to_thread

from app.core.exceptions import NotFoundError, StorageError
from app.core.logging import get_logger
from app.storage.base import StoredObject

log = get_logger(__name__)

# 1 MiB. Large enough that syscall overhead is negligible, small enough that a
# hundred concurrent transfers cannot add up to a memory problem.
_CHUNK_BYTES = 1024 * 1024


class LocalObjectStorage:
    """Store objects as files beneath a single root directory.

    Args:
        root: Directory that owns every object this instance manages. Created
            on first write if absent.
    """

    def __init__(self, root: Path | str) -> None:
        # Resolved once, at construction: the containment check below compares
        # against this value, and a relative root would make that check depend
        # on the process's current working directory.
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        """The directory every key resolves beneath."""
        return self._root

    # -- Path safety --------------------------------------------------------
    def _resolve(self, key: str) -> Path:
        """Map a storage key to an absolute path inside the root.

        The containment check is the security boundary of this class. A key
        derived from a user-supplied filename can contain ``..`` or a leading
        slash; without this check, ``put("../../../etc/cron.d/x", ...)`` writes
        wherever the process has permission to. Callers sanitise as well, but a
        storage adapter that trusts its caller is one refactor away from a
        path-traversal vulnerability.
        """
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageError(
                "Rejected a storage key that escapes the storage root.",
                details={"key": key},
            )
        return candidate

    # -- ObjectStorage ------------------------------------------------------
    async def put(
        self,
        key: str,
        data: AsyncIterator[bytes],
        *,
        content_type: str,
    ) -> StoredObject:
        """Stream ``data`` to disk, returning metadata about what was written.

        Writes to a ``.partial`` sibling and renames on success. ``rename`` is
        atomic within a filesystem, so a crash mid-write leaves a stray partial
        file rather than a truncated object that ``exists()`` reports as
        complete.

        Raises:
            StorageError: If the key escapes the root, or the write fails.
        """
        path = self._resolve(key)
        staging = path.with_name(f"{path.name}.partial")
        await anyio.to_thread.run_sync(lambda: path.parent.mkdir(parents=True, exist_ok=True))

        digest = hashlib.sha256()
        size_bytes = 0

        try:
            handle = await anyio.to_thread.run_sync(lambda: staging.open("wb"))
            try:
                async for chunk in data:
                    if not chunk:
                        continue
                    digest.update(chunk)
                    size_bytes += len(chunk)
                    await anyio.to_thread.run_sync(handle.write, chunk)
            finally:
                await anyio.to_thread.run_sync(handle.close)
            await anyio.to_thread.run_sync(staging.replace, path)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            raise StorageError(
                "Failed to write the object to local storage.",
                details={"key": key},
            ) from exc
        except BaseException:
            # Includes the size-limit rejection raised by the caller's
            # iterator. Leaving a partial file behind after an aborted upload
            # would slowly fill the disk with data nobody can reach.
            staging.unlink(missing_ok=True)
            raise

        log.info("storage.object_written", key=key, size_bytes=size_bytes, backend="local")

        return StoredObject(
            key=key,
            size_bytes=size_bytes,
            content_type=content_type,
            created_at=datetime.now(UTC),
            checksum=f"sha256:{digest.hexdigest()}",
        )

    async def get(self, key: str) -> AsyncIterator[bytes]:
        """Stream an object's bytes back in chunks.

        Raises:
            NotFoundError: If the key does not exist.
        """
        path = self._resolve(key)
        if not await anyio.to_thread.run_sync(path.is_file):
            raise NotFoundError(f"Object '{key}' was not found.", details={"key": key})

        handle = await anyio.to_thread.run_sync(lambda: path.open("rb"))
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(handle.read, _CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
        finally:
            await anyio.to_thread.run_sync(handle.close)

    async def delete(self, key: str) -> None:
        """Remove an object. Deleting an absent key is not an error."""
        path = self._resolve(key)
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))
        log.info("storage.object_deleted", key=key, backend="local")

    async def exists(self, key: str) -> bool:
        """Return whether an object is present."""
        return bool(await anyio.to_thread.run_sync(self._resolve(key).is_file))

    async def stat(self, key: str) -> StoredObject:
        """Return metadata without reading the body.

        ``content_type`` is inferred from the extension rather than recalled:
        the filesystem stores no per-object headers, and a sidecar file for one
        field is not worth the consistency problem it creates. The S3 adapter
        returns the stored header verbatim.

        Raises:
            NotFoundError: If the key does not exist.
        """
        path = self._resolve(key)
        try:
            stat_result = await anyio.to_thread.run_sync(path.stat)
        except OSError as exc:
            raise NotFoundError(f"Object '{key}' was not found.", details={"key": key}) from exc

        guessed, _ = mimetypes.guess_type(path.name)
        return StoredObject(
            key=key,
            size_bytes=stat_result.st_size,
            content_type=guessed or "application/octet-stream",
            created_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
        )

    async def signed_url(self, key: str, *, expires_in_seconds: int) -> str:  # noqa: ARG002
        """Return a ``file://`` URL for the object.

        Local disk has no signing or expiry mechanism, so ``expires_in_seconds``
        is accepted and ignored to satisfy the protocol. The URL is meaningful
        only to a process on this machine — which is precisely why deployed
        environments use the S3 adapter. This is a development affordance, not
        a security control.

        Raises:
            NotFoundError: If the key does not exist.
        """
        path = self._resolve(key)
        if not await anyio.to_thread.run_sync(path.is_file):
            raise NotFoundError(f"Object '{key}' was not found.", details={"key": key})
        return path.as_uri()

    # -- Maintenance --------------------------------------------------------
    async def clear(self) -> None:
        """Delete every object under the root.

        For test teardown and local resets. Not part of ``ObjectStorage`` and
        never called by a service.
        """
        await anyio.to_thread.run_sync(lambda: shutil.rmtree(self._root, ignore_errors=True))
