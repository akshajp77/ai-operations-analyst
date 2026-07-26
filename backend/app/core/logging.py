"""Structured logging.

Logs are machine-readable events, not prose. In production every line is a
single JSON object so a log aggregator can index, filter, and alert on
individual fields without regex archaeology. Locally we render the same
events as coloured text, because humans are the consumer there.

Two rules for the whole codebase:

1. Never use ``print()``. Ruff's ``T20`` rule enforces this.
2. Pass data as keyword arguments, not f-strings. Write
   ``log.info("dataset.ingested", rows=n)`` rather than
   ``log.info(f"ingested {n} rows")`` — the former is queryable, the latter
   is a string you have to parse later.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import Settings
from app.core.correlation import request_id_var


def _add_request_id(_logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
    """Attach the ambient request id to every event.

    This is what makes a production log searchable: one identifier ties the
    HTTP access log, every service-layer event, the SQL warning, and the
    OpenAI call latency together into a single traceable story — without any
    of those call sites having to thread an id through their signatures.
    """
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def _drop_color_message_key(_logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
    """Remove uvicorn's duplicated, ANSI-coloured copy of the message."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Install the logging pipeline. Call exactly once, at startup.

    Also redirects the standard library's ``logging`` module (which uvicorn,
    SQLAlchemy, and httpx all use) through the same processors, so third-party
    output lands in the same format as ours instead of interleaving two
    incompatible log styles.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_request_id,
        _drop_color_message_key,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # Hands the event off to the stdlib formatter configured below,
            # so we have exactly one rendering path for all log sources.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # `foreign_pre_chain` runs for records that came from stdlib logging
        # rather than from structlog, normalising them into the same shape.
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # uvicorn installs its own handlers; clear them so records propagate to
    # our root handler instead of being emitted twice in a different format.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # SQLAlchemy's INFO level echoes every statement, including bound
    # parameters. Keep it at WARNING unless explicitly enabled.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database.echo_sql else logging.WARNING
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger.

    Standard usage at the top of a module::

        log = get_logger(__name__)

    The return type is ``Any`` because structlog's ``BoundLogger`` gains
    methods dynamically; annotating it more tightly produces false positives
    in strict mypy without adding real safety.
    """
    return structlog.stdlib.get_logger(name)
