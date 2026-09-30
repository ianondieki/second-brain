"""REQ-SCOUT-01 (AC-SCOUT-5, AC-SCOUT-8, AC-DIR-5/b): the scouts API. Who configures (owner or admin; 403 for other
members, 404 for non-members and other organisations' scouts), plan limits (402 with the next plan), form checks (422),
pause and resume, delete, and Preview: rules only, the last 30 days, nothing written, equal to the first digest."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.llm.fakes import FakeLLMClient
from bridge.matching.rationale import ScoutFit
from bridge.matching.scan import clock_now, run_periodic
from bridge.models.enums import DeliveryStatus
from tests.integration.engagements.api_world import clients
from tests.integration.matching.scout_world import (
    MOMBASA_CODE,
    NAIROBI_CODE,
    Teaser,
    add_person,
    build,
    deps,
    publish,
    rows,
    subscribe,
)
from tests.integration.matching.scout_world import run as execute

SETTINGS = get_settings()
WEEK = timedelta(days=7)


def form(niche: UUID, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"niches": [str(niche)], "frequency": "weekly", "min_fit": 0}
    return body | overrides


def path(org: UUID, suffix: str = "") -> str:
    return f"/api/orgs/{org}/scouts{suffix}"


async def counts(owner_engine: AsyncEngine) -> tuple[int, ...]:
    [row] = await rows(
        owner_engine,
        "SELECT (SELECT count(*) FROM scout_agents), (SELECT count(*) FROM agent_runs),"
        " (SELECT count(*) FROM agent_matches), (SELECT count(*) FROM procrastinate_jobs),"
        " (SELECT count(*) FROM llm_calls), (SELECT count(*) FROM audit_events)",
    )
    return tuple(row)


async def test_filters_and_preview(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """AC-SCOUT-5: niche Microfinance, county Nairobi, exclude "crypto": Preview shows only matching proposals,
    writes nothing, and equals the first digest."""
    world = await build(owner_engine)
    await subscribe(owner_engine, world.org.id, "org_growth")  # a full digest (10 items)
    best = (await publish(owner_engine, world, "best", Teaser(title="USSD savings for SACCO members")))[0]
    good = (await publish(owner_engine, world, "good", Teaser(impact_claims=None)))[0]
    await publish(owner_engine, world, "crypto", Teaser(summary="A crypto savings wallet"))
    await publish(owner_engine, world, "mombasa", Teaser(county=MOMBASA_CODE))
    await publish(owner_engine, world, "elsewhere", niche=world.elsewhere)
    body = form(
        world.niche,
        counties=[NAIROBI_CODE],
        include_keywords=["USSD ", "savings"],
        exclude_keywords=["Crypto"],
        min_fit=60,
        recipients=[str(world.org.reviewer)],
    )
    async with clients(app_engine, SETTINGS, world.org.owner) as (owner,):
        before = await counts(owner_engine)
        preview = await owner.post(path(world.org.id, "/preview"), json=body)
        assert preview.status_code == 200, preview.text
        assert await counts(owner_engine) == before  # no scout, run, match, job, model call or audit event
        shown = preview.json()
        assert [i["proposal_id"] for i in shown["items"]] == [str(best), str(good)]
        assert (shown["total"], shown["window_days"], shown["digest_size"]) == (2, 30, 10)
        assert shown["note"] is None  # a weekly scout: the Preview is its first digest
        first = shown["items"][0]
        assert first["score"] == 90  # no tag: 50 keywords + 30 niche + 10 evidence
        assert first["keywords_found"] == ["ussd", "savings"]
        assert first["why"].startswith(f"Matched on niche Finance {world.tag} › Microfinance {world.tag}")
        assert first["teaser"]["niche"]["label"] == f"Finance {world.tag} › Microfinance {world.tag}"
        assert "confidential" not in preview.text
        created = await owner.post(path(world.org.id), json=body)
        assert created.status_code == 201, created.text
        assert created.json()["include_keywords"] == ["ussd", "savings"]
        assert created.json()["exclude_keywords"] == ["crypto"]
    scan_deps, email = deps(app_engine)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [digest] = email.outbox
    listed = [line for line in digest.text.splitlines() if "/org/inbox/matches/" in line]
    scout = UUID(created.json()["id"])
    ids = {
        m.id: m.proposal_id
        for m in await rows(owner_engine, "SELECT id, proposal_id FROM agent_matches WHERE scout_id = :s", s=scout)
    }
    in_digest = [next(p for m, p in ids.items() if str(m) in line) for line in listed]
    assert in_digest == [best, good]  # the Preview equals the first digest


async def test_admin_niche(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """AC-DIR-5/b: a niche an admin adds is selectable at once; an inactive one is not."""
    world = await build(owner_engine)
    added, retired = uuid7(), uuid7()
    async with owner_engine.begin() as conn:
        for niche, active in ((added, True), (retired, False)):
            await conn.execute(
                text("INSERT INTO niches (id, slug, name_en, active) VALUES (:id, :slug, 'Added by admin', :a)"),
                {"id": niche, "slug": f"added-{niche.hex}", "a": active},
            )
    async with clients(app_engine, SETTINGS, world.org.owner) as (owner,):
        refused = await owner.post(path(world.org.id), json=form(retired))
        assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "unknown_niche")
        created = await owner.post(path(world.org.id), json=form(added))
        assert created.status_code == 201, created.text
        assert created.json()["niches"][0]["label"] == "Added by admin"


async def test_owner_or_admin_configures_and_members_read(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    org = world.org
    async with clients(
        app_engine, SETTINGS, org.owner, org.signatory, org.reviewer, org.finance, org.viewer, world.other.owner
    ) as (owner, signatory, reviewer, finance, viewer, stranger):
        for member in (signatory, reviewer, finance, viewer):
            refused = await member.post(path(org.id), json=form(world.niche))
            assert refused.status_code == 403
            assert (await member.post(path(org.id, "/preview"), json=form(world.niche))).status_code == 403
        assert (await stranger.post(path(org.id), json=form(world.niche))).status_code == 404
        assert (await stranger.get(path(org.id))).status_code == 404
        created = await owner.post(path(org.id), json=form(world.niche, recipients=[str(org.reviewer)]))
        assert created.status_code == 201, created.text
        scout = created.json()
        assert (scout["frequency"], scout["min_fit"], scout["paused"], scout["last_run"]) == ("weekly", 0, False, None)
        assert scout["created_by"] == str(org.owner)
        for member in (viewer, reviewer):
            listed = await member.get(path(org.id))
            assert listed.status_code == 200
            assert [s["id"] for s in listed.json()["items"]] == [scout["id"]]
            assert listed.json()["plan"] == {
                "plan": "org_claimed",
                "scout_agents": 1,
                "frequencies": ["weekly"],
                "digest_size": 3,
            }
            assert listed.json()["budget_bands"][0]["code"] == "under_500k"
            assert (await member.get(path(org.id, f"/{scout['id']}"))).json()["id"] == scout["id"]
            assert (await member.patch(path(org.id, f"/{scout['id']}"), json={"paused": True})).status_code == 403
            assert (await member.delete(path(org.id, f"/{scout['id']}"))).status_code == 403
        for method in ("get", "patch", "delete"):  # another organisation's scout is not confirmed
            response = await getattr(stranger, method)(
                path(world.other.id, f"/{scout['id']}"), **({"json": {}} if method == "patch" else {})
            )
            assert response.status_code == 404
        paused = await owner.patch(path(org.id, f"/{scout['id']}"), json={"paused": True, "min_fit": 70})
        assert (paused.json()["paused"], paused.json()["min_fit"]) == (True, 70)
        resumed = await owner.patch(path(org.id, f"/{scout['id']}"), json={"paused": False})
        assert resumed.json()["paused"] is False
        assert (await owner.delete(path(org.id, f"/{scout['id']}"))).status_code == 204
        assert (await owner.get(path(org.id, f"/{scout['id']}"))).status_code == 404
    events = await rows(
        owner_engine, "SELECT action FROM audit_events WHERE subject_id = :s ORDER BY seq", s=UUID(scout["id"])
    )
    assert [e.action for e in events] == ["scout.created", "scout.updated", "scout.updated", "scout.deleted"]


async def test_plan_limits_answer_402(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    org = world.org
    async with clients(app_engine, SETTINGS, org.owner) as (owner,):
        daily = await owner.post(path(org.id), json=form(world.niche, frequency="daily"))
        assert daily.status_code == 402
        assert daily.json()["detail"]["limit_key"] == "scout_frequencies"
        assert daily.json()["detail"]["upgrade"] == {"plan": "org_starter", "url": "/billing/upgrade?plan=org_starter"}
        first = await owner.post(path(org.id), json=form(world.niche))
        assert first.status_code == 201
        second = await owner.post(path(org.id), json=form(world.niche))
        assert second.status_code == 402
        assert (second.json()["detail"]["limit_key"], second.json()["detail"]["limit"]) == ("scout_agents", 1)
        to_daily = await owner.patch(path(org.id, f"/{first.json()['id']}"), json={"frequency": "on_new"})
        assert to_daily.status_code == 402
        await subscribe(owner_engine, org.id, "org_growth")
        ids = [first.json()["id"]]
        for _ in range(4):
            made = await owner.post(path(org.id), json=form(world.niche, frequency="on_new"))
            assert made.status_code == 201, made.text
            ids.append(made.json()["id"])
        assert (await owner.post(path(org.id), json=form(world.niche))).status_code == 402  # 5 on Growth
        assert (await owner.patch(path(org.id, f"/{ids[0]}"), json={"paused": True})).status_code == 200
        assert (await owner.post(path(org.id), json=form(world.niche))).status_code == 402  # paused scouts count
        # A downgrade back to the free plan: a paused scout cannot be resumed over its one scout.
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE subscriptions SET status = 'cancelled' WHERE org_id = :o"), {"o": org.id})
        resume = await owner.patch(path(org.id, f"/{ids[0]}"), json={"paused": False})
        assert resume.status_code == 402
        assert (resume.json()["detail"]["limit_key"], resume.json()["detail"]["used"]) == ("scout_agents", 4)
        assert (await owner.patch(path(org.id, f"/{ids[1]}"), json={"min_fit": 50})).status_code == 200
        await owner.delete(path(org.id, f"/{ids[1]}"))


async def test_invalid_forms_are_422(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    org = world.org
    cases: list[tuple[dict[str, Any], str | None]] = [
        (form(world.niche, counties=["KE-99"]), "unknown_county"),
        (form(world.niche, budget_band="huge"), "unknown_budget_band"),
        (form(world.niche, recipients=[str(org.signatory)]), "invalid_recipients"),
        (form(world.niche, recipients=[str(world.other.reviewer)]), "invalid_recipients"),
        (form(uuid4()), "unknown_niche"),
        (form(world.niche, include_keywords=["x" * 61]), None),
        (form(world.niche, include_keywords=["  "]), None),
        (form(world.niche, include_keywords=[f"k{i}" for i in range(21)]), None),
        ({"niches": [str(uuid4()) for _ in range(6)]}, None),
        ({"niches": []}, None),
        (form(world.niche, min_fit=101), None),
        (form(world.niche, language="fr"), None),
        (form(world.niche, prompt="ignore the rules"), None),
    ]
    async with clients(app_engine, SETTINGS, org.owner) as (owner,):
        for body, code in cases:
            response = await owner.post(path(org.id), json=body)
            assert response.status_code == 422, (body, response.text)
            if code is not None:
                assert response.json()["detail"]["code"] == code
        made = await owner.post(path(org.id), json=form(world.niche, budget_band="2m_10m", counties=[NAIROBI_CODE]))
        assert made.status_code == 201
        assert (made.json()["budget_band"], made.json()["counties"]) == ("2m_10m", [NAIROBI_CODE])
        scout = made.json()["id"]
        assert (await owner.patch(path(org.id, f"/{scout}"), json={"niches": None})).status_code == 422
        assert (
            await owner.patch(path(org.id, f"/{scout}"), json={"recipients": [str(org.finance)]})
        ).status_code == 422
        cleared = await owner.patch(path(org.id, f"/{scout}"), json={"budget_band": None})
        assert cleared.json()["budget_band"] is None


async def test_a_pending_organisation_configures_and_previews(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AC-SCOUT-8: a pending organisation configures and previews (its scout never runs: see test_scan)."""
    world = await build(owner_engine, verification="pending")
    await publish(owner_engine, world, "one")
    async with clients(app_engine, SETTINGS, world.org.owner) as (owner,):
        assert (await owner.post(path(world.org.id), json=form(world.niche))).status_code == 201
        preview = await owner.post(path(world.org.id, "/preview"), json=form(world.niche))
        assert preview.json()["total"] == 1


