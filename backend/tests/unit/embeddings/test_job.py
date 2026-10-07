"""REQ-PERS-02, REQ-EMB-01 (P23-1): ``embeddings.reembed`` runs every 15 minutes on the default queue, one run at a
time, on the installed runtime, its own timestamp ignored; the runtime builds its parts from settings once (the fake
embedder in test, the batch size of ai/models.yaml, the cap of policy.yaml) and refuses the fake in production."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.config import get_settings
from bridge.embeddings.policy import EmbeddingsPolicy
from bridge.embeddings.worker import EmbeddingsDeps, EmbeddingsRuntime
from bridge.jobs import embeddings as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.llm import registry as registry_module
from bridge.llm.embeddings import FakeEmbedder


def test_the_job_runs_every_15_minutes_one_run_at_a_time() -> None:
    assert "bridge.jobs.embeddings" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("embeddings.reembed", "default", "embeddings:reembed")
    assert task.configure(task_kwargs={"timestamp": 0}).job.lock == "embeddings:reembed"
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "*/15 * * * *"


async def test_the_task_runs_a_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[EmbeddingsDeps] = []

    async def run(deps: EmbeddingsDeps) -> None:
        calls.append(deps)

    monkeypatch.setattr(jobs, "run_embeddings", run)
    factory: Any = object()
    embedder = FakeEmbedder()
    policy = EmbeddingsPolicy(max_rows_per_run=7)
    jobs.use_runtime(EmbeddingsRuntime(get_settings(), factory=factory, embedder=embedder, batch_size=3, policy=policy))
    try:
        await jobs.reembed(timestamp=0)
    finally:
        jobs.use_runtime(None)
    assert calls == [EmbeddingsDeps(factory, embedder, 3, 7)]
    assert isinstance(jobs.runtime(), EmbeddingsRuntime)
    assert jobs.runtime() is jobs.runtime()
    jobs.use_runtime(None)


def test_the_runtime_builds_its_parts_from_settings_once() -> None:
    settings = get_settings()
    runtime = EmbeddingsRuntime(settings)
    deps = runtime.deps()
    again = runtime.deps()
    assert (again.factory, again.embedder) == (deps.factory, deps.embedder)
    assert isinstance(deps.embedder, FakeEmbedder)  # EMBEDDER=fake in test
    batch = registry_module.load(settings.llm_models_file).embeddings.reembed_batch_size
    assert (deps.batch_size, deps.max_rows) == (batch, 500)


def test_production_refuses_the_fake_embedder() -> None:
    settings = get_settings().model_copy(update={"app_env": "production", "embedder": "fake"})
    with pytest.raises(ValueError, match="production"):
        EmbeddingsRuntime(settings).deps()
