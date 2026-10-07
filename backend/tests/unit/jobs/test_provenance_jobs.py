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
from bridge.engagements import message_notify, notify
from bridge.jobs import audit as audit_jobs
from bridge.jobs import embeddings as embedding_jobs
from bridge.jobs import events as event_jobs
from bridge.jobs import expiry as expiry_jobs
from bridge.jobs import message_uploads as upload_jobs
from bridge.jobs import provenance as jobs
from bridge.jobs import quiz as quiz_jobs
from bridge.jobs import reminders as reminder_jobs
from bridge.jobs import saved_searches as saved_search_jobs
from bridge.jobs import trends as trend_jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.matching.tasks import SCAN_TASK as SCOUT_SCAN_TASK
from bridge.problems.research.tasks import RUN_TASK as RESEARCH_RUN_TASK
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
    assert IMPORT_PATHS == [
        "bridge.jobs.provenance",
        "bridge.jobs.audit",
        "bridge.jobs.notifications",
        "bridge.jobs.reminders",
        "bridge.jobs.scouts",
        "bridge.jobs.research",  # P11: one research.run job per research run (REQ-RES-01)
        "bridge.jobs.expiry",  # P19: the tracker's clock, expiry and the end of holds (REQ-ENG-10)
        "bridge.jobs.saved_searches",  # P21: the daily saved-search alerts (REQ-PERS-03)
        "bridge.jobs.message_uploads",  # P21: the hourly purge of unsendable thread uploads (REQ-ENG-11)
        "bridge.jobs.quiz",  # P22: the nightly draft of Today's five (REQ-DEV-01)
        "bridge.jobs.events",  # P22: This week's reminders, N26 and N27 (REQ-DEV-02)
        "bridge.jobs.trends",  # P22: the weekly technology trends draft (REQ-DEV-02)
        "bridge.jobs.embeddings",  # P23: profile and problem embeddings for the ranker's f1 (REQ-PERS-02)
    ]
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    for name in (
        service.TASK_HASH,
        service.TASK_SIGN,
        service.TASK_TIMESTAMP,
        jobs.ANCHOR_TASK,
        audit_jobs.VERIFY_TASK,
        notify.TASK,  # REQ-NOT-04: the tracker's notifications (P5)
        message_notify.TASK,  # REQ-ENG-11: N18, a new message in the thread (P21)
        RESEARCH_RUN_TASK,  # REQ-RES-01 (P11)
    ):
        assert name in app.tasks
    assert app.tasks[service.TASK_HASH].queue == service.QUEUE
    crons = {task.task.name: task.cron for task in app.periodic_registry.periodic_tasks.values()}
    assert crons == {
        jobs.ANCHOR_TASK: "7 * * * *",
        audit_jobs.VERIFY_TASK: "30 21 * * *",
        reminder_jobs.DISPATCH_TASK: "*/15 * * * *",
        reminder_jobs.ORG_DIGEST_TASK: "*/15 * * * *",
        SCOUT_SCAN_TASK: "*/15 * * * *",
        expiry_jobs.TASK: "*/15 * * * *",
        saved_search_jobs.TASK: "5 4 * * *",  # P21: 07:05 in Nairobi
        upload_jobs.TASK: "17 * * * *",
        quiz_jobs.TASK: "30 23 * * *",  # P22: 02:30 in Nairobi
        event_jobs.TASK: "*/15 * * * *",  # P22: N26 at 18:00 the day before, N27 at 08:00 the day of (Nairobi)
        trend_jobs.TASK: "15 2 * * 1",  # P22: Mondays 05:15 in Nairobi
        embedding_jobs.TASK: "*/15 * * * *",  # P23: the stale profiles and problems
    }


def test_hourly_anchor_runs_never_overlap() -> None:
    """One anchor run at a time: every job of the hourly task (the periodic deferrer uses the task's defaults) holds
    the Procrastinate lock ``provenance:anchors``, so a run that outlives the hour holds the next one back."""
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.ANCHOR_TASK]
    assert task.lock == jobs.ANCHOR_LOCK == "provenance:anchors"
    assert task.configure(task_kwargs={"timestamp": 0}).job.lock == "provenance:anchors"


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
        # retry_at is "now + delay" when the decision is made: whole seconds, so two capped delays compare equal
        delays.append(round((decision.retry_at - datetime.now(UTC)).total_seconds()))
    assert delays == [min(retry.cap, retry.base * 2**n) for n in range(retry.max_attempts)]
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
