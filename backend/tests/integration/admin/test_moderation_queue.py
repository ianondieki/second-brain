"""REQ-MOD-01 (the AC-PROP-5 queue clause and AC-PROP-6): the moderation queue is staff-only (404 for everyone else,
403 for staff without the moderator role), lists unresolved cases with a Tier-1 preview, and a decision goes through
the definer functions once: approve publishes, reject keeps the subject private, a second decision is 409, a
moderator never decides on their own content, and each decision is audited on the staff member's chain."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.proposals.helpers import (
    TIER2_MARKERS,
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


# --- P15 (PLAN §8; REQ-ADM-01 queues): roles, what a moderator needs to decide, and the order of the queue ----------


async def test_moderators_see_the_moderation_queue_and_admins_see_every_queue(moderators: Staff) -> None:
    """docs/spec/03 staff roles: moderator = the moderation queue; admin = claims, research, directory and the
    moderation queue too; support = read-only elsewhere, no queue here. Enrolled staff lacking the role get 403."""
    queues = ("/api/admin/moderation/cases", "/api/admin/claims", "/api/admin/research/runs", "/api/admin/niches")
    expected = {
        "admin": (200, 200, 200, 200),
        "moderator": (200, 403, 403, 403),
        "support": (403, 403, 403, 403),
    }
    for role, statuses in expected.items():
        staff = await moderators(role=role)
        assert (await staff.get("/api/admin/me")).json() == {"role": role}
        assert tuple([(await staff.get(path)).status_code for path in queues]) == statuses, role


async def test_the_queue_shows_the_flagged_tier1_text_and_what_the_moderator_may_do(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    brand = proposal_world.org_brand
    owner = await developers()
    negative = f"Farmers say {brand} overcharges them for cold storage."
    created = await create(owner, draft_body(proposal_world, impact_claims=negative))
    named = (await publish(owner, created["id"])).json()
    assert named["moderation"]["state"] == "held"
    vulnerable_summary = f"It closes a security vulnerability in the {brand} agent app."
    body = draft_body(proposal_world, title="Agent app patching", summary=vulnerable_summary)
    body["new_problem"] = {"title": "Agents lose float", "statement": "Agents cannot reconcile float at night."}
    flagged = (await publish(owner, (await create(owner, body))["id"])).json()
    assert flagged["moderation"]["state"] == "held"

    moderator = await moderators()
    [case] = await cases_about(moderator, str(named["proposal_id"]))
    assert case["fields"] == [
        {"name": "title", "text": "Cold-chain alerts"},
        {"name": "problem_statement", "text": "Milk spoils before it reaches a cooler."},
        {"name": "impact_claims", "text": negative},
        {"name": "summary", "text": "An SMS goes out when a cooler warms up."},
    ]
    assert case["flagged_fields"] == ["impact_claims"]  # the preview's summary alone would not show it
    assert (case["reasons"], case["subject_state"], case["subject_version_id"]) == (
        ["names_real_org_negative"],
        "held",
        str(named["version_id"]),
    )
    assert (case["actions"], case["blocked"], case["decided_at"], case["decided_by"]) == (
        ["approve", "reject"],
        None,
        None,
        None,
    )

    [vulnerability] = await cases_about(moderator, str(flagged["proposal_id"]))
    assert vulnerability["flagged_fields"] == ["summary"]
    assert (vulnerability["actions"], vulnerability["blocked"]) == (["reject"], "cannot_approve_vulnerability")
    [problem] = await cases_about(moderator, str(flagged["new_problem_id"]))
    assert problem["fields"] == [
        {"name": "title", "text": "Agents lose float"},
        {"name": "statement", "text": "Agents cannot reconcile float at night."},
    ]
    assert (problem["flagged_fields"], problem["actions"], problem["blocked"]) == ([], ["approve", "reject"], None)
    assert (problem["subject_version_id"], problem["subject_state"]) == (None, "clear")

    listing = (await moderator.get("/api/admin/moderation/cases")).text
    assert not any(marker in listing for marker in TIER2_MARKERS)  # Tier-1 text only, never Tier 2

    # What the list says a moderator may do is what the decision route then does.
    refused = await decide(moderator, vulnerability, "approve")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, vulnerability["blocked"])


async def test_own_gone_and_other_subjects_cannot_be_decided_from_this_queue(
    moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    moderator = await moderators()
    own_case, own_problem_case, gone_case, claim_case = uuid7(), uuid7(), uuid7(), uuid7()
    async with owner_engine.begin() as conn:
        own_proposal, _ = await w.add_proposal(
            conn, user_of(moderator), proposal_world.niche_id, proposal_world.problem_id, moderation_state="held"
        )
        own_problem = await w.add_problem(conn, user_of(moderator), proposal_world.niche_id, moderation_state="held")
        for case_id, subject_type, subject_id, source in (
            (own_case, "proposal", own_proposal, "regex"),
            (own_problem_case, "problem", own_problem, "regex"),
            (gone_case, "proposal", uuid7(), "regex"),
            (claim_case, "org_claim", uuid7(), "claim_dispute"),
        ):
            await conn.execute(
                text(
                    "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source) VALUES"
                    " (:id, :type, :subject, ARRAY['security_vulnerability'], CAST(:source AS moderation_source))"
                ),
                {"id": case_id, "type": subject_type, "subject": subject_id, "source": source},
            )
    listed = {c["id"]: c for c in (await moderator.get("/api/admin/moderation/cases")).json()["items"]}
    own, gone, claim = listed[str(own_case)], listed[str(gone_case)], listed[str(claim_case)]
    assert (own["actions"], own["blocked"], own["subject_state"]) == ([], "own_content", "held")
    own_problem_listed = listed[str(own_problem_case)]  # a problem the staff member reported themselves
    assert (own_problem_listed["actions"], own_problem_listed["blocked"]) == ([], "own_content")
    assert own_problem_listed["fields"] == [
        {"name": "title", "text": "RLS problem"},
        {"name": "statement", "text": "Statement"},
    ]
    assert (gone["actions"], gone["blocked"], gone["fields"], gone["subject_state"]) == ([], "subject_gone", [], None)
    assert (claim["actions"], claim["blocked"], claim["fields"]) == ([], "unsupported_subject", [])
    assert claim["preview"] == {"title": None, "text": None}
    unsupported = await decide(moderator, claim, "reject")
    assert (unsupported.status_code, unsupported.json()["detail"]["code"]) == (409, "unsupported_subject")
    # The route answers what the queue says (app_moderate_* refuses own content; a missing subject is caught first).
    for case in (own, own_problem_listed):
        refused = await decide(moderator, case, "reject")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, case["blocked"])
    for decision in ("approve", "reject"):
        refused = await decide(moderator, gone, decision)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "subject_gone")
    [still] = await rows(owner_engine, "SELECT moderation_state FROM problems WHERE id = :p", p=own_problem)
    assert still.moderation_state == "held"


async def test_open_cases_come_oldest_first_and_decided_ones_newest_decision_first(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    problems: list[str] = []
    for n in range(3):
        body = draft_body(proposal_world, title=f"Queue order {n}")
        body["new_problem"] = {"title": f"Queue problem {n}", "statement": "Pumps stall at noon."}
        problems.append(str((await publish(owner, (await create(owner, body))["id"])).json()["new_problem_id"]))
    # Filed in the order 0, 1, 2; dated so the second was filed first (a fixed past, ahead of other tests' cases).
    dated = {problems[0]: "2020-01-02", problems[1]: "2020-01-01", problems[2]: "2020-01-03"}
    async with owner_engine.begin() as conn:
        for problem_id, day in dated.items():
            await conn.execute(
                text("UPDATE moderation_cases SET created_at = CAST(:day AS timestamptz) WHERE subject_id = :id"),
                {"day": day, "id": problem_id},
            )
    moderator = await moderators()

    async def listed(**params: str) -> list[dict[str, Any]]:
        response = await moderator.get("/api/admin/moderation/cases", params=params)
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    queue = [c for c in await listed() if c["subject_id"] in dated]
    assert [c["subject_id"] for c in queue] == [problems[1], problems[0], problems[2]]
    assert queue[0] == (await listed())[0]  # the oldest case of all heads the queue

    by_subject = {c["subject_id"]: c for c in queue}
    for problem_id in (problems[2], problems[1]):  # decided in this order: the newest decision is problems[1]'s
        assert (await decide(moderator, by_subject[problem_id], "approve")).status_code == 200
    async with owner_engine.begin() as conn:  # a strict order of decisions, whatever the clock's resolution
        await conn.execute(
            text("UPDATE moderation_cases SET decided_at = decided_at - interval '1 minute' WHERE subject_id = :id"),
            {"id": problems[2]},
        )
    decided = await listed(decided="true")
    ours = [c for c in decided if c["subject_id"] in dated]
    assert [c["subject_id"] for c in ours] == [problems[1], problems[2]]
    assert decided[0] == ours[0]  # the most recent decision heads the list
    first = ours[0]
    assert (first["status"], first["actions"], first["blocked"]) == ("approved", [], "already_decided")
    assert first["decided_by"] == {"id": str(user_of(moderator)), "display_name": "Staff"}
    assert first["decided_at"] is not None
    remaining = [c for c in await listed() if c["subject_id"] in dated]
    assert [c["subject_id"] for c in remaining] == [problems[0]]


async def test_a_decision_is_made_by_the_moderation_function(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """bridge_app cannot write ``moderation_state`` (no column grant): a held proposal becomes clear only through
    ``app_moderate_proposal`` (SECURITY DEFINER). Without EXECUTE on it the route decides nothing (the database's
    refusal answers like the staff dependency); with it, the approval publishes the teaser."""
    [grant] = await rows(
        owner_engine,
        "SELECT has_column_privilege('bridge_app', 'proposals', 'moderation_state', 'UPDATE') AS can_update",
    )
    assert grant.can_update is False
    owner = await developers()
    created = await create(owner, draft_body(proposal_world, title=f"Why {proposal_world.org_brand} overcharges"))
    assert (await publish(owner, created["id"])).json()["moderation"]["state"] == "held"
    moderator = await moderators()
    [case] = await cases_about(moderator, created["id"])

    function = "app_moderate_proposal(uuid, moderation_state)"
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"REVOKE EXECUTE ON FUNCTION {function} FROM bridge_app"))
    try:
        without = await decide(moderator, case, "approve")
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text(f"GRANT EXECUTE ON FUNCTION {function} TO bridge_app"))
    assert without.status_code == 404
    [held] = await rows(owner_engine, "SELECT moderation_state FROM proposals WHERE id = :p", p=created["id"])
    assert held.moderation_state == "held"
    [still] = await cases_about(moderator, created["id"])
    assert (still["status"], still["decided_by"]) == ("open", None)

    decided = await decide(moderator, case, "approve")
    assert decided.status_code == 200, decided.text
    [proposal] = await rows(owner_engine, "SELECT moderation_state FROM proposals WHERE id = :p", p=created["id"])
    assert proposal.moderation_state == "clear"
    reader = await developers(level="d0")
    assert (await reader.get(f"/api/proposals/{created['id']}")).status_code == 200


async def test_one_case_opens_by_its_id_wherever_it_falls_in_the_queue(
    developers: Developers, moderators: Staff, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """P16-E1 item 3 (P16-C2 carried MINOR 4): the case page reads its case by id. With 200 older open cases ahead
    of it the queue (at most 200, oldest first) no longer lists it, yet the case opens as the queue would show it;
    once decided, as the decided list shows it. The same gates as the queue: 404 for everyone but staff (and for an
    unknown case), 403 for staff without the moderator role or with a stale second factor."""
    owner = await developers()
    body = draft_body(proposal_world, title="Beyond the queue")
    body["new_problem"] = {"title": "Queue overflow", "statement": "Pumps stall at noon."}
    problem_id = str((await publish(owner, (await create(owner, body))["id"])).json()["new_problem_id"])
    moderator = await moderators()
    [case] = await cases_about(moderator, problem_id)
    url = f"/api/admin/moderation/cases/{case['id']}"
    ahead = [uuid7() for _ in range(200)]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, created_at)"
                " SELECT id, 'problem', gen_random_uuid(), ARRAY['security_vulnerability'], 'regex', '2000-01-01'"
                " FROM unnest(CAST(:ids AS uuid[])) AS id"
            ),
            {"ids": ahead},
        )
    try:
        assert await cases_about(moderator, problem_id) == []  # the 201st open case: not in the list
        opened = await moderator.get(url)
        assert opened.status_code == 200, opened.text
        assert opened.json() == case
        assert (await decide(moderator, case, "approve")).status_code == 200
        [decided] = await cases_about(moderator, problem_id, decided=True)
        reopened = await moderator.get(url)
        assert reopened.json() == decided
        assert (decided["status"], decided["actions"], decided["blocked"]) == ("approved", [], "already_decided")

        unknown = await moderator.get(f"/api/admin/moderation/cases/{uuid7()}")
        assert unknown.status_code == 404
        assert unknown.json() == {"detail": {"code": "not_found", "message": "No such case."}}
        assert (await moderator.get("/api/admin/moderation/cases/not-a-uuid")).status_code == 422
        hidden = await owner.get(url)
        assert hidden.status_code == 404
        assert hidden.json() == {"detail": {"code": "not_found", "message": "Not found."}}
        support = await moderators(role="support")
        refused = await support.get(url)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "forbidden")
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE sessions SET mfa_verified_at = now() - interval '13 hours' WHERE user_id = :u"),
                {"u": user_of(moderator)},
            )
        stale = await moderator.get(url)
        assert (stale.status_code, stale.json()["detail"]["code"]) == (403, "step_up_required")
        admin = await moderators(role="admin")
        assert (await admin.get(url)).json() == decided
    finally:
        async with owner_engine.begin() as conn:  # the session's other tests read the queue's first 200
            await conn.execute(text("DELETE FROM moderation_cases WHERE id = ANY(:ids)"), {"ids": ahead})
