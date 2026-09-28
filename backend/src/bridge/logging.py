"""Structured JSON logging with structlog (docs/spec/08 Observability: no PII in logs)."""

from __future__ import annotations

import logging
import sys

import structlog

# Keys that must never reach a log line, whatever the caller passes.
REDACTED_KEYS = frozenset({"password", "token", "secret", "email", "code", "cookie", "authorization", "totp"})

# Paths whose query string never reaches the access log: the OAuth callback's carries the authorization code, the
# state and the provider's error text (REQ-AUTH-02). Structlog does not log requests; uvicorn's access log does.
QUERYLESS_PATHS = ("/api/auth/oauth/",)


class DropQueryStrings(logging.Filter):
    """Drops the query string from uvicorn access-log records for ``QUERYLESS_PATHS``. uvicorn logs
    ``'%s - "%s %s HTTP/%s" %d'`` with (client, method, path?query, HTTP version, status); records of any other
    shape pass unchanged."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path, separator, _query = args[2].partition("?")
            if separator and path.startswith(QUERYLESS_PATHS):
                record.args = (args[0], args[1], path, args[3], args[4])
        return True


def _redact(_: object, __: str, event_dict: structlog.types.EventDict) -> structlog.types.EventDict:
    for key in list(event_dict):
        if any(part in key.lower() for part in REDACTED_KEYS):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )
    access = logging.getLogger("uvicorn.access")  # uvicorn's dictConfig keeps logger filters, so the order is free
    if not any(isinstance(existing, DropQueryStrings) for existing in access.filters):
        access.addFilter(DropQueryStrings())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
