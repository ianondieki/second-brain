"""REQ-REM-01, REQ-REM-02: the periodic jobs (every 15 minutes, one run at a time, on the installed runtime) and the
dev/test trigger ``python -m bridge.reminders run [--now]`` (refused with ``--now`` in production)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

import bridge.reminders.__main__ as cli
from bridge.config import get_settings
from bridge.jobs import reminders as jobs
from bridge.jobs.app import app
from bridge.models.enums import DeliveryStatus
from bridge.notifications.email import FakeEmailProvider
from bridge.reminders.dispatch import Deps, Outcome, ReminderRuntime, Report

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
USER, ORG = uuid4(), uuid4()


def test_the_tasks_run_every_fifteen_minutes_one_run_at_a_time() -> None:
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    for name, lock in ((jobs.DISPATCH_TASK, "reminders:dispatch"), (jobs.ORG_DIGEST_TASK, "reminders:org_digest")):
        task = app.tasks[name]
        assert (task.queue, task.lock) == ("reminders", lock)
        assert task.configure(task_kwargs={"timestamp": 0}).job.lock == lock
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.DISPATCH_TASK] == crons[jobs.ORG_DIGEST_TASK] == "*/15 * * * *"


class StubRuntime(ReminderRuntime):
    def __init__(self) -> None:
        super().__init__(get_settings())
        self.closed = 0
        self.built = Deps(factory=None, settings=get_settings(), email=FakeEmailProvider())  # type: ignore[arg-type]

    def deps(self) -> Deps:
        return self.built

    async def aclose(self) -> None:
        self.closed += 1


async def test_the_tasks_run_their_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, calls = StubRuntime(), []

    async def record(deps: Deps, **kwargs: Any) -> Report:
        calls.append((deps, kwargs))
        return Report(NOW, date(2026, 10, 5), True)

    monkeypatch.setattr(jobs, "run_developer_nudges", record)
    monkeypatch.setattr(jobs, "run_org_digests", record)
    jobs.use_runtime(runtime)
    try:
        await jobs.dispatch(timestamp=0)
        await jobs.org_digest(timestamp=0)
        assert calls == [(runtime.built, {}), (runtime.built, {})]  # the job's timestamp is ignored: the clock decides
    finally:
        jobs.use_runtime(None)
    assert isinstance(jobs.runtime(), ReminderRuntime)
    assert jobs.runtime() is jobs.runtime()
    jobs.use_runtime(None)


async def test_the_runtime_builds_its_parts_from_settings_once() -> None:
    runtime = ReminderRuntime(get_settings().model_copy(update={"email_provider": "fake"}))
    deps = runtime.deps()
    assert isinstance(deps.email, FakeEmailProvider)
    assert deps.llm is not None
    assert deps.llm.provider == "fake"  # APP_ENV=test
    again = runtime.deps()
    assert (again.factory, again.email, again.llm) == (deps.factory, deps.email, deps.llm)
    await runtime.aclose()


def reports(ran: bool) -> dict[str, Report]:
    outcomes = (
        Outcome(USER, "sent", email=DeliveryStatus.SENT),
        Outcome(USER, "already", org_id=ORG, email=None, email_skipped="no_consent"),
    )
    return {
        "developers": Report(NOW, date(2026, 10, 5), ran, outcomes[:1] if ran else ()),
        "organisations": Report(NOW, date(2026, 10, 5), ran, outcomes[1:] if ran else ()),
    }


@pytest.mark.parametrize("ran", [True, False])
def test_run_prints_one_line_per_recipient(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], ran: bool
) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []
    made = reports(ran)

    def fake(name: str) -> Any:
        async def run(deps: Deps, **kwargs: Any) -> Report:
            seen.append((name, kwargs))
            return made[name]

        return run

    monkeypatch.setattr(cli, "run_developer_nudges", fake("developers"))
    monkeypatch.setattr(cli, "run_org_digests", fake("organisations"))
    runtime = StubRuntime()
    assert cli.main(["run", "--now", "--user", str(USER)], runtime=runtime) == 0
    assert seen == [
        ("developers", {"force": True, "user_ids": [USER]}),
        ("organisations", {"force": True, "user_ids": [USER]}),
    ]
    assert runtime.closed == 1
    out = capsys.readouterr().out.splitlines()
    if ran:
        assert out == [
            "developers: 2026-10-05, 1 recipient(s)",
            f"  {USER} - sent email=sent",
            "organisations: 2026-10-05, 1 recipient(s)",
            f"  {USER} {ORG} already email=no_consent",
        ]
    else:
        assert out[0].startswith("developers: not yet (2026-10-05T06:00:00+00:00; use --now")


def test_run_only_one_pass_without_forcing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    async def developers(deps: Deps, **kwargs: Any) -> Report:
        seen.append(kwargs)
        return Report(NOW, date(2026, 10, 5), True)

    async def organisations(deps: Deps, **kwargs: Any) -> Report:
        raise AssertionError("--only developers runs one pass")

    monkeypatch.setattr(cli, "run_developer_nudges", developers)
    monkeypatch.setattr(cli, "run_org_digests", organisations)
    assert cli.main(["run", "--only", "developers"], runtime=StubRuntime()) == 0
    assert seen == [{"force": False, "user_ids": None}]


def test_run_now_is_refused_in_production(capsys: pytest.CaptureFixture[str]) -> None:
    production = get_settings().model_copy(update={"app_env": "production"})
    assert cli.main(["run", "--now"], settings=production, runtime=StubRuntime()) == 2
    assert "APP_ENV=production refuses it" in capsys.readouterr().err


def test_the_command_is_required() -> None:
    with pytest.raises(SystemExit):
        cli.parser().parse_args([])
    assert cli.parser().parse_args(["run", "--user", str(USER), "--user", str(ORG)]).users == [USER, ORG]
    assert isinstance(cli.parser().parse_args(["run"]).users, type(None))
    assert UUID(str(USER)) == USER
