"""REQ-SCOUT-02/03 (docs/spec/06 6.8 hard filter; round-2 review MINOR 2 carried to EM3): the digest reads the scout's
undigested matches under the matches API's own-member rule. A match found before its author joined the organisation
is not emailed to the organisation's reviewers while the author is an active member, and stays undigested until the
match is available again (here: the author leaves), when the next digest lists it."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.matching.scan import clock_now, run_periodic
from tests.integration.matching.scout_world import (
    ScoutWorld,
    Teaser,
    add_person,
    add_scout,
    add_teaser,
    build,
    deps,
    matches,
    outbox_of,
    publish,
)
from tests.integration.matching.test_scan import WEEK, mine

JOINED = "Wallet by the author who joined"


async def another_developers_proposal(owner_engine: AsyncEngine, world: ScoutWorld, title: str) -> UUID:
    async with owner_engine.begin() as conn:
        author = await add_person(conn, "author", "dev.example.test")
        proposal, _ = await add_teaser(conn, author, world.niche, world.problem, Teaser(title=title))
    return proposal


async def digest_sent(owner_engine: AsyncEngine, scout: UUID) -> dict[UUID, bool]:
    return {m.proposal_id: m.digest_sent_at is not None for m in await matches(owner_engine, scout)}


async def membership(owner_engine: AsyncEngine, sql: str, **params: Any) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text(sql), params)


async def test_a_match_whose_author_joined_the_organisation_is_not_emailed(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    org = world.org
    joined = (await publish(owner_engine, world, "joined", Teaser(title=JOINED)))[0]
    scout = await add_scout(owner_engine, org, [world.niche], recipients=[])
    scan_deps, email = deps(app_engine)
    now = await clock_now(scan_deps.factory)
    first = mine(await run_periodic(scan_deps, now=now, force=True), scout)
    assert (first.matched, outbox_of(email, org)) == (1, [])  # no recipient yet: the match waits
    assert await digest_sent(owner_engine, scout) == {joined: False}

    # The author joins the organisation; the owner adds a reviewer to the digest; another developer publishes.
    await membership(
        owner_engine,
        "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (gen_random_uuid(), :o, :u, '{viewer}')",
        o=org.id,
        u=world.developer,
    )
    await membership(
        owner_engine, "UPDATE scout_agents SET recipients = CAST(:r AS uuid[]) WHERE id = :s", r=[org.reviewer], s=scout
    )
    other = await another_developers_proposal(owner_engine, world, "Cold-chain alerts for dairy co-ops")
    scan_deps, email = deps(app_engine)
    second = mine(await run_periodic(scan_deps, now=now + WEEK, force=True), scout)
    assert second.digest is not None
    [message] = outbox_of(email, org)
    assert "Cold-chain alerts for dairy co-ops" in message.text
    assert JOINED not in message.text
    assert JOINED not in (message.html or "")
    assert await digest_sent(owner_engine, scout) == {joined: False, other: True}  # left undigested, not dropped

    # The author leaves: the match is available again and the next digest lists it.
    await membership(
        owner_engine,
        "UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u",
        o=org.id,
        u=world.developer,
    )
    scan_deps, email = deps(app_engine)
    mine(await run_periodic(scan_deps, now=now + 2 * WEEK, force=True), scout)
    [message] = outbox_of(email, org)
    assert JOINED in message.text
    assert await digest_sent(owner_engine, scout) == {joined: True, other: True}
