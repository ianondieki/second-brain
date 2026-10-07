"""The re-embed job (REQ-EMB-01; ADR-005 decision 6: a model change triggers a re-embed job).

``reembed`` asks a table for rows whose ``embed_model``/``embed_version`` differ from the embedder's, that have no
vector yet or (tables that keep a text hash) whose text changed since their vector was computed, embeds them in batches
of ``ai/models.yaml`` ``embeddings.reembed_batch_size`` and writes each vector with the new model and version and the
hash of the text it was listed with. Tables plug in through ``EmbeddingTable``: the developer profiles and the problems
(``bridge.embeddings.tables``, revision 0012's functions, run by the ``embeddings.reembed`` job; REQ-PERS-02); the
teaser embeddings are written at publish (``bridge.proposals.originality.index_teaser``). ``InMemoryEmbeddingTable``
serves the unit tests.

A table may refuse a write (``save`` returns False): the text changed between the listing and the write, or the row
left the set (a consent withdrawn, a problem held). A refusal is not an error and the row is not counted as done; a
changed text is listed again with its new hash and embedded again, at most ``MAX_RETRIES`` more times in one run (a
text that keeps changing waits for the next run). A row written in this run that comes back with the hash it was
written for means the table did not record the write: ``ReembedStalled``.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

from bridge.llm.embeddings import Embedder, Vector
from bridge.logging import get_logger

log = get_logger("bridge.jobs.reembed")

MAX_RETRIES: Final = 2  # further tries of a row in one run after its first (a text edited again and again waits)


@dataclass(frozen=True, slots=True)
class StaleRow:
    id: UUID
    text: str
    text_hash: str | None = None  # the hash of ``text`` the table's writer checks again (None: the table keeps none)


class EmbeddingTable(Protocol):
    @property
    def name(self) -> str: ...

    async def stale_rows(self, *, model: str, version: str, limit: int) -> Sequence[StaleRow]:
        """Up to ``limit`` rows with no vector, another ``embed_model`` or ``embed_version``, or a changed text."""
        ...

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        """Write ``vector`` for ``row`` as it was listed (its ``text_hash`` passed back unchanged). False, writing
        nothing, when the text changed since the listing or the row left the set: a skip, never an error."""
        ...


@dataclass(frozen=True, slots=True)
class ReembedReport:
    table: str
    rows: int  # rows written
    batches: int
    refused: int = 0  # writes the table refused (each logged as skipped)
    abandoned: int = 0  # rows whose last try allowed in the run (1 + MAX_RETRIES) was refused: left for the next run


class ReembedStalled(RuntimeError):
    """A row written in this run came back with the same text hash: ``save`` did not record the write."""


async def reembed(
    table: EmbeddingTable, embedder: Embedder, *, batch_size: int, max_rows: int | None = None
) -> ReembedReport:
    """Re-embed every stale row of ``table``: at most ``max_rows`` tries per run (refused ones included), so a job
    stays bounded."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    written: dict[UUID, str | None] = {}  # row -> the text hash its vector was written for in this run
    tries: Counter[UUID] = Counter()
    given_up: set[UUID] = set()
    tried = refused = batches = 0
    while max_rows is None or tried < max_rows:
        limit = batch_size if max_rows is None else min(batch_size, max_rows - tried)
        abandoned = {row_id for row_id, n in tries.items() if n > MAX_RETRIES}
        listed = await table.stale_rows(model=embedder.model, version=embedder.version, limit=limit + len(abandoned))
        if any(row.id in written and written[row.id] == row.text_hash for row in listed):
            raise ReembedStalled(f"{table.name}: a row came back stale after its save")
        rows = [row for row in listed if row.id not in abandoned][:limit]
        if not rows:
            break
        vectors = await embedder.embed([row.text for row in rows])
        for row, vector in zip(rows, vectors, strict=True):
            tries[row.id] += 1
            tried += 1
            if await table.save(row, vector, model=embedder.model, version=embedder.version):
                written[row.id] = row.text_hash
            else:
                refused += 1
                log.info("embeddings.reembed.skipped", table=table.name, attempt=tries[row.id])
                if tries[row.id] > MAX_RETRIES:
                    given_up.add(row.id)
        batches += 1
    log.info(
        "embeddings.reembed",
        table=table.name,
        rows=len(written),
        batches=batches,
        refused=refused,
        abandoned=len(given_up),
        model=embedder.model,
        version=embedder.version,
    )
    return ReembedReport(table.name, len(written), batches, refused, len(given_up))


def text_hash(text: str) -> str:
    """The SHA-256 of the text's UTF-8 bytes, in hex: what revision 0012 stores with a vector."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class _Stored:
    text: str
    vector: Vector | None = None
    model: str | None = None
    version: str | None = None
    text_hash: str | None = None


@dataclass
class InMemoryEmbeddingTable:
    """An ``EmbeddingTable`` in memory (unit tests), with revision 0012's rules: freshness by the text's hash, and a
    write refused when the text changed since the listing or the row is gone."""

    name: str = "memory"
    rows: dict[UUID, _Stored] = field(default_factory=dict)

    def add(self, row_id: UUID, text: str, *, model: str | None = None, version: str | None = None) -> None:
        self.rows[row_id] = _Stored(text, [0.0] if model else None, model, version, text_hash(text) if model else None)

    async def stale_rows(self, *, model: str, version: str, limit: int) -> Sequence[StaleRow]:
        stale = [
            StaleRow(row_id, row.text, text_hash(row.text))
            for row_id, row in self.rows.items()
            if row.vector is None or (row.model, row.version, row.text_hash) != (model, version, text_hash(row.text))
        ]
        return stale[:limit]

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        stored = self.rows.get(row.id)
        if stored is None or (row.text_hash is not None and row.text_hash != text_hash(stored.text)):
            return False
        stored.vector, stored.model, stored.version = vector, model, version
        stored.text_hash = text_hash(stored.text)
        return True
