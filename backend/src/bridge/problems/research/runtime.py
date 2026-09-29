"""The research job's long-lived parts (REQ-RES-01): database sessions and the LLM runtime, built from settings on
first use (tests pass their own). Each run's call goes through ``routed_client`` on the run's own session, bound to
the staff admin who started it, so the ledger, the caps and the D-37 demo-data rule apply to that admin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.llm.client import LLMClient
from bridge.llm.deps import build_runtime, routed_client
from bridge.llm.routing import LLMRuntime
from bridge.problems.research.policy import ResearchPolicy, get_research_policy
from bridge.problems.research.sources import Catalogue, get_catalogue


@dataclass(frozen=True)
class ResearchDeps:
    factory: async_sessionmaker[AsyncSession]
    settings: Settings
    llm: Callable[[AsyncSession], LLMClient]  # the client of a session bound to the run's starter
    catalogue: Catalogue
    policy: ResearchPolicy


class ResearchRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        llm: LLMRuntime | None = None,
        client: Callable[[AsyncSession], LLMClient] | None = None,
        catalogue: Catalogue | None = None,
        policy: ResearchPolicy | None = None,
    ) -> None:
        self._settings, self._factory, self._llm, self._client = settings, factory, llm, client
        self._catalogue, self._policy = catalogue, policy

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def deps(self) -> ResearchDeps:
        settings = self.settings
        if self._factory is None:
            self._factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        factory, client = self._factory, self._client
        if client is None:
            if self._llm is None:
                self._llm = build_runtime(settings)
            llm = self._llm

            def client(db: AsyncSession) -> LLMClient:
                return routed_client(db, factory=factory, settings=settings, runtime=llm)

        return ResearchDeps(
            factory=factory,
            settings=settings,
            llm=client,
            catalogue=self._catalogue or get_catalogue(),
            policy=self._policy or get_research_policy(),
        )

    async def aclose(self) -> None:
        if self._llm is not None:
            await self._llm.aclose()
