"""REQ-DEV-01 (D-59; P22 card A): the nightly job ``quiz.draft`` runs at 23:30 UTC (02:30 in Nairobi), one run at a
time, on the installed runtime, its own timestamp ignored; the runtime builds its parts once and an LLM client per
session."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from bridge.config import get_settings
from bridge.jobs import quiz as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.matching.trending import NAIROBI
from bridge.quiz.nightly import NightlyDeps
from bridge.quiz.policy import get_quiz_policy
from bridge.quiz.sources import get_sources


def test_the_job_runs_nightly_at_0230_nairobi_one_run_at_a_time() -> None:
    assert "bridge.jobs.quiz" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("quiz.draft", "quiz", "quiz:draft")
    assert task.configure(task_kwargs={"timestamp": 0}).job.lock == "quiz:draft"
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "30 23 * * *"
    assert datetime(2026, 10, 5, 23, 30, tzinfo=UTC).astimezone(NAIROBI).strftime("%a %H:%M") == "Tue 02:30"


async def test_the_task_runs_a_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def run(deps: NightlyDeps, **kwargs: Any) -> tuple[()]:
        calls.append((deps, kwargs))
        return ()

    def client(db: Any) -> Any:
        raise AssertionError("not called by a stubbed pass")

    monkeypatch.setattr(jobs, "run_nightly", run)
    factory = object()
    jobs.use_runtime(jobs.NightlyRuntime(get_settings(), factory=factory, client=client))  # type: ignore[arg-type]
    try:
        await jobs.draft(timestamp=0)
    finally:
        jobs.use_runtime(None)
    [(deps, kwargs)] = calls
    assert (deps.factory, deps.llm, kwargs) == (factory, client, {})  # the job's own timestamp is ignored
    assert (deps.sources, deps.policy) == (get_sources(), get_quiz_policy())
    assert isinstance(jobs.runtime(), jobs.NightlyRuntime)
    assert jobs.runtime() is jobs.runtime()
    jobs.use_runtime(None)


async def test_the_runtime_builds_its_parts_once_and_a_client_per_session() -> None:
    runtime = jobs.NightlyRuntime(get_settings())
    deps = runtime.deps()
    again = runtime.deps()
    assert again.factory is deps.factory
    async with deps.factory() as db:
        assert deps.llm(db) is not None  # a routed client over this unbound session (the fake provider in test)
    await runtime.aclose()
