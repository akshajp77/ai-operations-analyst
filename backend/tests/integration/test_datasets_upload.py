"""The HTTP contract of ``POST /api/v1/datasets/upload``.

The service tests already cover ingestion behaviour. What is verified here is
everything that only exists once a real request is involved: multipart
decoding, the status code each domain exception maps to, the error envelope
the frontend deserialises, and the OpenAPI document the TypeScript client is
generated from.

A regression in any of those breaks the client without breaking a single
service test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_database, get_object_storage
from app.core.config import Environment, IngestionLimits, Settings, StorageSettings
from app.main import create_app
from tests.conftest import FakeDatabase, FakeObjectStorage

pytestmark = pytest.mark.integration

UPLOAD_URL = "/api/v1/datasets/upload"


class TestSuccessfulUpload:
    async def test_returns_201_with_the_measured_shape(
        self, client: AsyncClient, csv_bytes: bytes
    ) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("january_orders.csv", csv_bytes, "text/csv")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["filename"] == "january_orders.csv"
        assert body["rows"] == 5
        assert body["columns"] == 4
        assert body["file_size"] == len(csv_bytes)
        assert body["dataset_id"]

    async def test_returns_exactly_the_documented_fields(
        self, client: AsyncClient, csv_bytes: bytes
    ) -> None:
        """The response shape is a contract the frontend is generated against.

        An extra field is silent schema drift; a missing one breaks the client
        at runtime.
        """
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("orders.csv", csv_bytes, "text/csv")},
        )

        assert set(response.json()) == {
            "dataset_id",
            "filename",
            "rows",
            "columns",
            "file_size",
        }

    async def test_accepts_an_excel_workbook(self, client: AsyncClient, xlsx_bytes: bytes) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={
                "file": (
                    "orders.xlsx",
                    xlsx_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        assert response.status_code == 201
        assert response.json()["rows"] == 5

    async def test_persists_the_upload_to_storage(
        self,
        client: AsyncClient,
        fake_storage: FakeObjectStorage,
        csv_bytes: bytes,
    ) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("orders.csv", csv_bytes, "text/csv")},
        )

        dataset_id = response.json()["dataset_id"]
        assert fake_storage.objects[f"datasets/{dataset_id}/orders.csv"] == csv_bytes

    async def test_trusts_the_extension_over_the_declared_content_type(
        self, client: AsyncClient, csv_bytes: bytes
    ) -> None:
        """Browsers send wildly inconsistent MIME types for CSV.

        A user whose OS reports ``application/octet-stream`` for a perfectly
        good spreadsheet must not be turned away.
        """
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("orders.csv", csv_bytes, "application/octet-stream")},
        )

        assert response.status_code == 201


class TestRejections:
    async def test_returns_415_for_an_unsupported_extension(
        self, client: AsyncClient, csv_bytes: bytes
    ) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("report.pdf", csv_bytes, "application/pdf")},
        )

        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_file_type"

    async def test_returns_422_for_an_empty_file(self, client: AsyncClient) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("empty.csv", b"", "text/csv")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "dataset_parse_failed"

    async def test_returns_422_for_bytes_that_are_not_a_workbook(self, client: AsyncClient) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("fake.xlsx", b"definitely not a workbook", "application/vnd.ms-excel")},
        )

        assert response.status_code == 422

    async def test_returns_422_when_no_file_part_is_present(self, client: AsyncClient) -> None:
        """A malformed request must use the same envelope as everything else."""
        response = await client.post(UPLOAD_URL)

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_failed"
        assert error["details"]["fields"]

    async def test_every_rejection_uses_the_standard_error_envelope(
        self, client: AsyncClient, csv_bytes: bytes
    ) -> None:
        response = await client.post(
            UPLOAD_URL,
            files={"file": ("report.pdf", csv_bytes, "application/pdf")},
        )

        error = response.json()["error"]
        assert set(error) == {"code", "message", "details", "request_id"}
        # The correlation id is what turns a user's screenshot into a log query.
        assert error["request_id"]

    async def test_stores_nothing_when_the_upload_is_rejected(
        self,
        client: AsyncClient,
        fake_storage: FakeObjectStorage,
        csv_bytes: bytes,
    ) -> None:
        await client.post(
            UPLOAD_URL,
            files={"file": ("report.pdf", csv_bytes, "application/pdf")},
        )

        assert fake_storage.objects == {}


class TestSizeCeiling:
    """The 413 path, driven end to end against a deliberately tiny limit."""

    @pytest.fixture
    async def small_limit_client(
        self,
        tmp_path_factory: pytest.TempPathFactory,
        fake_database: FakeDatabase,
        fake_storage: FakeObjectStorage,
    ) -> AsyncIterator[AsyncClient]:
        """An app that refuses anything over 1 KiB.

        A purpose-built app rather than the shared one: asserting the real
        ceiling would mean POSTing 200 MiB, and lowering the shared limit would
        change what every other test in this file exercises.
        """
        settings = Settings(
            environment=Environment.TEST,
            debug=True,
            log_level="WARNING",
            log_format="console",
            storage=StorageSettings(
                backend="local",
                local_path=str(tmp_path_factory.mktemp("small")),
            ),
            ingest=IngestionLimits(max_upload_bytes=1024),
        )
        app = create_app(settings)
        app.dependency_overrides[get_database] = lambda: fake_database
        app.dependency_overrides[get_object_storage] = lambda: fake_storage

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
        ):
            yield http_client

        app.dependency_overrides.clear()

    async def test_returns_413_for_an_oversized_upload(
        self, small_limit_client: AsyncClient
    ) -> None:
        oversized = b"region,units\n" + b"north,1\n" * 500

        response = await small_limit_client.post(
            UPLOAD_URL,
            files={"file": ("big.csv", oversized, "text/csv")},
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"

    async def test_accepts_an_upload_under_the_ceiling(
        self, small_limit_client: AsyncClient
    ) -> None:
        """The ceiling must not reject ordinary files."""
        response = await small_limit_client.post(
            UPLOAD_URL,
            files={"file": ("small.csv", b"region,units\nnorth,10\n", "text/csv")},
        )

        assert response.status_code == 201


class TestOpenAPIContract:
    async def test_the_endpoint_appears_in_the_schema(self, client: AsyncClient) -> None:
        """The frontend client is generated from this document.

        An endpoint absent here does not exist as far as the frontend is
        concerned, however well it works over curl.
        """
        document = (await client.get("/openapi.json")).json()

        operation = document["paths"]["/api/v1/datasets/upload"]["post"]
        assert operation["operationId"] == "datasets_upload_dataset"
        assert "multipart/form-data" in operation["requestBody"]["content"]

    async def test_error_responses_are_typed(self, client: AsyncClient) -> None:
        """Untyped error responses degrade the client's handling into casting."""
        document = (await client.get("/openapi.json")).json()

        responses = document["paths"]["/api/v1/datasets/upload"]["post"]["responses"]
        for status_code in ("413", "415", "422"):
            schema = responses[status_code]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("ErrorResponse")
