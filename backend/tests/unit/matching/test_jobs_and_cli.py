"""REQ-SCOUT-02: the scouts' jobs (``scouts.scan`` every 15 minutes, ``scouts.on_new`` per publication, one at a time,
on the installed runtime) and the dev/test trigger ``python -m bridge.matching run [--now] [--proposal ID]``, refused
outside dev and test."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

import bridge.matching.__main__ as cli
from bridge.config import get_settings
from bridge.jobs import scouts as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.matching.config import get_weights
from bridge.matching.runtime import ScoutRuntime
from bridge.matching.scan import Outcome, ScanDeps
from bridge.matching.tasks import LOCK, ON_NEW_TASK, QUEUE, SCAN_TASK
from bridge.notifications.email import FakeEmailProvider

SCOUT, ORG = uuid4(), uuid4()


def test_the_tasks_are_registered_one_scan_at_a_time() -> None:
    assert "bridge.jobs.scouts" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    for name in (SCAN_TASK, ON_NEW_TASK):
        task = app.tasks[name]
        assert (task.queue, task.lock) == (QUEUE, LOCK)
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[SCAN_TASK] == "*/15 * * * *"
    assert ON_NEW_TASK not in crons  # on_new runs only when a proposal is published


class StubRuntime(ScoutRuntime):
    def __init__(self) -> None:
        super().__init__(get_settings())
        self.closed = 0
        self.built = ScanDeps(factory=None, settings=get_settings(), email=FakeEmailProvider(), weights=get_weights())  # type: ignore[arg-type]

    def deps(self) -> ScanDeps:
        return self.built

    async def aclose(self) -> None:
        self.closed += 1


async def test_the_tasks_run_their_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, calls = StubRuntime(), []

    async def periodic(deps: ScanDeps, **kwargs: Any) -> list[Outcome]:
        calls.append(("periodic", deps, kwargs))
        return []

    async def on_new(deps: ScanDeps, proposal: UUID, **kwargs: Any) -> list[Outcome]:
        calls.append(("on_new", deps, {"proposal": proposal, **kwargs}))
        return []

    monkeypatch.setattr(jobs, "run_periodic", periodic)
    monkeypatch.setattr(jobs, "run_on_new", on_new)
    proposal = uuid4()
    jobs.use_runtime(runtime)
    try:
        await jobs.scan(timestamp=0)
        await jobs.on_new(proposal_id=str(proposal))
    finally:
        jobs.use_runtime(None)
    assert calls == [("periodic", runtime.built, {}), ("on_new", runtime.built, {"proposal": proposal})]
    assert isinstance(jobs.runtime(), ScoutRuntime)
    assert jobs.runtime() is jobs.runtime()
    jobs.use_runtime(None)


async def test_the_runtime_builds_its_parts_once_and_a_client_per_session() -> None:
    runtime = ScoutRuntime(get_settings().model_copy(update={"email_provider": "fake"}))
    deps = runtime.deps()
    assert isinstance(deps.email, FakeEmailProvider)
    again = runtime.deps()
    assert (again.factory, again.email) == (deps.factory, deps.email)
    async with deps.factory() as db:
        assert deps.llm(db) is not None  # a routed client over this session (the fake provider under APP_ENV=test)
    await runtime.aclose()


@pytest.mark.parametrize("env", ["staging", "production"])
def test_the_cli_is_refused_outside_dev_and_test(env: str, capsys: pytest.CaptureFixture[str]) -> None:
    settings = get_settings().model_copy(update={"app_env": env})
    assert cli.main(["run", "--now"], settings=settings, runtime=StubRuntime()) == 2
    assert "dev and test" in capsys.readouterr().err


def test_the_cli_runs_a_pass_now(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[tuple[str, Any]] = []

    async def periodic(deps: ScanDeps, *, force: bool) -> list[Outcome]:
        seen.append(("periodic", force))
        return [Outcome(SCOUT, ORG, "completed", uuid4(), 3, 1), Outcome(SCOUT, ORG, "skipped", reason="plan")]

    async def on_new(deps: ScanDeps, proposal: UUID) -> list[Outcome]:
        seen.append(("on_new", proposal))
        return []

    monkeypatch.setattr(cli, "run_periodic", periodic)
    monkeypatch.setattr(cli, "run_on_new", on_new)
    runtime = StubRuntime()
    assert cli.main(["run", "--now"], runtime=runtime) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [
        f"{SCOUT} {ORG} completed read=3 matched=1 digest_recipients=0",
        f"{SCOUT} {ORG} skipped (plan) read=0 matched=0 digest_recipients=0",
    ]
    proposal = uuid4()
    assert cli.main(["run", "--proposal", str(proposal)], runtime=runtime) == 0
    assert "nothing due" in capsys.readouterr().out
    assert seen == [("periodic", True), ("on_new", proposal)]
    assert runtime.closed == 2
