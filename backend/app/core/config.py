"""Application configuration.

Every tunable value in the system enters the process through this module and
nowhere else. Application code reads configuration via :func:`get_settings`;
it never touches ``os.environ`` directly. That single rule buys us three
things:

1. **Testability** — a test overrides one dependency instead of mutating
   global process state.
2. **Validation at boot** — a malformed or missing value fails the process at
   startup with a precise message, rather than at 3am inside a request.
3. **Auditability** — the full configuration surface of the service is one
   file you can read top to bottom.

Secrets are typed as :class:`~pydantic.SecretStr` so that an accidental
``repr()``, log line, or error payload prints ``**********`` instead of the
credential.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    PostgresDsn,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment.

    Behaviour differences between environments are decided by comparing
    against this enum, never by parsing a raw string at the call site.
    """

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_deployed(self) -> bool:
        """True for environments that serve real user data."""
        return self in {Environment.STAGING, Environment.PRODUCTION}


# A placeholder that must never survive into a deployed environment. The
# validator below turns "developer forgot to set SECRET_KEY" into a boot
# failure instead of a silent security hole.
_INSECURE_SECRET_PLACEHOLDER = "change-me-in-production"  # noqa: S105


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection and pool configuration.

    Pool sizing is configuration, not a constant, because the correct value
    differs by deployment shape: a single local container wants a small pool,
    while N replicas behind a connection pooler must keep
    ``N * (pool_size + max_overflow)`` under the server's ``max_connections``.
    """

    model_config = SettingsConfigDict(env_prefix="DATABASE_", extra="ignore")

    url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://postgres:postgres@localhost:5432/ai_ops_analyst"),
        description="Async SQLAlchemy DSN. Must use the postgresql+asyncpg driver.",
    )
    pool_size: Annotated[int, Field(ge=1, le=100)] = 10
    max_overflow: Annotated[int, Field(ge=0, le=100)] = 5
    pool_timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 30
    pool_recycle_seconds: Annotated[int, Field(ge=60)] = 1800
    echo_sql: bool = False

    @field_validator("url")
    @classmethod
    def _require_async_driver(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a sync DSN early.

        A ``postgresql://`` URL loads fine and then deadlocks the event loop on
        the first query. Catching it at boot is far cheaper than debugging it
        under load.
        """
        if value.scheme != "postgresql+asyncpg":
            raise ValueError(
                f"DATABASE_URL must use the 'postgresql+asyncpg' driver, got '{value.scheme}'. "
                "Alembic derives its own sync URL from this value."
            )
        return value

    @property
    def sync_url(self) -> str:
        """Synchronous DSN for Alembic, which does not run on the event loop."""
        return str(self.url).replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


class OpenAISettings(BaseSettings):
    """OpenAI Responses API configuration."""

    model_config = SettingsConfigDict(env_prefix="OPENAI_", extra="ignore")

    api_key: SecretStr = Field(default=SecretStr(""))
    model: str = Field(
        default="gpt-4.1",
        description="Default reasoning model for narrative generation.",
    )
    fast_model: str = Field(
        default="gpt-4.1-mini",
        description="Cheaper model for bounded, mechanical tasks such as column "
        "semantic labelling, where the large model is not worth its cost.",
    )
    timeout_seconds: Annotated[float, Field(gt=0, le=600)] = 120.0
    max_retries: Annotated[int, Field(ge=0, le=10)] = 3
    max_output_tokens: Annotated[int, Field(ge=256, le=100_000)] = 8_192