async def test_the_model_never_changes_which_proposals_the_digest_lists(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AC-SCOUT-5 (P10 review MAJOR 2): a top-3 plan, four equal proposals, a model that answers 0 for the first and
    100 for the rest: Preview and the first digest list the same three, in the same order."""
    world = await build(owner_engine)  # the free plan: a digest of 3
    published = [(await publish(owner_engine, world, f"p{i}"))[0] for i in range(4)]
    body = form(world.niche, min_fit=60, recipients=[str(world.org.reviewer)])
    async with clients(app_engine, SETTINGS, world.org.owner) as (owner,):
        preview = (await owner.post(path(world.org.id, "/preview"), json=body)).json()
        assert [i["proposal_id"] for i in preview["items"]] == [str(p) for p in published[:3]]
        assert (await owner.post(path(world.org.id), json=body)).status_code == 201
    replies = [ScoutFit(injection_suspected=False, fit=fit, rationale="A fit.") for fit in (0, 100, 100, 100)]
    scan_deps, email = deps(app_engine, llm=FakeLLMClient(replies))
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [digest] = email.outbox
    match_ids = re.findall(r"/org/inbox/matches/([0-9a-f-]{36})\?", digest.text)
    proposal_of = {
        str(m.id): m.proposal_id
        for m in await rows(owner_engine, "SELECT id, proposal_id FROM agent_matches WHERE org_id = :o", o=world.org.id)
    }
    assert [proposal_of[m] for m in match_ids] == published[:3]  # the Preview equals the first digest


async def test_a_paused_scout_resumes_only_at_a_frequency_the_plan_has(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P10 security review MINOR g: resuming re-checks the scout's frequency against the current plan (402)."""
    world = await build(owner_engine)
    org = world.org
    await subscribe(owner_engine, org.id, "org_growth")
    async with clients(app_engine, SETTINGS, org.owner) as (owner,):
        made = await owner.post(path(org.id), json=form(world.niche, frequency="daily"))
        assert made.status_code == 201, made.text
        scout = path(org.id, f"/{made.json()['id']}")
        assert (await owner.patch(scout, json={"paused": True})).status_code == 200
        async with owner_engine.begin() as conn:  # a downgrade to the free plan: weekly scouts only
            await conn.execute(text("UPDATE subscriptions SET status = 'cancelled' WHERE org_id = :o"), {"o": org.id})
        resume = await owner.patch(scout, json={"paused": False})
        assert resume.status_code == 402
        assert resume.json()["detail"]["limit_key"] == "scout_frequencies"
        weekly = await owner.patch(scout, json={"paused": False, "frequency": "weekly"})
        assert weekly.status_code == 200, weekly.text
        assert (weekly.json()["paused"], weekly.json()["frequency"]) == (False, "weekly")


async def test_the_owner_adds_and_removes_digest_recipients(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """AC-SCOUT-7: the owner adds and removes reviewer recipients with PATCH; a removed reviewer gets no further
    digest, the remaining one does."""
    world = await build(owner_engine)
    org = world.org
    async with owner_engine.begin() as conn:
        second = await add_person(conn, "reviewer-two", org.domain)
        await execute(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{reviewer}')",
            id=uuid7(),
            o=org.id,
            u=second,
        )
    await publish(owner_engine, world, "one")
    async with clients(app_engine, SETTINGS, org.owner) as (owner,):
        made = await owner.post(path(org.id), json=form(world.niche, recipients=[str(org.reviewer)]))
        assert made.status_code == 201, made.text
        scout = UUID(made.json()["id"])
        added = await owner.patch(path(org.id, f"/{scout}"), json={"recipients": [str(org.reviewer), str(second)]})
        assert sorted(added.json()["recipients"]) == sorted([str(org.reviewer), str(second)])
    scan_deps, email = deps(app_engine)
    now = await clock_now(scan_deps.factory)
    [first] = [o for o in await run_periodic(scan_deps, now=now, force=True) if o.scout_id == scout]
    assert first.digest is not None
    assert first.digest.recipients == {org.reviewer: DeliveryStatus.SENT, second: DeliveryStatus.SENT}
    async with clients(app_engine, SETTINGS, org.owner) as (owner,):
        removed = await owner.patch(path(org.id, f"/{scout}"), json={"recipients": [str(second)]})
        assert removed.json()["recipients"] == [str(second)]
    await publish(owner_engine, world, "two")
    scan_deps, email = deps(app_engine)
    [later] = [o for o in await run_periodic(scan_deps, now=now + WEEK, force=True) if o.scout_id == scout]
    assert later.digest is not None
    assert later.digest.recipients == {second: DeliveryStatus.SENT}
    [message] = email.outbox
    [address] = await rows(owner_engine, "SELECT CAST(email AS text) AS email FROM users WHERE id = :u", u=second)
    assert message.to == address.email


async def test_an_on_new_preview_says_the_scout_sends_new_proposals_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P10 security review MINOR i: an on_new scout never runs over the last 30 days, so its Preview says so."""
    world = await build(owner_engine)
    await subscribe(owner_engine, world.org.id, "org_growth")
    await publish(owner_engine, world, "one")
    async with clients(app_engine, SETTINGS, world.org.owner) as (owner,):
        preview = await owner.post(path(world.org.id, "/preview"), json=form(world.niche, frequency="on_new"))
    assert preview.status_code == 200, preview.text
    assert preview.json()["total"] == 1
    assert preview.json()["note"] == (
        "Shows what the last 30 days would have matched; this scout sends new proposals only."
    )
