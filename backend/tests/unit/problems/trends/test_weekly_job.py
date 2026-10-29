"""REQ-DEV-02 (D-60; P22 card B, default (5)): the weekly job ``trends.draft`` runs on Mondays at 02:15 UTC (05:15
in Nairobi), one run at a time, on the installed runtime, its own timestamp ignored and a manual run's admin passed
on; the runtime builds its parts once; the card JSON carries the confidence as a number."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest

from bridge.config import get_settings
from bridge.engagements.calendar import NAIROBI
from bridge.jobs import trends as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.problems.trends import fakes
from bridge.problems.trends.run import Accepted, draft_trends
from bridge.problems.trends.store import card_json
from tests.unit.problems.trends.test_run import WEEK, deps


def test_the_job_runs_on_mondays_at_0515_nairobi_one_run_at_a_time() -> None:
    assert "bridge.jobs.trends" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("trends.draft", "trends", "trends:draft")
    assert task.configure(task_kwargs={"timestamp": 0}).job.lock == "trends:draft"
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "15 2 * * 1"
    assert datetime(2026, 10, 5, 2, 15, tzinfo=UTC).astimezone(NAIROBI).strftime("%a %H:%M") == "Mon 05:15"
    sunday_night_utc = datetime(2026, 10, 11, 22, 0, tzinfo=UTC)  # Monday 01:00 in Nairobi
    assert jobs.monday_of(sunday_night_utc) == date(2026, 10, 12)


@pytest.mark.parametrize("user_id", [None, "01927f00-0000-7000-8000-000000000009"])
async def test_the_task_runs_a_pass_on_the_installed_runtime(
    monkeypatch: pytest.MonkeyPatch, user_id: str | None
) -> None:
    calls: list[Any] = []

    async def run(deps: jobs.WeeklyDeps, **kwargs: Any) -> None:
        calls.append((deps, kwargs))

    def client(db: Any) -> Any:
        raise AssertionError("not called by a stubbed pass")

    monkeypatch.setattr(jobs, "run_weekly", run)
    factory = object()
    jobs.use_runtime(jobs.TrendsRuntime(get_settings(), factory=factory, client=client))  # type: ignore[arg-type]
    try:
        await jobs.draft(timestamp=0, user_id=user_id)
    finally:
        jobs.use_runtime(None)
    [(found, kwargs)] = calls
    assert (found.factory, found.llm) == (factory, client)
    assert kwargs == {"user_id": None if user_id is None else UUID(user_id)}
    assert isinstance(jobs.runtime(), jobs.TrendsRuntime)
    assert jobs.runtime() is jobs.runtime()
    jobs.use_runtime(None)


async def test_the_runtime_builds_its_parts_once_and_a_client_per_session() -> None:
    runtime = jobs.TrendsRuntime(get_settings())
    built = runtime.deps()
    assert runtime.deps().factory is built.factory
    async with built.factory() as db:
        assert built.llm(db) is not None
    await runtime.aclose()


async def test_the_card_json_carries_the_confidence_as_a_number() -> None:
    outcome = await draft_trends(deps(fakes.FakeTrendsClient("valid")), WEEK)
    assert isinstance(outcome, Accepted)
    card = json.loads(card_json(outcome.cards[0]))
    assert card["confidence"] == 0.833
    assert card["named_orgs"] == ["GitHub"]
