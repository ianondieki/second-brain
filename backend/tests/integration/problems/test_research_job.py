"""REQ-RES-01: the ``research.run`` job (``bridge.jobs.research``): registered with the worker, it binds the staff
admin who started the run, runs the pipeline once and commits; a second delivery of the same job changes nothing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.jobs import app as jobs_app
from bridge.jobs import research as research_job
from bridge.llm.deps import routed_client
from bridge.models.enums import ResearchRunStatus
from bridge.problems.research.runtime import ResearchRuntime
from bridge.problems.research.tasks import QUEUE, RUN_TASK
from tests.integration.problems.research_rig import (
    TELECOM_DRAFT,
    ResearchWorld,
    adapter_of,
    answer,
    llm_runtime,
    rows,
    run_row,
    start,
)


def test_the_job_is_registered_with_the_worker() -> None:
    assert "bridge.jobs.research" in jobs_app.IMPORT_PATHS
    task = research_job.run
    assert (task.name, task.queue) == (RUN_TASK, QUEUE)


async def test_the_job_runs_the_run_as_its_starter_once(
    research_world: ResearchWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    llm = llm_runtime(answer(TELECOM_DRAFT))
    factory = create_session_factory(app_engine)
    runtime = ResearchRuntime(
        get_settings(),
        factory=factory,
        client=lambda db: routed_client(db, factory=factory, settings=get_settings(), runtime=llm),
        catalogue=research_world.catalogue,
    )
    run_id = await start(app_engine, research_world, "networks-telecommunications")
    research_job.use_runtime(runtime)
    try:
        await research_job.run(str(run_id), str(research_world.admin))
        await research_job.run(str(run_id), str(research_world.admin))  # delivered twice: nothing more happens
    finally:
        research_job.use_runtime(None)
    run = await run_row(owner_engine, run_id)
    assert (run.status, run.candidates) == (ResearchRunStatus.COMPLETED.value, 1)
    assert len(adapter_of(llm).requests) == 1
    found = await rows(owner_engine, "SELECT count(*) FROM problems WHERE research_run_id = :r", r=run_id)
    assert found[0][0] == 1


async def test_a_job_naming_someone_else_does_nothing(
    research_world: ResearchWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    llm = llm_runtime(answer(TELECOM_DRAFT))
    factory = create_session_factory(app_engine)
    runtime = ResearchRuntime(
        get_settings(),
        factory=factory,
        client=lambda db: routed_client(db, factory=factory, settings=get_settings(), runtime=llm),
        catalogue=research_world.catalogue,
    )
    run_id = await start(app_engine, research_world, "networks-telecommunications")
    for someone in (research_world.other_admin, research_world.moderator, research_world.developer):
        assert await research_job.run_research(run_id, someone, runtime) is None
    assert adapter_of(llm).requests == []
    assert (await run_row(owner_engine, run_id)).status == "running"
