"""REQ-AUTH-01 with REQ-ENG-04 and REQ-SCOUT-02 (docs/spec/06 6.1; THREAT_MODEL §5): a developer who signed up as
"Achieng Otieno" (through ``create_account``, as signup, OAuth and the demo seed do) publishes a teaser; nothing an
organisation reads before INTEREST_CONFIRMED holds a piece of that name or of the email's local part: the teaser and
Browse, the scout match and its EM3 digest, the Express interest answer, the stage-0 engagement, the organisation's
list and the History. They carry the random handle instead. With the old name-derived handle
(``achieng-otieno-2b2356``) every one of them named her."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.matching.scan import clock_now, run_periodic
from bridge.seed.reference import seed_all
from tests.integration.engagements.api_world import clients, db_today, deals_on
from tests.integration.engagements.test_stage0 import interest
from tests.integration.matching.scout_world import add_scout, build, deps, matches, outbox_of, publish
from tests.integration.test_auth_handles import create_developer, handle_of
from tests.name_tokens import leaked

SETTINGS = deals_on()
NAME = "Achieng Otieno"
LOCAL = "achieng.otieno"


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:  # the free plan signup starts
        await seed_all(conn, get_settings())


async def test_no_organisation_view_before_interest_confirmed_carries_a_piece_of_the_name(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    email = f"{LOCAL}@u{uuid4().hex[:12]}.example.test"
    developer = await create_developer(app_engine, NAME, email)
    world = replace(world, developer=developer, developer_email=email)
    proposal = (await publish(owner_engine, world, "one"))[0]
    handle = await handle_of(owner_engine, developer)
    org = world.org
    scout = await add_scout(owner_engine, org, [world.niche])
    scan_deps, mail = deps(app_engine)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [match] = await matches(owner_engine, scout)
    [em3] = outbox_of(mail, org)
    today = await db_today(owner_engine)
    async with clients(app_engine, SETTINGS, org.signatory, org.viewer, developer) as (signatory, viewer, dev):
        seen = {
            "teaser": await signatory.get(f"/api/proposals/{proposal}"),
            "browse": await signatory.get("/api/proposals", params={"problem": str(world.problem)}),
            "match": await signatory.get(f"/api/orgs/{org.id}/matches/{match.id}"),
        }
        created = await signatory.post(f"/api/orgs/{org.id}/interest", json=interest(world, proposal, match.id, today))
        assert created.status_code == 201, created.text
        engagement = created.json()["id"]
        seen |= {
            "detail": await viewer.get(f"/api/engagements/{engagement}"),
            "list": await viewer.get(f"/api/orgs/{org.id}/engagements"),
            "history": await viewer.get(f"/api/engagements/{engagement}/history"),
        }
        own = await dev.get(f"/api/engagements/{engagement}")
    assert {key: r.status_code for key, r in seen.items()} == dict.fromkeys(seen, 200)
    assert seen["teaser"].json()["owner_handle"] == handle
    assert [item["owner_handle"] for item in seen["browse"].json()["items"]] == [handle]
    assert seen["match"].json()["owner_handle"] == handle
    assert created.json()["developer_name"] == handle
    texts = {key: r.text for key, r in seen.items()} | {"interest": created.text, "em3": em3.text + (em3.html or "")}
    assert {key: leaked(t, NAME, LOCAL) for key, t in texts.items() if leaked(t, NAME, LOCAL)} == {}
    assert own.json()["developer_name"] == NAME  # the developer's own view names her: the check above can see it
