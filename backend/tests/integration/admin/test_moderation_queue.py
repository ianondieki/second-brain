"""REQ-MOD-01 (the AC-PROP-5 queue clause and AC-PROP-6): the moderation queue is staff-only (404 for everyone else,
403 for staff without the moderator role), lists unresolved cases with a Tier-1 preview, and a decision goes through
the definer functions once: approve publishes, reject keeps the subject private, a second decision is 409, a
moderator never decides on their own content, and each decision is audited on the staff member's chain."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
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
    user_of,
)


async def test_the_queue_is_staff_only(developers: Developers, moderators: Staff) -> None:
    developer = await developers()
    assert (await developer.get("/api/admin/moderation/cases")).status_code == 404
    body = {"decision": "approve", "subject_version_id": None}
    decision = await developer.post(f"/api/admin/moderation/cases/{uuid7()}/decision", json=body)
    assert decision.status_code == 404
    support = await moderators(role="support")
    assert (await support.get("/api/admin/moderation/cases")).status_code == 403
    assert (await support.post(f"/api/admin/moderation/cases/{uuid7()}/decision", json=body)).status_code == 403
    admin = await moderators(role="admin")
    assert (await admin.get("/api/admin/moderation/cases")).status_code == 200


async def test_a_problem_case_is_decided_once_and_audited(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    body = draft_body(proposal_world)
    body["new_problem"] = {"title": "Solar pumps stall at noon", "statement": "Pumps overheat in the midday sun."}
    created = await create(owner, body)
    problem_id = (await publish(owner, created["id"])).json()["new_problem_id"]

    moderator = await moderators()
    [case] = await cases_about(moderator, problem_id)
    url = f"/api/admin/moderation/cases/{case['id']}/decision"
    assert (await moderator.post(url, json={"decision": "maybe"})).status_code == 422
    rejected = await decide(moderator, case, "reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json() == {"id": case["id"], "status": "rejected", "subject_state": "rejected"}
    sql = "SELECT status, moderation_state, moderator_id FROM problems WHERE id = :id"
    [problem] = await rows(owner_engine, sql, id=problem_id)
    assert (problem.status, problem.moderation_state, problem.moderator_id) == (
        "rejected",
        "rejected",
        user_of(moderator),
    )
    reader = await developers(level="d0")
    assert (await reader.get("/api/problems", params={"q": "Solar pumps stall"})).json()["items"] == []

    again = await decide(moderator, case, "approve")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "already_decided")
    assert await cases_about(moderator, problem_id) == []
    [decided] = await cases_about(moderator, problem_id, decided=True)
    assert decided["status"] == "rejected"
    [row] = await rows(
        owner_engine, "SELECT decided_by, decided_at FROM moderation_cases WHERE id = :id", id=case["id"]
    )
    assert row.decided_by == user_of(moderator)
    assert row.decided_at is not None
    [event] = await rows(
        owner_engine,
        "SELECT actor_kind::text AS kind, actor_user_id, payload FROM audit_events"
        " WHERE action = 'moderation.case_decided' AND subject_id = :id",
        id=case["id"],
    )
    assert (event.kind, event.actor_user_id) == ("staff", user_of(moderator))
    assert event.payload == {"subject_type": "problem", "subject_id": problem_id, "decision": "reject"}
    unknown_body = {"decision": "approve", "subject_version_id": None}
    unknown = await moderator.post(f"/api/admin/moderation/cases/{uuid7()}/decision", json=unknown_body)
    assert unknown.status_code == 404


async def test_a_moderator_never_decides_on_their_own_content(
    moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    moderator = await moderators()
    case_id = uuid7()
    async with owner_engine.begin() as conn:
        proposal_id, version_id = await w.add_proposal(
            conn, user_of(moderator), proposal_world.niche_id, proposal_world.problem_id, moderation_state="held"
        )
        await conn.execute(
            text(
                "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source)"
                " VALUES (:id, 'proposal', :subject, ARRAY['security_vulnerability'], 'regex')"
            ),
            {"id": case_id, "subject": proposal_id},
        )
    own = {"id": str(case_id), "subject_version_id": str(version_id)}
    refused = await decide(moderator, own, "approve")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "own_content")
    [proposal] = await rows(owner_engine, "SELECT moderation_state FROM proposals WHERE id = :p", p=proposal_id)
    assert proposal.moderation_state == "held"
    [case] = await rows(owner_engine, "SELECT status FROM moderation_cases WHERE id = :id", id=case_id)
    assert case.status == "open"
