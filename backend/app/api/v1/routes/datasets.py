"""Dataset endpoints.

The route layer's entire job: turn an HTTP request into service arguments,
call one service, return its result. There is no validation, no branching, and
no error translation here — extension rules live in the service because a
worker ingesting from a bucket needs them too, and status codes live on the
domain exceptions because that keeps the mapping in one place instead of
duplicated across every handler.

If this file ever grows an ``if``, the logic belongs in a service.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Final

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import ObjectStorageDep, SettingsDep
from app.schemas.common import ERROR_RESPONSES
from app.schemas.dataset import DatasetUploadResponse
from app.services import dataset_service

router = APIRouter(responses=ERROR_RESPONSES)

# Matches the storage adapter's chunk size, so bytes move through the tee in
# one consistent unit rather than being re-fragmented at each hop.
_READ_CHUNK_BYTES: Final = 1024 * 1024


async def _stream(upload: UploadFile) -> AsyncIterator[bytes]:
    """Adapt Starlette's ``UploadFile`` to a plain async byte stream.

    This exists so the service never sees a web framework type. It is also
    what keeps a large upload off the heap: ``UploadFile.read()`` with a size
    argument reads incrementally from Starlette's spooled buffer, whereas the
    argument-less form materialises the entire file as one ``bytes`` object.
    """
    while chunk := await upload.read(_READ_CHUNK_BYTES):
        yield chunk


@router.post(
    "/upload",
    response_model=DatasetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a dataset",
    description=(
        "Accepts a CSV or Excel file, stores it, and returns its measured size "
        "and shape. Row and column counts are produced by parsing the file — "
        "they are never estimated."
    ),
)
async def upload_dataset(
    storage: ObjectStorageDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="The dataset to analyse.")],
) -> DatasetUploadResponse:
    """Ingest one uploaded dataset.

    The upload is rejected with 415 for an unsupported extension, 413 when it
    exceeds ``INGEST_MAX_UPLOAD_BYTES``, and 422 when the bytes cannot be
    parsed as a table. Those statuses come from the domain exceptions the
    service raises; this handler translates nothing.
    """
    return await dataset_service.ingest_upload(
        filename=file.filename,
        chunks=_stream(file),
        storage=storage,
        limits=settings.ingest,
    )