class StorageSettings(BaseSettings):
    """Where uploaded datasets and generated artefacts live.

    The backend is written against a storage *interface* (see
    ``app/storage``), so switching ``backend`` from ``local`` to ``s3`` is a
    configuration change, not a code change.
    """

    model_config = SettingsConfigDict(env_prefix="STORAGE_", extra="ignore")

    backend: Literal["local", "s3"] = "local"
    local_path: str = "./.data/uploads"
    s3_bucket: str | None = None
    s3_region: str | None = None
    signed_url_ttl_seconds: Annotated[int, Field(ge=60, le=86_400)] = 3_600

    @model_validator(mode="after")
    def _require_bucket_for_s3(self) -> Self:
        if self.backend == "s3" and not self.s3_bucket:
            raise ValueError("STORAGE_S3_BUCKET is required when STORAGE_BACKEND='s3'.")
        return self


class IngestionLimits(BaseSettings):
    """Hard ceilings on user-supplied input.

    These are the service's blast-radius controls. Without them a single
    50-column-by-10-million-row upload can exhaust memory for every tenant on
    the node, so they are explicit configuration rather than magic numbers
    buried in the parser.
    """

    model_config = SettingsConfigDict(env_prefix="INGEST_", extra="ignore")

    max_upload_bytes: Annotated[int, Field(ge=1024)] = 200 * 1024 * 1024  # 200 MiB
    max_rows: Annotated[int, Field(ge=1)] = 5_000_000
    max_columns: Annotated[int, Field(ge=1, le=10_000)] = 512
    allowed_extensions: tuple[str, ...] = (".csv", ".tsv", ".xlsx", ".xls", ".parquet")

    # How many rows the AI layer is allowed to see. The model reasons over
    # computed statistics, never the raw dataset — this is both a cost control
    # and a data-minimisation control.
    ai_sample_rows: Annotated[int, Field(ge=0, le=1_000)] = 50


class Settings(BaseSettings):
    """Root settings object. One instance per process, cached."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        # Environment variables are matched case-insensitively, so both
        # LOG_LEVEL and log_level resolve.
        case_sensitive=False,
    )

    # --- Identity ----------------------------------------------------------
    app_name: str = "AI Operations Analyst"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Security ----------------------------------------------------------
    secret_key: SecretStr = Field(default=SecretStr(_INSECURE_SECRET_PLACEHOLDER))
    access_token_ttl_minutes: Annotated[int, Field(ge=1)] = 60
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    # --- Observability -----------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- Composed sections -------------------------------------------------
    # `default_factory` lets each section read its own env-prefixed variables
    # (DATABASE_URL, OPENAI_API_KEY, ...) while still being addressable in code
    # as `settings.database.url`.
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingest: IngestionLimits = Field(default_factory=IngestionLimits)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept ``a,b,c`` from the environment as well as a JSON array.

        Docker Compose and most secret managers only hand us plain strings, so
        requiring JSON here would be a needless foot-gun.
        """
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @field_validator("debug")
    @classmethod
    def _forbid_debug_in_production(cls, value: bool, info: ValidationInfo) -> bool:
        environment = info.data.get("environment")
        if value and environment == Environment.PRODUCTION:
            raise ValueError("DEBUG must be false in production; it leaks stack traces to clients.")
        return value

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Self:
        """Refuse to boot a deployed environment with development defaults.

        Every check here represents an incident we would rather have at
        deploy time than at runtime.
        """
        if not self.environment.is_deployed:
            return self

        problems: list[str] = []

        if self.secret_key.get_secret_value() in ("", _INSECURE_SECRET_PLACEHOLDER):
            problems.append("SECRET_KEY must be set to a generated value.")
        if not self.openai.api_key.get_secret_value():
            problems.append("OPENAI_API_KEY must be set.")
        if any(origin == "*" for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must not be '*'; list explicit origins.")
        if self.database.echo_sql:
            problems.append("DATABASE_ECHO_SQL must be false; it logs query parameters.")

        if problems:
            raise ValueError(
                f"Invalid configuration for environment '{self.environment}':\n  - "
                + "\n  - ".join(problems)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that the ``.env`` file is parsed and validated exactly once.
    This function is the FastAPI dependency used throughout the API layer;
    tests override it via ``app.dependency_overrides`` rather than by
    monkey-patching the environment.
    """
    return Settings()
