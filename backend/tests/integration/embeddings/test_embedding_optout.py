"""AC-PERS-3 with the embedding job (P23-1; REQ-PERS-02), in a database of its own: turning personalisation off clears
the profile embedding at once, in the settings request itself (the app calls ``app_clear_profile_embedding`` beside
revision 0012's withdrawal trigger), the job never embeds the profile while the consent is off, and turning it on again
gets it embedded by the next run."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.embeddings.worker import run_embeddings
from bridge.llm.embeddings import FAKE_MODEL, FAKE_VERSION
from tests.integration.embeddings.job_world import consented_developer, deps, profile
from tests.integration.embeddings.schema_world import EMPTY_PROFILE, listed
from tests.integration.engagements import tracker as t
from tests.integration.engagements.api_world import clients
from tests.integration.query_counts import statements

CLEARER = "app_clear_profile_embedding"


async def decide(client: httpx.AsyncClient, app: AsyncEngine, **decisions: bool) -> list[str]:
    """PUT /api/me/consents with these decisions; the statements the request sent."""
    version = (await client.get("/api/consents")).json()["version"]
    body: dict[str, Any] = {purpose: {"granted": granted, "version": version} for purpose, granted in decisions.items()}
    with statements(app) as seen:
        response = await client.put("/api/me/consents", json=body)
    assert response.status_code == 200, response.text
    return seen


async def is_listed(owner: AsyncEngine, user: UUID) -> bool:
    async with t.as_app(owner) as conn:
        return user in await listed(conn, user, model=FAKE_MODEL, version=FAKE_VERSION)


async def test_turning_profiling_off_clears_the_embedding_at_once_and_the_job_leaves_it(
    job_owner: AsyncEngine, job_app: AsyncEngine
) -> None:
    user = await consented_developer(job_owner, "optout", granted=None)
    async with clients(job_app, get_settings(), user) as (developer,):
        sent = await decide(developer, job_app, profiling=True, marketing=False)
        assert not [s for s in sent if CLEARER in s]  # a grant clears nothing
        await run_embeddings(deps(job_app))
        assert (await profile(job_owner, user))["embed_model"] == FAKE_MODEL

        sent = await decide(developer, job_app, profiling=False)
        assert [s for s in sent if CLEARER in s]  # in the request, beside the trigger
        assert await profile(job_owner, user) == EMPTY_PROFILE
        assert not await is_listed(job_owner, user)
        await run_embeddings(deps(job_app))
        assert await profile(job_owner, user) == EMPTY_PROFILE  # never embedded while the consent is off

        await decide(developer, job_app, marketing=True)  # another purpose: the profile stays as it is
        assert await profile(job_owner, user) == EMPTY_PROFILE

        await decide(developer, job_app, profiling=True)
        assert await is_listed(job_owner, user)
        await run_embeddings(deps(job_app))
    stored = await profile(job_owner, user)
    assert (stored["embed_model"], stored["embed_version"]) == (FAKE_MODEL, FAKE_VERSION)
