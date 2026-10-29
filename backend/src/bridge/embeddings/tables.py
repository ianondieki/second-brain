"""Revision 0012's embedding functions as ``EmbeddingTable``s (REQ-PERS-02, REQ-EMB-01; P23-1).

Every call opens its own short transaction on a session with no user bound: the functions answer only the embedding
worker (bridge_app with no ``app.user_id``) and refuse a bound session, so nothing here is reachable from a request.
The readers return ``(id, text, text_hash)``: the developer profiles whose ``profiling`` consent is granted, the
problems any developer may be shown, each with no vector, another model or version, or a text that changed since. A
writer takes the reader's hash back unchanged, recomputes the text under the row lock and returns false, writing
nothing, when the text changed meanwhile or the row left the set; ``reembed`` logs that as a skip. The writers run at
READ COMMITTED, the default isolation (revision 0012 refuses any other).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Final

from pgvector.sqlalchemy import Vector as PgVector
from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.jobs.reembed import StaleRow
from bridge.llm.embeddings import EMBED_DIM, Vector

READER_MAX: Final = 1000  # the readers' largest page (revision 0012 refuses a limit outside 1 to 1,000)


def _writer_sql(function: str) -> TextClause:
    sql = f"SELECT {function}(:id, CAST(:vector AS vector), :model, :version, :text_hash)"
    return text(sql).bindparams(bindparam("vector", type_=PgVector(EMBED_DIM)))


class FunctionTable:
    """One table's reader and writer (revision 0012), each call in its own transaction of an unbound session."""

    name: ClassVar[str]
    _reader: ClassVar[TextClause]
    _writer: ClassVar[TextClause]

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def stale_rows(self, *, model: str, version: str, limit: int) -> Sequence[StaleRow]:
        params = {"model": model, "version": version, "limit": max(1, min(limit, READER_MAX))}
        async with self._factory() as db, db.begin():
            found = await db.execute(self._reader, params)
            return [StaleRow(row_id, row_text, row_hash) for row_id, row_text, row_hash in found.tuples()]

    async def save(self, row: StaleRow, vector: Vector, *, model: str, version: str) -> bool:
        if row.text_hash is None:
            raise ValueError(f"{self.name}: a row is written with the text hash its reader gave")
        params = {"id": row.id, "vector": vector, "model": model, "version": version, "text_hash": row.text_hash}
        async with self._factory() as db, db.begin():
            wrote = (await db.execute(self._writer, params)).scalar_one()
        return bool(wrote)


class ProfileEmbeddingTable(FunctionTable):
    """``developer_profiles.profile_embedding``: headline, bio, liked niches and the last five published teasers."""

    name = "developer_profiles"
    _reader = text("SELECT user_id, text, text_hash FROM app_profiles_to_embed(:model, :version, :limit)")
    _writer = _writer_sql("app_set_profile_embedding")


class ProblemEmbeddingTable(FunctionTable):
    """``problems.embedding``: the title and statement of a published, clear, publicly readable problem."""

    name = "problems"
    _reader = text("SELECT problem_id, text, text_hash FROM app_problems_to_embed(:model, :version, :limit)")
    _writer = _writer_sql("app_set_problem_embedding")


@dataclass(frozen=True, slots=True)
class PerTable:
    """A count for each table."""

    profiles: int
    problems: int


_CLEAR_EMPTY = text("SELECT profiles, problems FROM app_clear_empty_embeddings()")
_STALE = text("SELECT profiles, problems FROM app_stale_embedding_counts(:model, :version)")


async def clear_empty(factory: async_sessionmaker[AsyncSession]) -> PerTable:
    """Clear every vector whose text is empty now (all it was computed from removed); how many on each table."""
    async with factory() as db, db.begin():
        profiles, problems = (await db.execute(_CLEAR_EMPTY)).one()
    return PerTable(int(profiles), int(problems))


async def stale_counts(factory: async_sessionmaker[AsyncSession], *, model: str, version: str) -> PerTable:
    """How many rows of each table the readers would list now for this model and version."""
    async with factory() as db, db.begin():
        profiles, problems = (await db.execute(_STALE, {"model": model, "version": version})).one()
    return PerTable(int(profiles), int(problems))
