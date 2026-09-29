"""AC-SUB-1 (REQ-BIL-02, REQ-BIL-01) on the real publish route: a Free developer with 3 active (published)
proposals who publishes a 4th gets 402 with the upgrade path, and nothing is created. Hidden proposals are not
active; publishing the next version of an active proposal is not a new proposal."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    published,
    rows,
    user_of,
)


async def test_fourth_proposal_402(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    owner_id = user_of(owner)
    first = [await published(owner, proposal_world, title=f"Idea {n}") for n in range(3)]

    body = draft_body(proposal_world, title="Idea 4")
    body["new_problem"] = {"title": "A fourth problem", "statement": "It would be created at publishing."}
    fourth = await create(owner, body)
    version_id = fourth["draft"]["id"]
    refused = await publish(owner, fourth["id"])
    assert refused.status_code == 402, refused.text
    assert refused.json()["detail"] == {
        "code": "plan_limit",
        "message": "This needs a higher plan.",
        "limit_key": "active_proposals",
        "limit": 3,
        "used": 3,
        "plan": "dev_free",
        "upgrade": {"plan": "dev_pro_monthly", "url": "/billing/upgrade?plan=dev_pro_monthly"},
    }

    # Nothing was created: the draft is untouched and nothing was registered, attested, queued, signalled or audited.
    sql = "SELECT status, current_version_id FROM proposals WHERE id = :p"
    [proposal] = await rows(owner_engine, sql, p=fourth["id"])
    assert (proposal.status, proposal.current_version_id) == ("draft", None)
    [version] = await rows(owner_engine, "SELECT status, cert_id FROM proposal_versions WHERE id = :v", v=version_id)
    assert (version.status, version.cert_id) == ("draft", None)
    assert await rows(owner_engine, "SELECT id FROM attestations WHERE version_id = :v", v=version_id) == []
    assert await rows(owner_engine, "SELECT id FROM problems WHERE created_by = :u", u=owner_id) == []
    assert await rows(owner_engine, "SELECT id FROM signal_events WHERE item_id = :p", p=fourth["id"]) == []
    assert await rows(owner_engine, "SELECT id FROM moderation_cases WHERE subject_id = :p", p=fourth["id"]) == []
    jobs = await rows(owner_engine, "SELECT id FROM procrastinate_jobs WHERE args->>'version_id' = :v", v=version_id)
    assert jobs == []
    sql = "SELECT id FROM audit_events WHERE action = 'proposal.published' AND actor_user_id = :u"
    events = await rows(owner_engine, sql, u=owner_id)
    assert len(events) == 3
    assert (await owner.get(f"/api/me/proposals/{fourth['id']}")).json()["draft"]["new_problem"] is not None

    # The next version of an active proposal is not a new proposal.
    edited = await owner.patch(f"/api/me/proposals/{first[0]['proposal_id']}", json={"teaser": {"title": "Idea 0 v2"}})
    assert edited.status_code == 200
    assert (await publish(owner, first[0]["proposal_id"])).status_code == 200

    # A hidden proposal is not active: the 4th publishes once one is hidden.
    assert (await owner.delete(f"/api/me/proposals/{first[1]['proposal_id']}")).json()["status"] == "hidden"
    allowed = await publish(owner, fourth["id"])
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["new_problem_id"] is not None
