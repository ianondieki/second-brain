"""Orchestrator re-check #29 (P5 decision 8): a decline's written reason travels in the notification job's arguments
(``reason_text``) until only an id is passed; it must never reach a log line. Procrastinate logs a job's arguments
twice, in the message (``call_string``) and in the record's ``job`` extra (``task_kwargs``, ``call_string``):
``bridge.logging.install_job_log_redaction`` redacts both on its loggers, the worker's own included.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from bridge import logging as bridge_logging

SECRET = "We are merging this unit into the group IT team."
KWARGS: dict[str, Any] = {"engagement_id": "e-1", "event_id": "v-1", "developer_id": "d-1", "reason_text": SECRET}
CALL = "engagements.notify[42](" + ", ".join(f"{k}={v!r}" for k, v in KWARGS.items()) + ")"


def job_extra() -> dict[str, Any]:
    return {"id": 42, "task_name": "engagements.notify", "task_kwargs": dict(KWARGS), "call_string": CALL}


@pytest.mark.parametrize("logger_name", ["procrastinate.worker.worker", "procrastinate.periodic", "procrastinate.jobs"])
def test_procrastinate_records_never_carry_a_redacted_argument(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    bridge_logging.install_job_log_redaction()
    bridge_logging.install_job_log_redaction()  # idempotent
    logger = logging.getLogger(logger_name)
    assert sum(isinstance(f, bridge_logging.RedactJobArguments) for f in logger.filters) == 1
    with caplog.at_level(logging.DEBUG, logger="procrastinate"):
        logger.info(f"Starting job {CALL}", extra={"action": "start_job", "job": job_extra()})
        logger.debug(f"Job {CALL} ended with status: Success")  # a message without the job extra
    assert SECRET not in caplog.text
    started, ended = caplog.records
    job = started.job  # type: ignore[attr-defined]
    assert SECRET not in repr(job)
    assert job["task_kwargs"] == {**KWARGS, "reason_text": "[redacted]"}
    assert job["call_string"] in started.getMessage()
    assert "engagement_id='e-1'" in started.getMessage()
    assert "reason_text='[redacted]'" in ended.getMessage()


def test_a_named_worker_and_the_root_handlers_are_covered(caplog: pytest.LogCaptureFixture) -> None:
    handler = logging.StreamHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        bridge_logging.install_job_log_redaction(worker_name="w-notify")
        assert any(isinstance(f, bridge_logging.RedactJobArguments) for f in handler.filters)
        logger = logging.getLogger("procrastinate.worker.w-notify")
        with caplog.at_level(logging.INFO, logger="procrastinate"):
            logger.info(f"Starting job {CALL}", extra={"job": job_extra()})
        assert SECRET not in caplog.text
    finally:
        root.removeHandler(handler)


def test_other_records_pass_unchanged() -> None:
    redact = bridge_logging.RedactJobArguments()
    plain = logging.LogRecord("procrastinate.worker", logging.INFO, __file__, 1, "Starting job x[1]()", None, None)
    assert redact.filter(plain)
    assert plain.getMessage() == "Starting job x[1]()"
    other = logging.LogRecord("procrastinate.worker", logging.INFO, __file__, 1, "m", None, None)
    other.job = {"task_kwargs": {"engagement_id": "e"}, "call_string": "t[1](engagement_id='e')"}
    assert redact.filter(other)
    assert other.job["task_kwargs"] == {"engagement_id": "e"}  # type: ignore[attr-defined]
    quoted = logging.LogRecord(
        "procrastinate.worker", logging.INFO, __file__, 1, 'Job t[1](reason_text="it\'s \\"x\\"") ended', None, None
    )
    assert redact.filter(quoted)
    assert quoted.getMessage() == "Job t[1](reason_text='[redacted]') ended"
