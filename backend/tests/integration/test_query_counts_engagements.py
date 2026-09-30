"""P16-E1 item 5 (REQ-FND-01, docs/spec/08 p95 budgets): the engagement lists of both sides, the tracker (detail and
History, for both parties), the organisation's Inbox, scout matches and scouts send as many statements with many rows
as with few (``tests/integration/query_counts.py``).

The engagements span the states whose facts need their own rows (NDA_PENDING: the NDA and its signatures;
IN_IMPLEMENTATION: the signed agreement and its milestones) and the organisation sees some developers by handle
(before INTEREST_CONFIRMED) and some by name, in both the small and the large list."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements import interest as interest_module
from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements.api_world import (
    Seats,
    Tracker,
    World,
    build,
    db_today,
    deals_on,
    open_engagement,
    run,
    seats,
    walk_to,
)
from tests.integration.matching.scout_world import Org, add_person, add_scout
from tests.integration.query_counts import LARGE, SMALL, counted


async def interested(owner_engine: AsyncEngine, world: World, signatory: httpx.AsyncClient, today: date) -> UUID:
    """One more engagement of the world's developer and organisation: the signatory's interest in another of the
    developer's proposals (Stage 0), accepted by the developer (INTEREST_CONFIRMED)."""
    proposal = await _proposal(owner_engine, world, world.developer)
    body = {
        "proposal_id": str(proposal),
        "origin": "org_browse",
        "match_id": None,
        "contact_user_id": str(world.owner),
        "channel": "video_call",
        "contact_by": str(today + timedelta(days=1)),
    }
    created = await signatory.post(f"/api/orgs/{world.org}/interest", json=body)
    assert created.status_code == 201, created.text
    return UUID(created.json()["id"])


async def _proposal(owner_engine: AsyncEngine, world: World, developer: UUID) -> UUID:
    async with owner_engine.begin() as conn:
        niche = await run(conn, "SELECT niche_id FROM proposal_versions WHERE id = :v", v=world.version)
        problem = await run(
            conn, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=world.version
        )
        proposal, _ = await w.add_proposal(conn, developer, niche, problem)
    return proposal


def terms(today: date, milestones: int) -> dict[str, Any]:
    return {
        "ip_terms": "non_exclusive_licence",
        "deemed_acceptance_days": 0,
        "milestones": [
            {"deliverable": f"Part {n}", "amount_kes_minor": 1_000_000, "due_date": str(today + timedelta(days=30 + n))}
            for n in range(milestones)
        ],
    }


async def implementing(t: Tracker, s: Seats, world: World, today: date, milestones: int) -> None:
    """The engagement walked to IN_IMPLEMENTATION on terms of ``milestones`` milestones."""
    await walk_to(t, s, world, today, "NDA_SIGNED")
    await t.ok(s.owner, "propose-terms", terms(today, milestones))
    await walk_to(t, s, world, today, "IN_IMPLEMENTATION")


