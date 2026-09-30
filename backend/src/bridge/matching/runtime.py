"""The scouts' long-lived parts for the jobs and the CLI (REQ-SCOUT-02): database sessions, the email provider and
the LLM runtime, built from settings on first use (tests pass their own, or build ``ScanDeps`` directly).

Each run's model calls go through ``routed_client`` on the run's own session, bound to the scout's acting member and
organisation, so the ledger, the organisation's monthly cap and the D-37 demo-data rule apply to that tenant.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.llm.client import LLMClient
from bridge.llm.deps import build_runtime, routed_client
from bridge.llm.routing import LLMRuntime
from bridge.matching.config import get_weights
from bridge.matching.scan import ScanDeps
from bridge.notifications.email import EmailProvider, provider_from_settings


class ScoutRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        email: EmailProvider | None = None,
        llm: LLMRuntime | None = None,
    ) -> None:
        self._settings, self._factory, self._email, self._llm = settings, factory, email, llm

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def deps(self) -> ScanDeps:
        settings = self.settings
        if self._factory is None:
            self._factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        if self._email is None:
            self._email = provider_from_settings(settings)
        if self._llm is None:
            self._llm = build_runtime(settings)
        factory, llm = self._factory, self._llm

        def client(db: AsyncSession) -> LLMClient:
            return routed_client(db, factory=factory, settings=settings, runtime=llm)

        return ScanDeps(factory=factory, settings=settings, email=self._email, weights=get_weights(), llm=client)

    async def aclose(self) -> None:
        if self._llm is not None:
            await self._llm.aclose()
