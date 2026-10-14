"""Structured logging.

Every log line is a set of key/value pairs (event, request_id, campaign_id, ...), so logs can
be filtered by any id later. Values bound with `structlog.contextvars.bind_contextvars` (like
the request id) are added to every line logged inside that request automatically.
"""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", json: bool = False) -> None:
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Libraries that use the standard logging module (uvicorn, sqlalchemy) go to stdout too.
    logging.basicConfig(
        level=log_level, stream=sys.stdout, format="%(levelname)s %(name)s %(message)s"
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