async def test_engagement_lists_and_the_tracker(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(interest_module, "INTEREST_PER_MINUTE", 100)
    monkeypatch.setattr(interest_module, "INTEREST_IP_PER_MINUTE", 100)
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    lists = ("/api/me/engagements", f"/api/orgs/{world.org}/engagements")
    async with seats(app_engine, deals_on(), world) as s:

        async def accepted() -> UUID:
            engagement = await interested(owner_engine, world, s.signatory, today)
            await Tracker(engagement).ok(s.dev, "accept-interest")
            return engagement

        # NDA_PENDING, IN_IMPLEMENTATION (1 milestone), SIGN_OFF and ORG_INTEREST (the organisation sees a handle).
        pending, working, signing_off = await open_engagement(app_engine, world), await accepted(), await accepted()
        await walk_to(Tracker(pending), s, world, today, "NDA_PENDING")
        await implementing(Tracker(working), s, world, today, 1)
        await walk_to(Tracker(signing_off), s, world, today, "SIGN_OFF")
        await interested(owner_engine, world, s.signatory, today)
        small = [await counted(reader, app_engine, url) for reader, url in zip((s.dev, s.owner), lists, strict=True)]
        assert [len(body["items"]) for _, body in small] == [4, 4]

        await walk_to(Tracker(await accepted()), s, world, today, "NDA_PENDING")
        await walk_to(Tracker(await accepted()), s, world, today, "AGREEMENT_SIGNING")
        busy = await accepted()
        await implementing(Tracker(busy), s, world, today, 10)
        for n in range(LARGE - 7):
            await (accepted() if n % 2 else interested(owner_engine, world, s.signatory, today))
        large = [await counted(reader, app_engine, url) for reader, url in zip((s.dev, s.owner), lists, strict=True)]
        assert [len(body["items"]) for _, body in large] == [LARGE, LARGE]
        assert [count for count, _ in large] == [count for count, _ in small]

        # Each list item says what its engagement's own page says (the batched read is the single read).
        for reader, (_, body) in zip((s.dev, s.owner), large, strict=True):
            for item in body["items"]:
                own = await Tracker(UUID(item["id"])).detail(reader)
                assert {key: own[key] for key in item} == item, item["state"]
        states = {item["state"] for item in large[0][1]["items"]}
        assert {"NDA_PENDING", "AGREEMENT_SIGNING", "IN_IMPLEMENTATION", "SIGN_OFF", "ORG_INTEREST"} <= states

        # The tracker: one milestone, then ten (the same state and path otherwise).
        for reader in (s.dev, s.owner):
            for suffix in ("", "/history"):
                one, body = await counted(reader, app_engine, f"/api/engagements/{working}{suffix}")
                ten, other = await counted(reader, app_engine, f"/api/engagements/{busy}{suffix}")
                assert ten == one, (suffix, reader is s.dev)
                if not suffix:
                    assert [len(b["agreements"][0]["milestones"]) for b in (body, other)] == [1, 10]


async def test_the_inbox(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Delivered tags of as many developers (one open tag per developer and organisation)."""
    world = await build(owner_engine)

    async def pitch(count: int) -> None:
        for _ in range(count):
            async with owner_engine.begin() as conn:
                developer = await add_person(conn, "pitcher", "dev.example.test")
            proposal = await _proposal(owner_engine, world, developer)
            async with owner_engine.begin() as conn:
                await run(
                    conn,
                    "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
                    " VALUES (:id, :p, :o, :d, 'delivered')",
                    id=uuid7(),
                    p=proposal,
                    o=world.org,
                    d=developer,
                )

    await open_engagement(app_engine, world)  # one pitched proposal with its engagement
    await pitch(SMALL - 1)
    url = f"/api/orgs/{world.org}/inbox"
    async with seats(app_engine, deals_on(), world) as s:
        small, body = await counted(s.owner, app_engine, url, {"limit": "50"})
        assert len(body["items"]) == SMALL
        await pitch(LARGE - SMALL)
        large, body = await counted(s.owner, app_engine, url, {"limit": "50"})
        assert len(body["items"]) == LARGE
        assert large == small


async def test_scout_matches_and_scouts(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    async with owner_engine.begin() as conn:
        niche = await run(conn, "SELECT niche_id FROM proposal_versions WHERE id = :v", v=world.version)
        problem = await run(
            conn, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=world.version
        )
    org = Org(
        world.org,
        world.org_name,
        "",
        world.owner,
        world.signatory,
        world.reviewer,
        world.reviewer,
        world.finance,
        world.viewer,
    )

    async def grow(count: int) -> None:
        scout = await add_scout(owner_engine, org, [niche], recipients=[world.reviewer])
        async with owner_engine.begin() as conn:
            await run(
                conn,
                "INSERT INTO agent_runs (id, scout_id, org_id, trigger, status, finished_at, window_end)"
                " VALUES (:id, :scout, :org, 'weekly', 'completed', now(), now())",
                id=uuid7(),
                scout=scout,
                org=world.org,
            )
            for _ in range(count):
                proposal, version = await w.add_proposal(conn, world.developer, niche, problem)
                await run(
                    conn,
                    "INSERT INTO agent_matches (id, scout_id, org_id, proposal_id, version_id, niche_id, score)"
                    " VALUES (:id, :scout, :org, :p, :v, :n, 70)",
                    id=uuid7(),
                    scout=scout,
                    org=world.org,
                    p=proposal,
                    v=version,
                    n=niche,
                )

    async with seats(app_engine, deals_on(), world) as s:
        await grow(SMALL)
        await grow(0)
        matches, body = await counted(s.reviewer, app_engine, f"/api/orgs/{world.org}/matches")
        scouts, listed = await counted(s.owner, app_engine, f"/api/orgs/{world.org}/scouts")
        assert (len(body["items"]), len(listed["items"])) == (SMALL, 2)
        for _ in range(8):
            await grow((LARGE - SMALL) // 8 + 1)
        more_matches, body = await counted(s.reviewer, app_engine, f"/api/orgs/{world.org}/matches")
        more_scouts, listed = await counted(s.owner, app_engine, f"/api/orgs/{world.org}/scouts")
        assert len(body["items"]) >= LARGE
        assert len(listed["items"]) == 10
        assert (more_matches, more_scouts) == (matches, scouts)
