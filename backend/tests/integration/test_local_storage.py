"""Filesystem storage adapter behaviour.

Marked integration rather than unit because it genuinely touches disk, which
is the whole point: the properties worth proving here — atomic replace, path
containment, no partial file after a failure — exist precisely because a real
filesystem is involved. A test against a mocked ``open()`` would prove none of
them.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.exceptions import NotFoundError, StorageError
from app.storage.base import ObjectStorage, StoredObject
from app.storage.local import LocalObjectStorage

pytestmark = pytest.mark.integration


async def _stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _collect(source: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in source])


@pytest.fixture
def storage(tmp_path: Path) -> LocalObjectStorage:
    return LocalObjectStorage(tmp_path / "objects")


class TestProtocolConformance:
    def test_satisfies_the_object_storage_protocol(self, storage: LocalObjectStorage) -> None:
        """Services depend on the protocol, never on this class.

        The structural check that really matters is mypy's, at the
        ``build_object_storage`` return annotation; this catches an accidental
        method removal at runtime too.
        """
        assert isinstance(storage, ObjectStorage)


class TestRoundTrip:
    async def test_returns_the_bytes_that_were_written(self, storage: LocalObjectStorage) -> None:
        await storage.put(
            "datasets/abc/orders.csv", _stream(b"a,b\n1,2\n"), content_type="text/csv"
        )

        assert await _collect(storage.get("datasets/abc/orders.csv")) == b"a,b\n1,2\n"

    async def test_reassembles_a_chunked_write_in_order(self, storage: LocalObjectStorage) -> None:
        """Chunk boundaries must not reorder or drop data."""
        await storage.put("k", _stream(b"one", b"two", b"three"), content_type="text/plain")

        assert await _collect(storage.get("k")) == b"onetwothree"

    async def test_creates_missing_parent_directories(self, storage: LocalObjectStorage) -> None:
        """Keys nest by dataset id; nothing pre-creates those folders."""
        result = await storage.put(
            "deeply/nested/path/x.csv", _stream(b"a\n"), content_type="text/csv"
        )

        assert result.key == "deeply/nested/path/x.csv"
        assert await storage.exists("deeply/nested/path/x.csv")


class TestMetadata:
    async def test_counts_the_bytes_it_wrote(self, storage: LocalObjectStorage) -> None:
        result = await storage.put("k", _stream(b"12345", b"678"), content_type="text/csv")

        assert result.size_bytes == 8

    async def test_records_a_sha256_of_the_content(self, storage: LocalObjectStorage) -> None:
        """The checksum is what makes a later integrity check possible."""
        payload = b"region,units\nnorth,10\n"

        result = await storage.put("k", _stream(payload), content_type="text/csv")

        assert result.checksum == f"sha256:{hashlib.sha256(payload).hexdigest()}"

    async def test_stat_reports_the_size_without_reading_the_body(
        self, storage: LocalObjectStorage
    ) -> None:
        await storage.put("k.csv", _stream(b"x" * 100), content_type="text/csv")

        stat = await storage.stat("k.csv")

        assert isinstance(stat, StoredObject)
        assert stat.size_bytes == 100
        assert stat.content_type == "text/csv"
        # Timezone-aware, so comparing it against another timestamp cannot
        # raise or silently compare across zones.
        assert stat.created_at.tzinfo is not None

    async def test_signed_url_points_at_the_file(self, storage: LocalObjectStorage) -> None:
        await storage.put("k.csv", _stream(b"a\n"), content_type="text/csv")

        url = await storage.signed_url("k.csv", expires_in_seconds=60)

        assert url.startswith("file://")
        assert url.endswith("k.csv")


class TestMissingObjects:
    async def test_get_raises_not_found(self, storage: LocalObjectStorage) -> None:
        with pytest.raises(NotFoundError):
            await _collect(storage.get("nope.csv"))

    async def test_stat_raises_not_found(self, storage: LocalObjectStorage) -> None:
        with pytest.raises(NotFoundError):
            await storage.stat("nope.csv")

    async def test_exists_is_false(self, storage: LocalObjectStorage) -> None:
        assert await storage.exists("nope.csv") is False

    async def test_delete_is_idempotent(self, storage: LocalObjectStorage) -> None:
        """The service deletes on every rejection path; some of those overlap."""
        await storage.delete("never-existed.csv")
        await storage.delete("never-existed.csv")


class TestPathContainment:
    """The security boundary. A key is derived from a client-supplied name."""

    @pytest.mark.parametrize(
        "key",
        ["../escaped.csv", "datasets/../../escaped.csv", "/etc/passwd"],
    )
    async def test_rejects_a_key_that_escapes_the_root(
        self, storage: LocalObjectStorage, key: str
    ) -> None:
        with pytest.raises(StorageError):
            await storage.put(key, _stream(b"pwned"), content_type="text/csv")

    async def test_writes_nothing_outside_the_root(
        self, storage: LocalObjectStorage, tmp_path: Path
    ) -> None:
        with pytest.raises(StorageError):
            await storage.put("../escaped.csv", _stream(b"pwned"), content_type="text/csv")

        assert not (tmp_path / "escaped.csv").exists()


class TestFailedWrites:
    async def test_leaves_no_partial_file_when_the_source_fails(
        self, storage: LocalObjectStorage
    ) -> None:
        """A stream can die mid-upload — a dropped connection, or the size
        ceiling tripping inside the service's tee.

        What must not survive is a half-written object that ``exists()``
        reports as complete, because the next stage would parse a truncated
        file and report confident, wrong numbers.
        """

        async def failing_stream() -> AsyncIterator[bytes]:
            yield b"first chunk"
            raise RuntimeError("connection dropped")

        with pytest.raises(RuntimeError):
            await storage.put("k.csv", failing_stream(), content_type="text/csv")

        assert await storage.exists("k.csv") is False
        # Nor may the staging file linger and slowly fill the disk.
        assert list(storage.root.rglob("*.partial")) == []

    async def test_a_failed_write_does_not_clobber_an_existing_object(
        self, storage: LocalObjectStorage
    ) -> None:
        """Staging plus atomic rename is what buys this.

        Writing in place would leave the previous good object truncated.
        """
        await storage.put("k.csv", _stream(b"original"), content_type="text/csv")

        async def failing_stream() -> AsyncIterator[bytes]:
            yield b"replacement"
            raise RuntimeError("connection dropped")

        with pytest.raises(RuntimeError):
            await storage.put("k.csv", failing_stream(), content_type="text/csv")

        assert await _collect(storage.get("k.csv")) == b"original"


class TestOverwrite:
    async def test_replaces_an_existing_object(self, storage: LocalObjectStorage) -> None:
        await storage.put("k.csv", _stream(b"old"), content_type="text/csv")
        await storage.put("k.csv", _stream(b"new content"), content_type="text/csv")

        assert await _collect(storage.get("k.csv")) == b"new content"

    async def test_delete_removes_the_object(self, storage: LocalObjectStorage) -> None:
        await storage.put("k.csv", _stream(b"data"), content_type="text/csv")

        await storage.delete("k.csv")

        assert await storage.exists("k.csv") is False
