"""REQ-ENG-10 (part), AC-PROP-3: the tracker's clock job runs every 15 minutes, one run at a time, on the shared clock;
what it does to an engagement is decided by code (``expiry.due_action``) from the state machine's rules."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from bridge.engagements import expiry
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI, add_business_days
from bridge.engagements.models import EngagementEvent
from bridge.engagements.policy import get_policy
from bridge.jobs import expiry as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.models.enums import EngagementState

S = EngagementState
POLICY = get_policy()
MONDAY = date(2026, 10, 5)


def at(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=NAIROBI)


def entered(day: date, due_on: date | None) -> EngagementEvent:
    return EngagementEvent(created_at=at(day, 9), stage_deadline_at=sm.end_of_day(due_on) if due_on else None)


def test_the_task_runs_every_fifteen_minutes_one_run_at_a_time() -> None:
    assert "bridge.jobs.expiry" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("engagements.expire", "engagements", "engagements:expire")
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "*/15 * * * *"


async def test_the_task_runs_a_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def run(factory: object, **kwargs: Any) -> expiry.Report:
        calls.append((factory, kwargs))
        return expiry.Report(at(MONDAY))

    factory = object()
    monkeypatch.setattr(jobs, "run_expiry", run)
    jobs.use_runtime(jobs.ExpiryRuntime(session_factory=factory))  # type: ignore[arg-type]
    try:
        await jobs.expire(timestamp=0)
    finally:
        jobs.use_runtime(None)
    assert calls == [(factory, {})]  # the job's own timestamp is ignored: the shared clock decides
    assert isinstance(jobs.runtime(), jobs.ExpiryRuntime)
    jobs.use_runtime(None)


@pytest.mark.parametrize(
    ("state", "expire_bd"),
    [(S.ORG_INTEREST, 5), (S.SUBMITTED, 20), (S.UNDER_REVIEW, 30), (S.INTEREST_CONFIRMED, 10)],
)
def test_a_stage_expires_once_the_end_of_its_expire_day_has_passed(state: EngagementState, expire_bd: int) -> None:
    due_on = add_business_days(MONDAY, POLICY.stage(state).due_bd or 0, set())
    deadline = sm.end_of_day(due_on)
    last = add_business_days(MONDAY, expire_bd, set())
    event = entered(MONDAY, due_on)
    assert expiry.due_action(state, at(last, 23), deadline, event, set(), POLICY) is None
    assert expiry.due_action(state, sm.end_of_day(last), deadline, event, set(), POLICY) is None
    assert expiry.due_action(state, sm.end_of_day(last) + timedelta(seconds=1), deadline, event, set(), POLICY) == (
        "expire"
    )
    assert expiry.due_action(state, at(last + timedelta(days=1)), deadline, None, set(), POLICY) is None


def test_a_hold_resumes_on_its_resume_date_and_nothing_else_moves() -> None:
    resume_at = date(2026, 10, 15)
    deadline = sm.end_of_day(resume_at)
    assert expiry.due_action(S.ON_HOLD, at(resume_at - timedelta(days=1), 23), deadline, None, set(), POLICY) is None
    assert expiry.due_action(S.ON_HOLD, at(resume_at, 0), deadline, None, set(), POLICY) == "resume"
    assert expiry.due_action(S.ON_HOLD, at(resume_at + timedelta(days=3)), deadline, None, set(), POLICY) == "resume"
    assert expiry.due_action(S.ON_HOLD, at(resume_at), None, None, set(), POLICY) is None
    late = at(MONDAY + timedelta(days=300))
    for state in (S.INFO_REQUESTED, S.NEGOTIATION, S.EXPIRED, S.CLOSED):
        assert expiry.due_action(state, late, sm.end_of_day(MONDAY), entered(MONDAY, MONDAY), set(), POLICY) is None


def test_a_report_finds_an_engagements_outcome() -> None:
    engagement = UUID("01900000-0000-7000-8000-0000000000aa")
    report = expiry.Report(at(MONDAY), (expiry.Outcome(engagement, "expire", S.EXPIRED),))
    assert report.of(engagement) == expiry.Outcome(engagement, "expire", S.EXPIRED)
    assert report.of(UUID(int=0)) is None
