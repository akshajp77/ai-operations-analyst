"""Configuration validation.

These tests exist because configuration bugs are silent and expensive: the
service boots, serves traffic, and is quietly insecure. Asserting the
fail-fast behaviour turns "we assume nobody deploys with the default secret"
into a check that runs on every commit.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import DatabaseSettings, Environment, Settings, StorageSettings

pytestmark = pytest.mark.unit


class TestEnvironment:
    def test_local_and_test_are_not_deployed(self) -> None:
        assert not Environment.LOCAL.is_deployed
        assert not Environment.TEST.is_deployed

    def test_staging_and_production_are_deployed(self) -> None:
        assert Environment.STAGING.is_deployed
        assert Environment.PRODUCTION.is_deployed


class TestDatabaseSettings:
    def test_rejects_synchronous_driver(self) -> None:
        """A sync DSN would deadlock the event loop, so it must fail at boot."""
        with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
            DatabaseSettings(url="postgresql://user:pw@localhost:5432/db")

    def test_derives_sync_url_for_alembic(self) -> None:
        settings = DatabaseSettings(url="postgresql+asyncpg://user:pw@localhost:5432/db")
        assert settings.sync_url.startswith("postgresql+psycopg://")

    def test_rejects_out_of_range_pool_size(self) -> None:
        with pytest.raises(ValidationError):
            DatabaseSettings(pool_size=0)


class TestStorageSettings:
    def test_s3_backend_requires_a_bucket(self) -> None:
        with pytest.raises(ValidationError, match="STORAGE_S3_BUCKET"):
            StorageSettings(backend="s3")

    def test_local_backend_needs_no_bucket(self) -> None:
        assert StorageSettings(backend="local").s3_bucket is None


class TestProductionHardening:
    """The checks that stop a misconfigured deploy from reaching customers."""

    def test_placeholder_secret_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(
                environment=Environment.PRODUCTION,
                openai={"api_key": "sk-test"},
            )

    def test_missing_openai_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
            Settings(
                environment=Environment.PRODUCTION,
                secret_key="a-real-generated-secret",
            )

    def test_wildcard_cors_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="CORS_ORIGINS"):
            Settings(
                environment=Environment.PRODUCTION,
                secret_key="a-real-generated-secret",
                openai={"api_key": "sk-test"},
                cors_origins=("*",),
            )

    def test_debug_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DEBUG"):
            Settings(environment=Environment.PRODUCTION, debug=True)

    def test_valid_production_configuration_is_accepted(self) -> None:
        settings = Settings(
            environment=Environment.PRODUCTION,
            secret_key="a-real-generated-secret",
            openai={"api_key": "sk-test"},
            cors_origins=("https://app.example.com",),
        )
        assert settings.environment is Environment.PRODUCTION

    def test_local_environment_tolerates_defaults(self) -> None:
        """Development must stay frictionless; the gate is deployment-only."""
        assert Settings(environment=Environment.LOCAL).environment is Environment.LOCAL


class TestSecretHandling:
    def test_secrets_are_masked_in_repr(self) -> None:
        """An accidental log line or traceback must not print the key."""
        settings = Settings(openai={"api_key": "sk-super-secret-value"})
        assert "sk-super-secret-value" not in repr(settings)
        assert settings.openai.api_key.get_secret_value() == "sk-super-secret-value"


class TestCorsParsing:
    def test_accepts_comma_separated_string(self) -> None:
        """Docker Compose and most secret managers only supply plain strings."""
        settings = Settings(cors_origins="http://a.test, http://b.test")
        assert settings.cors_origins == ("http://a.test", "http://b.test")

    def test_ignores_empty_segments(self) -> None:
        settings = Settings(cors_origins="http://a.test,,")
        assert settings.cors_origins == ("http://a.test",)
