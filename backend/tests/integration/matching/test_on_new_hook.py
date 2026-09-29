"""REQ-SCOUT-02 (AC-SCOUT-6): a publication that becomes visible queues ``scouts.on_new`` in its own transaction (a
clear publish, or a moderator's approval of a held one); a held publication queues nothing; a failure to queue never
fails the publication."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.directory.models import Niche
from bridge.matching import tasks
from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    Staff,
    cases_about,
    create,
    decide,
    draft_body,
    publish,
    rows,
)


async def on_new_jobs(owner_engine: AsyncEngine, proposal_id: str) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT queue_name, lock, args FROM procrastinate_jobs WHERE task_name = 'scouts.on_new'"
        " AND args->>'proposal_id' = :p",
        p=proposal_id,
    )


async def test_a_clear_publication_queues_the_on_new_scouts(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world))
    assert (await publish(owner, created["id"])).status_code == 200
    [job] = await on_new_jobs(owner_engine, created["id"])
    assert (job.queue_name, job.lock, job.args) == ("scouts", "scouts:scan", {"proposal_id": created["id"]})


async def test_a_held_publication_queues_nothing_until_approved(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world, title=f"Why {proposal_world.org_brand} overcharges"))
    out = (await publish(owner, created["id"])).json()
    assert out["moderation"]["state"] == "held"
    assert await on_new_jobs(owner_engine, created["id"]) == []
    moderator = await moderators()
    [case] = await cases_about(moderator, created["id"])
    assert (await decide(moderator, case, "approve")).status_code == 200
    assert len(await on_new_jobs(owner_engine, created["id"])) == 1


async def test_a_publication_never_fails_because_its_scouts_could_not_be_queued(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(session: AsyncSession, *args: Any, **kwargs: Any) -> int:
        await session.execute(text("SELECT 1 / 0"))  # a database error inside the savepoint
        return 0

    monkeypatch.setattr(tasks, "defer", broken)
    owner = await developers()
    created = await create(owner, draft_body(proposal_world))
    published = await publish(owner, created["id"])
    assert published.status_code == 200, published.text
    assert await on_new_jobs(owner_engine, created["id"]) == []
    [row] = await rows(owner_engine, "SELECT status, moderation_state FROM proposals WHERE id = :p", p=created["id"])
    assert (row.status, row.moderation_state) == ("published", "clear")
    signals = await rows(owner_engine, "SELECT kind FROM signal_events WHERE item_id = :p", p=created["id"])
    assert [s.kind for s in signals] == ["proposal_published"]  # the rest of the transaction committed


async def test_the_callers_own_failure_is_never_swallowed_as_a_queueing_failure(owner_engine: AsyncEngine) -> None:
    """P10 security review MINOR f: the caller's pending changes flush before the savepoint, so only the defer's own
    failure is logged and swallowed; the caller's failure reaches the caller."""
    async with AsyncSession(owner_engine) as session:
        session.add(Niche(slug=f"orphan-{uuid4().hex[:8]}", name_en="Orphan", parent_id=uuid4()))  # no such parent
        with pytest.raises(IntegrityError):
            await tasks.defer_on_new(session, uuid4())
