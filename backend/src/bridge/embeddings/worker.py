"""One pass of the embedding job (REQ-PERS-02, REQ-EMB-01; P23-1; ``bridge.jobs.embeddings``).

A run, on sessions with no user bound (the embedding worker): first ``app_clear_empty_embeddings()`` (a profile or a
problem whose text became empty loses its vector within one interval), then ``bridge.jobs.reembed.reembed`` over the
developer profiles and then the problems, with the configured embedder (``EMBEDDER``: the fake in dev, CI and the demo;
bge-m3 from local weights in production, ADR-005), batches of ``ai/models.yaml`` ``embeddings.reembed_batch_size`` and
at most ``policy.yaml`` ``embeddings.max_rows_per_run`` rows of each table, then one log line per table with what was
written, cleared and is still stale (``app_stale_embedding_counts``). Freshness is by the text's hash, so a profile,
liked-niche, proposal or problem edit is picked up by the next run with no marking code.

An embedder that cannot run here (``EmbedderUnavailable``: sentence-transformers or the weights missing) logs one line
(the exception's class and the model, never the weights' path) and ends the run; the next run, 15 minutes later, tries
again (no retry storm). Any other failure of one table's pass is logged and the other table still runs; the counts are
logged, then the job fails (``EmbeddingsRunFailed``) so the failure is visible. The runtime is built from settings on
first use and kept: the embedder loads its weights once per worker process, not once per run.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.embeddings.policy import EmbeddingsPolicy, get_embeddings_policy
from bridge.embeddings.tables import PerTable, ProblemEmbeddingTable, ProfileEmbeddingTable, clear_empty, stale_counts
from bridge.jobs.reembed import ReembedReport, reembed
from bridge.llm import registry as registry_module
from bridge.llm.embeddings import Embedder, EmbedderUnavailable, embedder_from_settings
from bridge.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingsDeps:
    factory: async_sessionmaker[AsyncSession]  # bridge_app sessions; never bound to a user
    embedder: Embedder
    batch_size: int  # ai/models.yaml embeddings.reembed_batch_size
    max_rows: int  # policy.yaml embeddings.max_rows_per_run, for each table


@dataclass(frozen=True, slots=True)
class RunReport:
    cleared: PerTable
    tables: tuple[
        ReembedReport, ...
    ]  # the profiles', then the problems' (fewer when one failed or the embedder could not run)
    stale: PerTable | None = None  # rows still stale after the run; None when the embedder could not run
    unavailable: bool = False
    failed: tuple[str, ...] = ()  # tables whose pass raised (the other still ran; the job then fails)


class EmbeddingsRunFailed(RuntimeError):
    """A table's pass raised; the other table ran and the counts were logged first."""


class EmbeddingsRuntime:
    """The job's long-lived parts, built from settings on first use (tests and the demo seed pass their own)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        embedder: Embedder | None = None,
        batch_size: int | None = None,
        policy: EmbeddingsPolicy | None = None,
    ) -> None:
        self._settings, self._factory, self._embedder = settings, factory, embedder
        self._batch_size, self._policy = batch_size, policy

    def deps(self) -> EmbeddingsDeps:
        settings = self._settings = self._settings or get_settings()
        if self._factory is None:
            self._factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        if self._embedder is None or self._batch_size is None:
            embeddings = registry_module.load(settings.llm_models_file).embeddings
            self._embedder = self._embedder or embedder_from_settings(settings, embeddings)
            self._batch_size = self._batch_size or embeddings.reembed_batch_size
        policy = self._policy or get_embeddings_policy()
        return EmbeddingsDeps(self._factory, self._embedder, self._batch_size, policy.max_rows_per_run)


async def run_embeddings(deps: EmbeddingsDeps) -> RunReport:
    """Clear the vectors of emptied texts, then embed what is stale in each table (see the module docstring). A table
    whose pass raises is logged and left; the other still runs and the counts are logged either way."""
    cleared = await clear_empty(deps.factory)
    reports: list[ReembedReport] = []
    failed: list[str] = []
    for table in (ProfileEmbeddingTable(deps.factory), ProblemEmbeddingTable(deps.factory)):
        try:
            reports.append(await reembed(table, deps.embedder, batch_size=deps.batch_size, max_rows=deps.max_rows))
        except EmbedderUnavailable as exc:
            log.warning("embeddings.unavailable", error_type=type(exc).__name__, model=deps.embedder.model)
            return RunReport(cleared, tuple(reports), unavailable=True, failed=tuple(failed))
        except Exception as exc:  # one table's failure must not stop the other's pass
            log.error("embeddings.table_failed", table=table.name, error_type=type(exc).__name__)
            failed.append(table.name)
    stale = await stale_counts(deps.factory, model=deps.embedder.model, version=deps.embedder.version)
    written = {report.table: report.rows for report in reports}
    for name, cleared_rows, stale_rows in (
        (ProfileEmbeddingTable.name, cleared.profiles, stale.profiles),
        (ProblemEmbeddingTable.name, cleared.problems, stale.problems),
    ):
        log.info("embeddings.run", table=name, rows=written.get(name, 0), cleared=cleared_rows, stale=stale_rows)
    return RunReport(cleared, tuple(reports), stale, failed=tuple(failed))
