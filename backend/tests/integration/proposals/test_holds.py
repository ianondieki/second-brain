"""AC-PROP-6 (REQ-PROP-02, REQ-MOD-01): a teaser with a bare domain, an email address, a Kenyan phone number and a
vulnerability phrase naming a directory organisation is rejected (contact details, 422) or held (the vulnerability
and the negative naming), and a held teaser or problem is returned by no public or search endpoint, nor readable by
another user at the database, until a moderator approves it. Holds never block the author's own view."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    Staff,
    cases_about,
    create,
    draft_body,
    publish,
    rows,
    user_of,
)


async def visible_to(app_engine: AsyncEngine, user_id: UUID, proposal_id: str) -> int:
    """How many rows of the proposal another user reads as ``bridge_app`` (what any search endpoint could return)."""
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=user_id)
        found = await db.execute(text("SELECT count(*) FROM proposals WHERE id = :id"), {"id": proposal_id})
        return int(found.scalar_one())


async def test_contact_details_in_the_teaser_are_rejected(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    summary = (
        f"A vulnerability in {proposal_world.org_brand} lets agents reset PINs. Write to fix@example.com, visit"
        " pinfix.co.ke or call 0712 345 678."
    )
    refused = await owner.post("/api/me/proposals", json=draft_body(proposal_world, summary=summary))
    assert refused.status_code == 422
    codes = [(e["field"], e["code"]) for e in refused.json()["detail"]["errors"]]
    assert codes == [("summary", "contains_domain"), ("summary", "contains_email"), ("summary", "contains_phone")]
    assert await rows(owner_engine, "SELECT id FROM proposals WHERE owner_id = :u", u=user_of(owner)) == []


async def test_a_vulnerability_naming_an_org_is_held_and_never_approved(
    developers: Developers,
    moderators: Staff,
    proposal_world: ProposalWorld,
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
) -> None:
    owner = await developers()
    brand = proposal_world.org_brand
    summary = f"A vulnerability in the {brand} agent app lets anyone reset a PIN. The corrupt {brand} ignores it."
    created = await create(owner, draft_body(proposal_world, summary=summary))
    pid = created["id"]
    published = await publish(owner, pid)
    assert published.status_code == 200, published.text
    out = published.json()
    assert out["moderation"]["state"] == "held"
    assert out["moderation"]["message"]

    # The author still sees everything.
    mine = (await owner.get(f"/api/me/proposals/{pid}")).json()
    assert mine["moderation"]["state"] == "held"
    assert mine["current"]["teaser"]["summary"] == summary
    assert [i["moderation_state"] for i in (await owner.get("/api/me/proposals")).json()["items"]] == ["held"]

    # Nobody else does: no public endpoint, and no row another user could search.
    reader = await developers(level="d0")
    assert (await reader.get(f"/api/proposals/{pid}")).status_code == 404
    assert (await owner.get(f"/api/proposals/{pid}")).status_code == 404
    assert await visible_to(app_engine, user_of(reader), pid) == 0
    assert await rows(owner_engine, "SELECT id FROM signal_events WHERE item_id = :p", p=pid) == []
    [proposal] = await rows(owner_engine, "SELECT status, moderation_state FROM proposals WHERE id = :p", p=pid)
    assert (proposal.status, proposal.moderation_state) == ("published", "held")

    moderator = await moderators()
    [case] = await cases_about(moderator, pid)
    assert case["reasons"] == ["names_real_org_negative", "security_vulnerability"]
    assert (case["source"], case["status"], case["subject_state"]) == ("regex", "open", "held")
    assert case["preview"]["title"] == "Cold-chain alerts"

    # REQ-PROP-02: vulnerability content is never made public, so a moderator can only reject it.
    url = f"/api/admin/moderation/cases/{case['id']}/decision"
    refused = await moderator.post(url, json={"decision": "approve"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "cannot_approve_vulnerability")
    assert (await reader.get(f"/api/proposals/{pid}")).status_code == 404
    assert await visible_to(app_engine, user_of(reader), pid) == 0
    [still] = await cases_about(moderator, pid)
    assert (still["status"], still["subject_state"]) == ("open", "held")

    # A false positive is released by the author: a corrected version is re-screened, then a moderator approves it.
    clean = "An SMS goes out when a cooler warms up."
    await owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"summary": clean}})
    second = (await publish(owner, pid)).json()
    assert (second["version_no"], second["moderation"]["state"]) == (2, "held")
    [case] = await cases_about(moderator, pid)
    assert "new_version_of_moderated_proposal" in case["reasons"]
    decided = await moderator.post(url, json={"decision": "approve"})
    assert decided.status_code == 200, decided.text
    assert decided.json() == {"id": case["id"], "status": "approved", "subject_state": "clear"}
    card = await reader.get(f"/api/proposals/{pid}")
    assert (card.status_code, card.json()["teaser"]["summary"]) == (200, clean)
    assert await visible_to(app_engine, user_of(reader), pid) == 1
    [signal] = await rows(owner_engine, "SELECT kind FROM signal_events WHERE item_id = :p", p=pid)
    assert signal.kind == "proposal_published"


async def test_a_rejected_teaser_stays_private(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, app_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world, title=f"Why {proposal_world.org_brand} overcharges"))
    out = (await publish(owner, created["id"])).json()
    assert out["moderation"]["state"] == "held"
    moderator = await moderators()
    [case] = await cases_about(moderator, created["id"])
    assert case["reasons"] == ["names_real_org_negative"]
    rejected = await moderator.post(f"/api/admin/moderation/cases/{case['id']}/decision", json={"decision": "reject"})
    assert rejected.json()["subject_state"] == "rejected"
    reader = await developers(level="d0")
    assert (await reader.get(f"/api/proposals/{created['id']}")).status_code == 404
    assert await visible_to(app_engine, user_of(reader), created["id"]) == 0
    assert (await owner.get(f"/api/me/proposals/{created['id']}")).json()["moderation"]["state"] == "rejected"


async def test_a_held_new_problem_is_not_public_but_the_clean_teaser_is(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    body = draft_body(proposal_world)
    body["new_problem"] = {"title": "Agent PIN resets", "statement": "An SQL injection in the agent portal."}
    created = await create(owner, body)
    out = (await publish(owner, created["id"])).json()
    assert out["moderation"]["state"] == "clear"
    problem_id = out["new_problem_id"]
    [problem] = await rows(owner_engine, "SELECT status, moderation_state FROM problems WHERE id = :id", id=problem_id)
    assert (problem.status, problem.moderation_state) == ("published", "held")

    reader = await developers(level="d0")
    card = (await reader.get(f"/api/proposals/{created['id']}")).json()
    assert [p["id"] for p in card["problems"]] == [str(proposal_world.problem_id)]
    found = await reader.get("/api/problems", params={"q": "Agent PIN resets"})
    assert found.json()["items"] == []
    mine = (await owner.get(f"/api/me/proposals/{created['id']}")).json()
    assert problem_id in [p["id"] for p in mine["current"]["problems"]]  # the author still sees it

    moderator = await moderators()
    [case] = await cases_about(moderator, problem_id)
    assert case["reasons"] == ["new_developer_problem", "security_vulnerability"]
    assert case["subject_state"] == "held"
    url = f"/api/admin/moderation/cases/{case['id']}/decision"
    refused = await moderator.post(url, json={"decision": "approve"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "cannot_approve_vulnerability")
    assert (await moderator.post(url, json={"decision": "reject"})).json()["subject_state"] == "rejected"


async def test_a_new_version_of_a_rejected_proposal_goes_back_to_the_moderators(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, app_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world, title=f"Why {proposal_world.org_brand} is a scam"))
    pid = created["id"]
    await publish(owner, pid)
    moderator = await moderators()
    [case] = await cases_about(moderator, pid)
    await moderator.post(f"/api/admin/moderation/cases/{case['id']}/decision", json={"decision": "reject"})

    await owner.patch(f"/api/me/proposals/{pid}", json={"teaser": {"title": "Cold-chain alerts for co-ops"}})
    second = (await publish(owner, pid)).json()
    assert second["version_no"] == 2
    assert second["moderation"]["state"] == "rejected"  # still private: a moderator decides again
    reader = await developers(level="d0")
    assert (await reader.get(f"/api/proposals/{pid}")).status_code == 404
    [again] = await cases_about(moderator, pid)
    assert again["id"] != case["id"]
    assert again["reasons"] == ["new_version_of_moderated_proposal"]
    assert again["preview"]["title"] == "Cold-chain alerts for co-ops"
    await moderator.post(f"/api/admin/moderation/cases/{again['id']}/decision", json={"decision": "approve"})
    assert (await reader.get(f"/api/proposals/{pid}")).json()["version_no"] == 2
    assert await visible_to(app_engine, user_of(reader), pid) == 1
