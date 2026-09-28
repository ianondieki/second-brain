"""REQ-PROV-01 / REQ-AUD-01: the provenance and audit tasks are registered with the names the pipeline queues, retry
with capped backoff (never after a permanent error), run on schedule, and build their runtime from settings, failing
closed where a setting is missing."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest
from procrastinate.jobs import Job
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from bridge.audit.chain import ChainProblem
from bridge.config import ConfigurationError, Settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.jobs import audit as audit_jobs
from bridge.jobs import provenance as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.provenance import service
from bridge.provenance.service import RegistrationError, RegistrationPendingError
from bridge.provenance.signing import LocalSigner
from bridge.provenance.transparency import ChainVerificationError
from bridge.storage.objects import InMemoryObjectStore

KEY = base64.b64encode(bytes(range(32))).decode()


def job(attempts: int) -> Job:
    return Job(id=1, queue="provenance", lock=None, queueing_lock=None, task_name="t", attempts=attempts)


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://bridge_app:x@127.0.0.1:1/none"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(KEY),
        "recovery_code_pepper": SecretStr("p" * 32),
        "tier2_local_kek": SecretStr(KEY),
        "provenance_signing_key": SecretStr(KEY),
        "object_store": "memory",
        "audit_reader_database_url": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_the_task_modules_are_imported_by_the_worker() -> None:
    assert IMPORT_PATHS == ["bridge.jobs.provenance", "bridge.jobs.audit"]
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    for name in (
        service.TASK_HASH,
        service.TASK_SIGN,
        service.TASK_TIMESTAMP,
        jobs.ANCHOR_TASK,
        audit_jobs.VERIFY_TASK,
    ):
        assert name in app.tasks
    assert app.tasks[service.TASK_HASH].queue == service.QUEUE
    crons = {task.task.name: task.cron for task in app.periodic_registry.periodic_tasks.values()}
    assert crons == {jobs.ANCHOR_TASK: "7 * * * *", audit_jobs.VERIFY_TASK: "30 21 * * *"}


def test_backoff_is_capped_and_stops_on_permanent_errors() -> None:
    backoff = jobs.Backoff(base=30, cap=3600, max_attempts=12)
    first = backoff.get_retry_decision(exception=RegistrationPendingError("later"), job=job(0))
    assert first is not None
    assert first.retry_at is not None
    later = backoff.get_retry_decision(exception=RuntimeError("db"), job=job(10))
    assert later is not None
    assert later.retry_at is not None
    assert (later.retry_at - datetime.now(UTC)).total_seconds() <= 3600 + 5
    assert backoff.get_retry_decision(exception=RegistrationError("never"), job=job(0)) is None
    assert backoff.get_retry_decision(exception=RuntimeError("db"), job=job(12)) is None
    assert jobs.TIMESTAMP_RETRY.max_attempts == 24 * 14


def test_the_nightly_verification_retries_transient_failures_and_never_a_broken_chain() -> None:
    """A dropped connection or a restarting database is retried with capped, growing delays a bounded number of
    times; a broken chain (or a missing setting) fails the job at once: no retry could publish a root."""
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    retry = audit_jobs.VERIFY_RETRY
    assert app.tasks[audit_jobs.VERIFY_TASK].retry_strategy is retry
    transient = OperationalError("SELECT 1", {}, ConnectionResetError("server closed the connection"))
    delays = []
    for attempts in range(retry.max_attempts):
        decision = retry.get_retry_decision(exception=transient, job=job(attempts))
        assert decision is not None
        assert decision.retry_at is not None
        delays.append((decision.retry_at - datetime.now(UTC)).total_seconds())
    assert delays == sorted(delays)
    assert delays[0] >= 30
    assert delays[-1] <= retry.cap + 5
    assert retry.get_retry_decision(exception=transient, job=job(retry.max_attempts)) is None
    assert retry.get_retry_decision(exception=TimeoutError(), job=job(0)) is not None
    broken = ChainVerificationError({"org:x": [ChainProblem(2, None, "event_hash does not match the row's contents")]})
    assert retry.get_retry_decision(exception=broken, job=job(0)) is None
    missing = ConfigurationError("audit.verify_chain needs AUDIT_READER_DATABASE_URL")
    assert retry.get_retry_decision(exception=missing, job=job(0)) is None


def test_the_nightly_run_closes_the_nairobi_day_that_ended() -> None:
    # 21:30 UTC on 28 September is 00:30 EAT on 29 September: the root is for 28 September.
    run = int(datetime(2026, 9, 28, 21, 30, tzinfo=UTC).timestamp())
    assert audit_jobs.closing_day(run) == date(2026, 9, 28)


def test_the_runtime_builds_each_part_from_settings_on_first_use() -> None:
    rt = jobs.ProvenanceRuntime(settings())
    assert isinstance(rt.wrapper, LocalKeyWrapper)
    assert rt.wrapper is rt.wrapper
    assert isinstance(rt.store, InMemoryObjectStore)
    assert isinstance(rt.signer, LocalSigner)
    assert rt.tsa.urls[0] == rt.settings.tsa_url
    assert rt.session_factory is rt.session_factory  # an engine is created, nothing connects yet
    with pytest.raises(ConfigurationError, match="AUDIT_READER_DATABASE_URL"):
        _ = rt.audit_engine
    with_reader = jobs.ProvenanceRuntime(
        settings(audit_reader_database_url=SecretStr("postgresql+psycopg://audit_reader:x@127.0.0.1:1/none"))
    )
    assert with_reader.audit_engine is with_reader.audit_engine


def test_missing_keys_fail_closed_at_use() -> None:
    rt = jobs.ProvenanceRuntime(settings(tier2_local_kek=None, provenance_signing_key=None))
    with pytest.raises(ConfigurationError, match="TIER2_LOCAL_KEK"):
        _ = rt.wrapper
    with pytest.raises(ConfigurationError, match="PROVENANCE_SIGNING_KEY"):
        _ = rt.signer


def test_the_default_runtime_reads_process_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs.use_runtime(None)
    monkeypatch.setattr(jobs, "get_settings", settings)
    rt = jobs.runtime()
    assert rt is jobs.runtime()
    assert rt.settings.object_store == "memory"
    jobs.use_runtime(None)
