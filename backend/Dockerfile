# syntax=docker/dockerfile:1.9
#
# Backend image — multi-stage.
#
# The build toolchain (gcc, headers) is needed to compile some wheels but is a
# liability at runtime: it is attack surface and hundreds of megabytes. Two
# stages let us compile in one and ship only the resulting virtualenv.

# ---------------------------------------------------------------------------
# Stage 1: build the virtualenv
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# Pinned to 3.12 deliberately. pandas, polars, duckdb, and pyarrow all publish
# prebuilt wheels for it; a newer interpreter can silently fall back to a
# source build that takes twenty minutes and may not compile at all.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the dependency manifest first. Docker caches this layer, so an
# application code change does not reinstall pandas — the difference between
# a 5-second rebuild and a 5-minute one.
COPY pyproject.toml README.md ./
# A minimal package stub so the project itself is installable before the real
# source is copied in.
RUN mkdir -p app && touch app/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel \
    && pip install .

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq5 is the runtime half of libpq-dev; psycopg needs it, the headers are
# only needed to compile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user. A container escape from root is a host
# compromise; from an unprivileged uid it is far less useful.
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --create-home appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser app ./app

USER appuser

EXPOSE 8000

# Container-level health, distinct from the orchestrator probe. Hits liveness
# only, so a database outage does not cause Docker to kill healthy processes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health/live || exit 1

# No --reload here. Development mounts source and overrides this command in
# docker-compose; the image itself must always be production-shaped.
#
# Worker count is left to the orchestrator: one uvicorn process per container,
# scaled by replica count, gives better isolation and simpler metrics than
# multiple workers inside one container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
