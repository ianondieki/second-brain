"""AC-TRACK-8/b (REQ-ENG-04, REQ-SCOUT-03): an untagged proposal in a fixture organisation's real scout digest. The
signatory follows the digest's link, expresses interest from the match, the developer accepts: an engagement exists,
EM2 is sent exactly once, the tracker shows the developer's endorsement of stage 0; a reviewer gets 403."""

from __future__ import annotations

import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.matching.scan import clock_now, run_periodic
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import Tracker, clients, db_today, deals_on, run_notifications
from tests.integration.matching.scout_world import add_scout, build, deps, publish, rows

SETTINGS = deals_on()


async def test_stage_0_from_a_real_digest(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    proposal = (await publish(owner_engine, world, "untagged"))[0]
    assert await rows(owner_engine, "SELECT id FROM tags WHERE proposal_id = :p", p=proposal) == []
    await add_scout(owner_engine, world.org, [world.niche], recipients=[world.org.reviewer])
    scan_deps, email = deps(app_engine)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [digest] = email.outbox
    assert digest.to.endswith(f"@{world.org.domain}")
    [link] = re.findall(r"/org/inbox/matches/([0-9a-f-]{36})\?org=" + str(world.org.id), digest.text)
    match = UUID(link)
    today = await db_today(owner_engine)
    body = {
        "proposal_id": str(proposal),
        "origin": "org_agent_match",
        "match_id": str(match),
        "contact_user_id": str(world.org.signatory),
        "channel": "email",
        "contact_by": str(today + timedelta(days=1)),
    }
    async with clients(app_engine, SETTINGS, world.org.reviewer, world.org.signatory, world.developer) as (
        reviewer,
        signatory,
        dev,
    ):
        page = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
        assert page["proposal_id"] == str(proposal)
        assert page["interest"] == {"allowed": True, "reason": None}
        refused = await reviewer.post(f"/api/orgs/{world.org.id}/interest", json=body)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "role_required")
        created = await signatory.post(f"/api/orgs/{world.org.id}/interest", json=body)
        assert created.status_code == 201, created.text
        engagement = UUID(created.json()["id"])
        tracker = Tracker(engagement)
        accepted = await tracker.ok(dev, "accept-interest")
        assert accepted["state"] == "INTEREST_CONFIRMED"
        history = (await dev.get(tracker.path("/history"))).json()
        [endorsement] = history["endorsements"]
        assert (endorsement["stage"], endorsement["party"]) == ("ORG_INTEREST", "developer")
    provider = FakeEmailProvider()
    for _ in range(2):  # a retried job never sends twice
        await run_notifications(owner_engine, app_engine, engagement, provider, SETTINGS, keep=True)
    subjects = [m.subject for m in provider.outbox]
    assert sum(s.startswith("Good news:") for s in subjects) == 1  # EM2 exactly once
    assert sum("is interested in" in s for s in subjects) == 1  # N17 once
    [row] = await rows(
        owner_engine, "SELECT origin::text AS origin, state::text AS state FROM engagements WHERE id = :e", e=engagement
    )
    assert (row.origin, row.state) == ("org_agent_match", "INTEREST_CONFIRMED")
