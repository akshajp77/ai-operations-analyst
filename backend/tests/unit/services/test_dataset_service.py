"""Dataset ingestion behaviour.

This is the trust boundary of the product. Everything downstream — profiling,
trends, forecasts, the written narrative — is computed from what this service
accepts and from the row and column counts it reports. A dataset admitted here
that should have been refused, or a row count off by one, is wrong in every
report that follows.

So these tests assert two distinct things, and both matter:

* the numbers returned are the numbers in the file, and
* a rejected upload leaves nothing behind.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator

import pandas as pd
import pytest

from app.core.config import IngestionLimits
from app.core.exceptions import (
    DatasetError,
    DatasetParseError,
    PayloadTooLargeError,
    UnsupportedFileTypeError,
)
from app.services.dataset_service import ingest_upload
from tests.conftest import FakeObjectStorage, stream_of

pytestmark = pytest.mark.unit


@pytest.fixture
def limits() -> IngestionLimits:
    """Permissive limits; individual tests tighten the one they exercise."""
    return IngestionLimits()


class TestAcceptedFormats:
    """The formats the product promises to read."""

    async def test_reports_the_measured_shape_of_a_csv(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        result = await ingest_upload(
            filename="january_orders.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        # The sample dataset is 5 rows by 4 columns. These are counts taken
        # from the parsed frame, not estimates.
        assert result.rows == 5
        assert result.columns == 4
        assert result.filename == "january_orders.csv"
        assert result.file_size == len(csv_bytes)

    async def test_excludes_the_header_from_the_row_count(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        """A header counted as data would inflate every downstream total."""
        payload = b"region,units\nnorth,10\nsouth,20\n"

        result = await ingest_upload(
            filename="tiny.csv",
            chunks=stream_of(payload),
            storage=fake_storage,
            limits=limits,
        )

        assert result.rows == 2
        assert result.columns == 2

    async def test_reads_an_xlsx_workbook(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        xlsx_bytes: bytes,
    ) -> None:
        result = await ingest_upload(
            filename="orders.xlsx",
            chunks=stream_of(xlsx_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert result.rows == 5
        assert result.columns == 4

    async def test_reads_a_tab_separated_file(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        tsv_bytes: bytes,
    ) -> None:
        """.tsv must not be parsed with a comma separator.

        Doing so yields a single-column frame and a silently useless dataset
        rather than an error, which is the worst available failure mode.
        """
        result = await ingest_upload(
            filename="orders.tsv",
            chunks=stream_of(tsv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert result.rows == 5
        assert result.columns == 4

    async def test_accepts_a_header_only_file(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        """Zero rows is a real answer, not an error.

        The user learns their export was empty. Rejecting it would leave them
        guessing whether the upload or the export was at fault.
        """
        result = await ingest_upload(
            filename="empty_export.csv",
            chunks=stream_of(b"region,units\n"),
            storage=fake_storage,
            limits=limits,
        )

        assert result.rows == 0
        assert result.columns == 2


class TestExtensionValidation:
    async def test_rejects_an_unsupported_extension(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        with pytest.raises(UnsupportedFileTypeError) as caught:
            await ingest_upload(
                filename="quarterly_report.pdf",
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=limits,
            )

        assert caught.value.status_code == 415
        assert caught.value.code == "unsupported_file_type"
        # The client is told what *would* be accepted; an error that only says
        # "no" makes the user guess.
        assert ".csv" in caught.value.details["allowed_extensions"]

    async def test_rejects_a_file_with_no_extension(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        with pytest.raises(UnsupportedFileTypeError):
            await ingest_upload(
                filename="orders",
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=limits,
            )

    async def test_accepts_an_uppercase_extension(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """ORDERS.CSV is a CSV. Windows exports produce these routinely."""
        result = await ingest_upload(
            filename="ORDERS.CSV",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert result.rows == 5

    async def test_does_not_store_a_rejected_file_type(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """The extension check must happen before any byte is written."""
        with pytest.raises(UnsupportedFileTypeError):
            await ingest_upload(
                filename="malware.exe",
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=limits,
            )

        assert fake_storage.objects == {}

    async def test_honours_a_narrowed_allowlist(
        self,
        fake_storage: FakeObjectStorage,
        csv_bytes: bytes,
    ) -> None:
        """Configuration can narrow the accepted set."""
        csv_only = IngestionLimits(allowed_extensions=(".csv",))

        with pytest.raises(UnsupportedFileTypeError):
            await ingest_upload(
                filename="orders.xlsx",
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=csv_only,
            )

    async def test_cannot_be_widened_past_the_available_readers(
        self,
        fake_storage: FakeObjectStorage,
        csv_bytes: bytes,
    ) -> None:
        """Configuration must not admit a format with no reader behind it.

        Otherwise a typo in an environment variable becomes a 500 on the first
        upload instead of a 415.
        """
        over_permissive = IngestionLimits(allowed_extensions=(".csv", ".json"))

        with pytest.raises(UnsupportedFileTypeError):
            await ingest_upload(
                filename="orders.json",
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=over_permissive,
            )


class TestFilenameSafety:
    async def test_strips_directory_components_from_the_stored_name(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """A traversal attempt must not reach the storage key.

        The filename is fully client-controlled. Used as a path, this upload
        would write outside the storage root.
        """
        result = await ingest_upload(
            filename="../../../etc/cron.d/orders.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert result.filename == "orders.csv"
        stored_key = next(iter(fake_storage.objects))
        assert ".." not in stored_key
        assert stored_key == f"datasets/{result.dataset_id}/orders.csv"

    async def test_strips_a_windows_path(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """POSIX parsing alone would treat this whole string as one filename."""
        result = await ingest_upload(
            filename=r"C:\Users\ops\Desktop\sales.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert result.filename == "sales.csv"

    async def test_rejects_a_missing_filename(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        with pytest.raises(DatasetError):
            await ingest_upload(
                filename=None,
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=limits,
            )

    async def test_rejects_an_over_long_filename(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """Truncating instead would let two uploads collide invisibly."""
        with pytest.raises(DatasetError):
            await ingest_upload(
                filename=f"{'a' * 300}.csv",
                chunks=stream_of(csv_bytes),
                storage=fake_storage,
                limits=limits,
            )

    async def test_isolates_two_uploads_of_the_same_name(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """Everyone's export is called orders.csv. They must not overwrite."""
        first = await ingest_upload(
            filename="orders.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )
        second = await ingest_upload(
            filename="orders.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert first.dataset_id != second.dataset_id
        assert len(fake_storage.objects) == 2


class TestSizeLimit:
    async def test_rejects_a_payload_over_the_byte_ceiling(
        self,
        fake_storage: FakeObjectStorage,
    ) -> None:
        tiny = IngestionLimits(max_upload_bytes=1024)
        oversized = b"region,units\n" + b"north,1\n" * 500

        with pytest.raises(PayloadTooLargeError) as caught:
            await ingest_upload(
                filename="big.csv",
                chunks=stream_of(oversized, chunk_size=128),
                storage=fake_storage,
                limits=tiny,
            )

        assert caught.value.status_code == 413
        assert caught.value.details["limit_bytes"] == 1024

    async def test_stops_reading_as_soon_as_the_ceiling_is_crossed(
        self,
        fake_storage: FakeObjectStorage,
    ) -> None:
        """The limit is enforced mid-stream, not after buffering.

        A client can understate Content-Length, so this is the check that
        actually protects the process. Counting how many chunks were pulled
        proves we stopped early rather than reading the whole body first.
        """
        tiny = IngestionLimits(max_upload_bytes=1024)
        chunks_read = 0

        async def counting_stream() -> AsyncIterator[bytes]:
            nonlocal chunks_read
            for _ in range(100):
                chunks_read += 1
                yield b"x" * 256

        with pytest.raises(PayloadTooLargeError):
            await ingest_upload(
                filename="big.csv",
                chunks=counting_stream(),
                storage=fake_storage,
                limits=tiny,
            )

        # 1024 bytes is four 256-byte chunks; the fifth crosses the line.
        assert chunks_read == 5

    async def test_leaves_no_object_behind_when_rejected_for_size(
        self,
        fake_storage: FakeObjectStorage,
    ) -> None:
        """A refused upload must not consume storage.

        Otherwise a client can fill the bucket with data no dataset id points
        at, and nothing will ever clean it up.
        """
        tiny = IngestionLimits(max_upload_bytes=1024)

        with pytest.raises(PayloadTooLargeError):
            await ingest_upload(
                filename="big.csv",
                chunks=stream_of(b"x" * 5000, chunk_size=128),
                storage=fake_storage,
                limits=tiny,
            )

        assert fake_storage.objects == {}
        assert fake_storage.deleted_keys

    async def test_accepts_a_payload_exactly_at_the_ceiling(
        self,
        fake_storage: FakeObjectStorage,
    ) -> None:
        """The limit is inclusive. An off-by-one here rejects valid uploads."""
        header = b"a\n"
        payload = header + b"1\n" * ((1024 - len(header)) // 2)
        at_limit = IngestionLimits(max_upload_bytes=len(payload))

        result = await ingest_upload(
            filename="exact.csv",
            chunks=stream_of(payload, chunk_size=64),
            storage=fake_storage,
            limits=at_limit,
        )

        assert result.file_size == len(payload)


class TestParseFailures:
    async def test_rejects_an_empty_upload(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        with pytest.raises(DatasetParseError):
            await ingest_upload(
                filename="nothing.csv",
                chunks=stream_of(b""),
                storage=fake_storage,
                limits=limits,
            )

        assert fake_storage.objects == {}

    async def test_rejects_bytes_that_are_not_a_workbook(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        """A .xlsx extension does not make the bytes a spreadsheet."""
        with pytest.raises(DatasetParseError) as caught:
            await ingest_upload(
                filename="not_really.xlsx",
                chunks=stream_of(b"this is plain text, not a workbook"),
                storage=fake_storage,
                limits=limits,
            )

        assert caught.value.status_code == 422

    async def test_a_parse_failure_reveals_no_internals(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        """The message reaches the user, so it must not leak paths or types."""
        with pytest.raises(DatasetParseError) as caught:
            await ingest_upload(
                filename="not_really.xlsx",
                chunks=stream_of(b"garbage"),
                storage=fake_storage,
                limits=limits,
            )

        message = caught.value.message
        assert "Traceback" not in message
        assert "/" not in message

    async def test_deletes_the_object_when_parsing_fails(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        """An unparseable file is not a dataset; its bytes are unreachable."""
        with pytest.raises(DatasetParseError):
            await ingest_upload(
                filename="not_really.xlsx",
                chunks=stream_of(b"garbage"),
                storage=fake_storage,
                limits=limits,
            )

        assert fake_storage.objects == {}
        assert fake_storage.deleted_keys


class TestShapeLimits:
    async def test_rejects_a_table_with_too_many_columns(
        self,
        fake_storage: FakeObjectStorage,
    ) -> None:
        narrow = IngestionLimits(max_columns=2)
        payload = b"a,b,c\n1,2,3\n"

        with pytest.raises(DatasetError) as caught:
            await ingest_upload(
                filename="wide.csv",
                chunks=stream_of(payload),
                storage=fake_storage,
                limits=narrow,
            )

        assert caught.value.details == {"columns": 3, "max_columns": 2}
        assert fake_storage.objects == {}

    async def test_rejects_a_table_with_too_many_rows(
        self,
        fake_storage: FakeObjectStorage,
    ) -> None:
        shallow = IngestionLimits(max_rows=2)
        payload = b"a\n1\n2\n3\n"

        with pytest.raises(DatasetError) as caught:
            await ingest_upload(
                filename="deep.csv",
                chunks=stream_of(payload),
                storage=fake_storage,
                limits=shallow,
            )

        assert caught.value.details == {"rows": 3, "max_rows": 2}


class TestStoredArtefact:
    async def test_stores_the_bytes_verbatim(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """The stored file must be byte-identical to what was uploaded.

        Re-analysis, audit, and re-download all depend on it, and a checksum
        recorded over modified bytes would be worse than none.
        """
        result = await ingest_upload(
            filename="orders.csv",
            chunks=stream_of(csv_bytes, chunk_size=16),
            storage=fake_storage,
            limits=limits,
        )

        key = f"datasets/{result.dataset_id}/orders.csv"
        assert fake_storage.objects[key] == csv_bytes

    async def test_records_the_format_content_type(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        result = await ingest_upload(
            filename="orders.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        key = f"datasets/{result.dataset_id}/orders.csv"
        assert fake_storage.content_types[key] == "text/csv"

    async def test_issues_a_uuid_as_the_dataset_id(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        csv_bytes: bytes,
    ) -> None:
        """Unguessable by construction, so ids cannot be enumerated."""
        result = await ingest_upload(
            filename="orders.csv",
            chunks=stream_of(csv_bytes),
            storage=fake_storage,
            limits=limits,
        )

        assert uuid.UUID(result.dataset_id).version == 4

    async def test_reported_size_matches_the_stored_bytes(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        xlsx_bytes: bytes,
    ) -> None:
        """file_size is counted while writing, not taken from a header."""
        result = await ingest_upload(
            filename="orders.xlsx",
            chunks=stream_of(xlsx_bytes, chunk_size=512),
            storage=fake_storage,
            limits=limits,
        )

        key = f"datasets/{result.dataset_id}/orders.xlsx"
        assert result.file_size == len(fake_storage.objects[key]) == len(xlsx_bytes)


class TestNumbersAreMeasured:
    """The product rule: no reported figure is ever generated or estimated."""

    @pytest.mark.parametrize("row_count", [1, 7, 250])
    async def test_row_count_tracks_the_actual_file(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
        row_count: int,
    ) -> None:
        frame = pd.DataFrame({"units": range(row_count), "region": ["north"] * row_count})
        payload = frame.to_csv(index=False).encode()

        result = await ingest_upload(
            filename="generated.csv",
            chunks=stream_of(payload),
            storage=fake_storage,
            limits=limits,
        )

        assert result.rows == row_count
        assert result.columns == 2

    async def test_column_count_tracks_the_actual_workbook(
        self,
        fake_storage: FakeObjectStorage,
        limits: IngestionLimits,
    ) -> None:
        frame = pd.DataFrame({f"col_{index}": [index] for index in range(13)})
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False, engine="openpyxl")

        result = await ingest_upload(
            filename="wide.xlsx",
            chunks=stream_of(buffer.getvalue()),
            storage=fake_storage,
            limits=limits,
        )

        assert result.columns == 13
        assert result.rows == 1
