"""Helpers of the embedding job's tests (P23-1; REQ-PERS-02, REQ-EMB-01), over the module's own database
(``conftest.job_url``): committed developers and problems (the job opens its own sessions) and the job's dependencies
over bridge_app sessions with no user bound."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.db import create_session_factory
from bridge.embeddings.worker import EmbeddingsDeps
from bridge.llm.embeddings import Embedder, FakeEmbedder, Vector
from tests.integration.embeddings.schema_world import decide, named_niche, stored_problem, stored_profile
from tests.integration.teams.schema_world import developer


@asynccontextmanager
async def committed(owner: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """One committed transaction as the owner (the schema_world helpers switch roles inside it)."""
    async with owner.begin() as conn:
        yield conn


def deps(
    app: AsyncEngine, embedder: Embedder | None = None, *, batch_size: int = 2, max_rows: int = 500
) -> EmbeddingsDeps:
    return EmbeddingsDeps(create_session_factory(app), embedder or FakeEmbedder(), batch_size, max_rows)


async def consented_developer(owner: AsyncEngine, label: str, *, granted: bool | None = True) -> UUID:
    """A developer who likes one niche of their own (the text: its name), with this profiling decision (None: none)."""
    async with committed(owner) as conn:
        topic = await named_niche(conn, f"{label.title()} {uuid4().hex[:6]}")
        user = await developer(conn, label, peers=False, liked=(topic,))
        if granted is not None:
            await decide(conn, user, granted)
    return user


async def profile(owner: AsyncEngine, user: UUID) -> dict[str, Any]:
    async with committed(owner) as conn:
        return await stored_profile(conn, user)


async def problem(owner: AsyncEngine, problem_id: UUID) -> dict[str, Any]:
    async with committed(owner) as conn:
        return await stored_problem(conn, problem_id)


class Interrupting(FakeEmbedder):
    """The fake embedder, which runs ``action`` once, before its first batch (an edit committed mid-run)."""

    def __init__(self, action: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self._action: Callable[[], Awaitable[None]] | None = action

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        if self._action is not None:
            action, self._action = self._action, None
            await action()
        return await super().embed(texts)
