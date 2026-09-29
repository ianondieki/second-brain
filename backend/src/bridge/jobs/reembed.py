"""The re-embed job (REQ-EMB-01; ADR-005 decision 6: a model change triggers a re-embed job).

``reembed`` asks a table for rows whose ``embed_model``/``embed_version`` differ from the embedder's (or that have
no vector yet), embeds them in batches of ``ai/models.yaml`` ``embeddings.reembed_batch_size`` and writes each vector
with the new model and version. Tables plug in through ``EmbeddingTable``: the SQL tables (teaser embeddings,
developer profiles, the Tier-2 embeddings table read only by the ``tier2_embed_worker`` role) arrive with T2.1 and
T2.3, and each runs as its own one-tenant or system job; the Procrastinate task is registered with them.
``InMemoryEmbeddingTable`` serves tests until then.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from bridge.llm.embeddings import Embedder, Vector
from bridge.logging import get_logger

log = get_logger("bridge.jobs.reembed")


@dataclass(frozen=True, slots=True)
class StaleRow:
    id: UUID
    text: str


class EmbeddingTable(Protocol):
    @property
    def name(self) -> str: ...

    async def stale_rows(self, *, model: str, version: str, limit: int) -> Sequence[StaleRow]:
        """Up to ``limit`` rows with no vector or with another ``embed_model`` or ``embed_version``."""
        ...

    async def save(self, row_id: UUID, vector: Vector, *, model: str, version: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReembedReport:
    table: str
    rows: int
    batches: int


class ReembedStalled(RuntimeError):
    """The table returned rows it had already been given: ``save`` did not record the model and version."""


async def reembed(
    table: EmbeddingTable, embedder: Embedder, *, batch_size: int, max_rows: int | None = None
) -> ReembedReport:
    """Re-embed every stale row of ``table`` (at most ``max_rows`` per run, so a job stays bounded)."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    done: set[UUID] = set()
    batches = 0
    while max_rows is None or len(done) < max_rows:
        limit = batch_size if max_rows is None else min(batch_size, max_rows - len(done))
        rows = await table.stale_rows(model=embedder.model, version=embedder.version, limit=limit)
        if not rows:
            break
        if any(row.id in done for row in rows):
            raise ReembedStalled(f"{table.name}: rows came back stale after save")
        vectors = await embedder.embed([row.text for row in rows])
        for row, vector in zip(rows, vectors, strict=True):
            await table.save(row.id, vector, model=embedder.model, version=embedder.version)
            done.add(row.id)
        batches += 1
    log.info(
        "embeddings.reembed",
        table=table.name,
        rows=len(done),
        batches=batches,
        model=embedder.model,
        version=embedder.version,
    )
    return ReembedReport(table.name, len(done), batches)


@dataclass
class _Stored:
    text: str
    vector: Vector | None = None
    model: str | None = None
    version: str | None = None


@dataclass
class InMemoryEmbeddingTable:
    """An ``EmbeddingTable`` in memory (tests; the SQL tables come with T2.1)."""

    name: str = "memory"
    rows: dict[UUID, _Stored] = field(default_factory=dict)

    def add(self, row_id: UUID, text: str, *, model: str | None = None, version: str | None = None) -> None:
        self.rows[row_id] = _Stored(text, [0.0] if model else None, model, version)

    async def stale_rows(self, *, model: str, version: str, limit: int) -> Sequence[StaleRow]:
        stale = [
            StaleRow(row_id, row.text)
            for row_id, row in self.rows.items()
            if row.vector is None or row.model != model or row.version != version
        ]
        return stale[:limit]

    async def save(self, row_id: UUID, vector: Vector, *, model: str, version: str) -> None:
        row = self.rows[row_id]
        row.vector, row.model, row.version = vector, model, version
