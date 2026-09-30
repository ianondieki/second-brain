"""Structured JSON logging with structlog (docs/spec/08 Observability: no PII in logs)."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

import structlog

# Parts of a key whose value never reaches a log line, whatever the caller passes: secrets (passwords, tokens, keys,
# codes, sessions) and personal data (emails, phones, names, addresses, free text, URLs that may carry a token).
# P16-E1 added the personal-data parts; tests/unit/test_log_fields.py keeps every structlog call's fields reviewed.
REDACTED_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "email",
        "code",
        "cookie",
        "authorization",
        "totp",
        "otp",
        "recovery",
        "pepper",
        "session",
        "csrf",
        "credential",
        "api_key",
        "private_key",
        "phone",
        "msisdn",
        "name",
        "address",
        "text",
        "body",
        "url",
        "link",
    }
)

# Paths whose query string never reaches the access log: the OAuth callback's carries the authorization code, the
# state and the provider's error text (REQ-AUTH-02). Structlog does not log requests; uvicorn's access log does.
QUERYLESS_PATHS = ("/api/auth/oauth/",)
# Query parameters that carry what people type (search words, which can be a name or an address): their values are
# redacted on every path (P16-E1).
FREE_TEXT_PARAMETERS = ("q",)
_FREE_TEXT_VALUE = re.compile(r"(^|&)(" + "|".join(FREE_TEXT_PARAMETERS) + r")=[^&]*")


class DropQueryStrings(logging.Filter):
    """Drops the query string from uvicorn access-log records for ``QUERYLESS_PATHS``, and the values of
    ``FREE_TEXT_PARAMETERS`` from every other. uvicorn logs ``'%s - "%s %s HTTP/%s" %d'`` with (client, method,
    path?query, HTTP version, status); records of any other shape pass unchanged."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path, separator, query = args[2].partition("?")
            if separator and path.startswith(QUERYLESS_PATHS):
                record.args = (args[0], args[1], path, args[3], args[4])
            elif separator:
                redacted = _FREE_TEXT_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}={_REDACTED}", query)
                record.args = (args[0], args[1], f"{path}?{redacted}", args[3], args[4])
        return True


# Job arguments that carry free text and never reach a log line. A decline's written reason (``OTHER``) travels in the
# ``engagements.notify`` job's arguments until only an id is passed (P5 decision 8; orchestrator re-check #29).
REDACTED_JOB_ARGUMENTS = frozenset({"reason_text"})
# The loggers through which Procrastinate logs a job's arguments: the worker (``procrastinate.worker.<name>``, default
# name ``worker``), the periodic deferrer and the job manager. Logger filters do not reach child loggers, so each is
# named; the root handlers get the filter too, which covers a worker name chosen later.
PROCRASTINATE_LOGGERS = (
    "procrastinate",
    "procrastinate.worker",
    "procrastinate.jobs",
    "procrastinate.manager",
    "procrastinate.periodic",
)
_REDACTED = "[redacted]"
_ARGUMENT_REPR = re.compile(
    r"\b(" + "|".join(sorted(REDACTED_JOB_ARGUMENTS)) + r")=(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
)


def _call_string(job: dict[str, Any], kwargs: dict[str, Any]) -> str:
    """Procrastinate's ``Job.call_string`` for these arguments."""
    rendered = ", ".join(f"{key}={value!r}" for key, value in kwargs.items())
    return f"{job.get('task_name')}[{job.get('id')}]({rendered})"


class RedactJobArguments(logging.Filter):
    """Replaces ``REDACTED_JOB_ARGUMENTS`` in a Procrastinate record: in its ``job`` extra (``task_kwargs`` and
    ``call_string``) and in its message (the call string, or any ``name='value'`` left in a message without the
    extra). Other records pass unchanged."""

    def filter(self, record: logging.LogRecord) -> bool:
        job = getattr(record, "job", None)
        kwargs = job.get("task_kwargs") if isinstance(job, dict) else None
        if isinstance(job, dict) and isinstance(kwargs, dict) and REDACTED_JOB_ARGUMENTS & kwargs.keys():
            safe = {key: _REDACTED if key in REDACTED_JOB_ARGUMENTS else value for key, value in kwargs.items()}
            redacted_call = _call_string(job, safe)
            original = job.get("call_string")
            record.job = {**job, "task_kwargs": safe, "call_string": redacted_call}
            if isinstance(original, str) and isinstance(record.msg, str):
                record.msg = record.msg.replace(original, redacted_call)
        if isinstance(record.msg, str):
            record.msg = _ARGUMENT_REPR.sub(lambda match: f"{match.group(1)}='{_REDACTED}'", record.msg)
        return True


def install_job_log_redaction(worker_name: str | None = None) -> None:
    """Put ``RedactJobArguments`` on Procrastinate's loggers (the worker named ``worker_name``, the CLI's
    ``PROCRASTINATE_WORKER_NAME`` or the default) and on the root handlers. Idempotent. The worker calls it when it
    imports ``bridge.jobs.app`` (before the CLI configures its handlers, hence the named loggers); the API through
    ``configure_logging``."""
    name = worker_name or os.environ.get("PROCRASTINATE_WORKER_NAME") or "worker"
    targets: list[logging.Filterer] = [
        logging.getLogger(n) for n in (*PROCRASTINATE_LOGGERS, f"procrastinate.worker.{name}")
    ]
    targets += logging.getLogger().handlers
    for target in targets:
        if not any(isinstance(existing, RedactJobArguments) for existing in target.filters):
            target.addFilter(RedactJobArguments())


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
    install_job_log_redaction()
    access = logging.getLogger("uvicorn.access")  # uvicorn's dictConfig keeps logger filters, so the order is free
    if not any(isinstance(existing, DropQueryStrings) for existing in access.filters):
        access.addFilter(DropQueryStrings())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
