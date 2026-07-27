"""Dataset ingestion: accept an upload, store it, measure it.

This is the first half of the dataset lifecycle. It answers one question —
"can we take this file, and what is in it?" — and deliberately stops there.
Profiling, cleaning, and analysis are separate concerns that run against a
dataset which has already been accepted.

The module imports no web framework. It takes a filename and an async stream
of bytes, which is all an upload actually is; the same function is therefore
callable from a worker draining a queue or a CLI backfilling a directory, not
only from a request handler. That boundary is why the size limit and the parse
both live here rather than in the route.

Ordering is not arbitrary. Validation runs cheapest-first:

1. **Filename and extension** — pure string work, no bytes read. A ``.pdf``
   upload is rejected before anything reaches the disk.
2. **Byte ceiling, enforced while streaming** — the request never has to be
   fully resident to be refused.
3. **Parse** — only once the file is known to be a plausible size and type.

Reversing any two of those turns a cheap rejection into an expensive one, and
the expensive ones are exactly what a hostile client will send.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import PurePosixPath
from typing import IO, Final

import anyio.to_thread
import pandas as pd

from app.core.config import IngestionLimits
from app.core.exceptions import (
    DatasetError,
    DatasetParseError,
    PayloadTooLargeError,
    UnsupportedFileTypeError,
)
from app.core.logging import get_logger
from app.schemas.dataset import DatasetUploadResponse
from app.storage.base import ObjectStorage

log = get_logger(__name__)

# Longest filename most filesystems accept in a single path component. We
# reject rather than truncate: two uploads truncated to the same name are a
# collision the user can neither see nor explain.
_MAX_FILENAME_LENGTH: Final = 255

# Spill the in-flight copy to disk past this point. Small uploads — the common
# case — are parsed straight from memory; a 200 MiB one becomes a temp file
# instead of 200 MiB of heap per concurrent request.
_SPOOL_TO_DISK_BYTES: Final = 8 * 1024 * 1024

_OCTET_STREAM: Final = "application/octet-stream"


def _read_csv(handle: IO[bytes]) -> pd.DataFrame:
    return pd.read_csv(handle)


def _read_tsv(handle: IO[bytes]) -> pd.DataFrame:
    return pd.read_csv(handle, sep="\t")


def _read_xlsx(handle: IO[bytes]) -> pd.DataFrame:
    # Engine pinned rather than sniffed. pandas' auto-detection will fall
    # through to a different reader on a malformed file and produce a confusing
    # error from a library we never intended to invoke.
    return pd.read_excel(handle, engine="openpyxl")


def _read_xls(handle: IO[bytes]) -> pd.DataFrame:
    return pd.read_excel(handle, engine="xlrd")


def _read_parquet(handle: IO[bytes]) -> pd.DataFrame:
    return pd.read_parquet(handle)


# The authoritative list of what this service can actually parse. Intersected
# with ``INGEST_ALLOWED_EXTENSIONS`` at call time, so configuration can narrow
# the set but never widen it into a format with no reader behind it.
_READERS: Final[dict[str, Callable[[IO[bytes]], pd.DataFrame]]] = {
    ".csv": _read_csv,
    ".tsv": _read_tsv,
    ".xlsx": _read_xlsx,
    ".xls": _read_xls,
    ".parquet": _read_parquet,
}

_CONTENT_TYPES: Final[dict[str, str]] = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".parquet": "application/vnd.apache.parquet",
}


def _sanitize_filename(raw: str | None) -> str:
    """Reduce a client-supplied filename to a single safe path component.

    The client controls this string completely. Treating it as a path is how
    ``../../../etc/passwd`` becomes a storage key, so every directory component
    is discarded and only the final name survives. Backslashes are normalised
    first because some clients send ``C:\\Users\\x\\sales.csv``, which POSIX
    path parsing would treat as one long filename rather than as a path.

    Raises:
        DatasetError: If nothing usable remains.
    """
    candidate = (raw or "").replace("\\", "/").strip()
    name = PurePosixPath(candidate).name.strip()

    if not name or name in {".", ".."}:
        raise DatasetError("The upload is missing a usable filename.")
    if len(name) > _MAX_FILENAME_LENGTH:
        raise DatasetError(
            f"Filename exceeds {_MAX_FILENAME_LENGTH} characters.",
            details={"max_length": _MAX_FILENAME_LENGTH, "length": len(name)},
        )
    return name


def _resolve_extension(filename: str, limits: IngestionLimits) -> str:
    """Return the lower-cased extension, or reject the file.

    Raises:
        UnsupportedFileTypeError: If the extension is absent, not configured as
            allowed, or has no reader implementation.
    """
    extension = PurePosixPath(filename).suffix.lower()
    allowed = tuple(ext for ext in limits.allowed_extensions if ext in _READERS)

    if extension not in allowed:
        message = (
            f"'{extension}' is not a supported dataset format."
            if extension
            else "The file has no extension, so its format cannot be determined."
        )
        raise UnsupportedFileTypeError(
            message,
            details={"extension": extension, "allowed_extensions": list(allowed)},
        )
    return extension


async def _tee_with_limit(
    source: AsyncIterator[bytes],
    sink: IO[bytes],
    *,
    max_bytes: int,
) -> AsyncIterator[bytes]:
    """Yield ``source`` onward while copying it into ``sink`` and counting.

    A tee rather than two passes. The alternative — store the object, then read
    it back to parse it — doubles the I/O on every upload for no benefit, since
    the bytes already flow through this process exactly once.

    The ceiling is enforced here, mid-stream, rather than from
    ``Content-Length``. A client can understate or omit that header under
    chunked encoding, so the header check in ``MaxBodySizeMiddleware`` is a
    cheap first gate and this is the one that actually holds.

    Raises:
        PayloadTooLargeError: As soon as the running total exceeds ``max_bytes``.
    """
    total = 0
    async for chunk in source:
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(
                f"Upload exceeds the {max_bytes} byte limit.",
                details={"limit_bytes": max_bytes},
            )
        await anyio.to_thread.run_sync(sink.write, chunk)
        yield chunk


def _parse_table(handle: IO[bytes], extension: str) -> tuple[int, int]:
    """Parse the buffered upload and return ``(rows, columns)``.

    Runs in a worker thread: pandas is synchronous and CPU-bound, and a
    multi-second parse on the event loop would stall every other request in the
    process.

    The whole table is materialised. That is a real memory cost — a 200 MiB CSV
    can expand several-fold as a DataFrame — accepted because the downstream
    profiling and analytics engines need the frame regardless, and because a
    streaming row count would report a number no later stage agrees with.
    ``INGEST_MAX_UPLOAD_BYTES`` is what bounds the exposure.

    Raises:
        DatasetParseError: If the bytes are not a readable table.
    """
    handle.seek(0)
    try:
        frame = _READERS[extension](handle)
    except pd.errors.EmptyDataError as exc:
        raise DatasetParseError("The file contains no data.") from exc
    except (MemoryError, RecursionError):
        # Resource exhaustion, not bad input. Let it surface as a 500 so we
        # investigate it, rather than telling the user their file is corrupt.
        raise
    except Exception as exc:
        # Broad on purpose, and this is the one place in the codebase where
        # that is the right call. Behind `read_excel` and `read_parquet` sit
        # openpyxl, xlrd, and pyarrow, which raise their own unrelated
        # hierarchies — `BadZipFile`, `XLRDError`, `ArrowInvalid`,
        # `UnicodeDecodeError` — none of it documented as a stable contract.
        # Enumerating those types is a list that silently rots with every
        # dependency bump, and each gap in it turns a user's corrupt
        # spreadsheet into a 500 and a spurious page.
        #
        # The exception type is logged so a genuine bug is still diagnosable;
        # only the generic message crosses the boundary to the user.
        log.warning(
            "dataset.parse_failed",
            extension=extension,
            exc_type=type(exc).__name__,
        )
        raise DatasetParseError(
            f"The file could not be read as {extension.lstrip('.').upper()}.",
        ) from exc

    rows, columns = frame.shape
    return int(rows), int(columns)


def _enforce_shape_limits(rows: int, columns: int, limits: IngestionLimits) -> None:
    """Reject a table too large for the analysis pipeline to handle.

    Raises:
        DatasetError: If the row or column count exceeds its configured ceiling.
    """
    if rows > limits.max_rows:
        raise DatasetError(
            f"The dataset has {rows} rows; the limit is {limits.max_rows}.",
            details={"rows": rows, "max_rows": limits.max_rows},
        )
    if columns > limits.max_columns:
        raise DatasetError(
            f"The dataset has {columns} columns; the limit is {limits.max_columns}.",
            details={"columns": columns, "max_columns": limits.max_columns},
        )


async def ingest_upload(
    *,
    filename: str | None,
    chunks: AsyncIterator[bytes],
    storage: ObjectStorage,
    limits: IngestionLimits,
) -> DatasetUploadResponse:
    """Validate, store, and measure one uploaded dataset.

    Args:
        filename: The client-supplied name. Untrusted; sanitised before use.
        chunks: The file's bytes as an async stream.
        storage: Where the file is durably written.
        limits: Configured ceilings on size and shape.

    Returns:
        The identifier assigned to the upload, alongside its measured size and
        shape. Every number is counted, never estimated.

    Raises:
        DatasetError: The filename is unusable, or the table exceeds a shape
            limit.
        UnsupportedFileTypeError: The extension is not an accepted format.
        PayloadTooLargeError: The stream exceeded ``max_upload_bytes``.
        DatasetParseError: The bytes are not a readable table.
    """
    safe_filename = _sanitize_filename(filename)
    extension = _resolve_extension(safe_filename, limits)

    dataset_id = str(uuid.uuid4())
    # Key layout mirrors the tenancy scheme documented in ``app.storage.base``.
    # The organisation prefix is absent only because authentication has not
    # landed yet; the dataset id already isolates one upload's bytes from
    # another's, so two users uploading "orders.csv" never collide.
    key = f"datasets/{dataset_id}/{safe_filename}"

    log.info(
        "dataset.upload_started",
        dataset_id=dataset_id,
        # The filename is user-supplied, and it is logged because an operator
        # debugging a failed upload needs it. It is metadata, not row content —
        # cell values never reach a log line.
        filename=safe_filename,
        extension=extension,
    )

    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_TO_DISK_BYTES) as buffer:
        try:
            stored = await storage.put(
                key,
                _tee_with_limit(chunks, buffer, max_bytes=limits.max_upload_bytes),
                content_type=_CONTENT_TYPES.get(extension, _OCTET_STREAM),
            )
        except PayloadTooLargeError:
            log.warning(
                "dataset.upload_rejected",
                dataset_id=dataset_id,
                reason="payload_too_large",
                limit_bytes=limits.max_upload_bytes,
            )
            # The local adapter discards its own partial write; this covers an
            # adapter that cannot, so a refused upload never leaves bytes
            # behind.
            await storage.delete(key)
            raise

        if stored.size_bytes == 0:
            await storage.delete(key)
            log.warning("dataset.upload_rejected", dataset_id=dataset_id, reason="empty_file")
            raise DatasetParseError("The uploaded file is empty.")

        try:
            rows, columns = await anyio.to_thread.run_sync(_parse_table, buffer, extension)
            _enforce_shape_limits(rows, columns, limits)
        except DatasetError as exc:
            # Covers DatasetParseError too — both are DatasetError subclasses.
            # An unparseable file is not a dataset; keeping its bytes would
            # accumulate garbage nothing will ever reference.
            await storage.delete(key)
            log.warning(
                "dataset.upload_rejected",
                dataset_id=dataset_id,
                reason=exc.code,
                extension=extension,
            )
            raise

    log.info(
        "dataset.upload_completed",
        dataset_id=dataset_id,
        rows=rows,
        columns=columns,
        file_size=stored.size_bytes,
        storage_key=key,
        checksum=stored.checksum,
    )

    return DatasetUploadResponse(
        dataset_id=dataset_id,
        filename=safe_filename,
        rows=rows,
        columns=columns,
        file_size=stored.size_bytes,
    )
