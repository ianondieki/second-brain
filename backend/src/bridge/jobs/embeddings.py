"""The embedding job (REQ-PERS-02, REQ-EMB-01; P23-1; ``bridge.embeddings.worker``).

``embeddings.reembed`` runs every 15 minutes on the default queue, one run at a time (lock ``embeddings:reembed``),
with no user bound: it clears the vectors of emptied texts, then embeds the stale developer profiles (profiling consent
granted) and readable problems through revision 0012's functions. No retry: whatever a run could not do (the per-run
cap, an embedder that cannot run, a text that kept changing), the next one picks up. Procrastinate's own timestamp is
not used. The runtime is built from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from bridge.embeddings.worker import EmbeddingsRunFailed, EmbeddingsRuntime, run_embeddings
from bridge.jobs.app import app

TASK: Final = "embeddings.reembed"
QUEUE: Final = "default"
LOCK: Final = "embeddings:reembed"
CRON: Final = "*/15 * * * *"

_runtime: EmbeddingsRuntime | None = None


def runtime() -> EmbeddingsRuntime:
    global _runtime
    if _runtime is None:
        _runtime = EmbeddingsRuntime()
    return _runtime


def use_runtime(value: EmbeddingsRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="embeddings-reembed-every-15-minutes")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def reembed(timestamp: int) -> None:
    del timestamp  # the rows' hashes decide what is stale, not the job's own time
    report = await run_embeddings(runtime().deps())
    if report.failed:
        raise EmbeddingsRunFailed(f"embedding pass failed for {', '.join(report.failed)}")
