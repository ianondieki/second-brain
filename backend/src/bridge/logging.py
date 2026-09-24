"""Structured JSON logging with structlog (docs/spec/08 Observability: no PII in logs)."""

from __future__ import annotations

import logging
import sys

import structlog

# Keys that must never reach a log line, whatever the caller passes.
REDACTED_KEYS = frozenset({"password", "token", "secret", "email", "code", "cookie", "authorization", "totp"})


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


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
