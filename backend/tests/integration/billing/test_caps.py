"""AC-SUB-1 (REQ-BIL-02, REQ-BIL-01) on the real publish route: a Free developer with 3 active (published)
proposals who publishes a 4th gets 402 with the upgrade path, and nothing is created. Hidden proposals are not
active; publishing the next version of an active proposal is not a new proposal."""

from __future__ import annotations

import asyncio
from uuid import UUID

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
from tests.integration.proposals.pitch_helpers import Org, add_org, counts, pitch, pitchable


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


async def test_concurrent_publications_cannot_pass_the_cap_together(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """Three drafts published at once by a Free developer with 2 active proposals: one gets through, two get 402
    (the per-owner advisory lock serialises the count)."""
    owner = await developers()
    for n in range(2):
        await published(owner, proposal_world, title=f"Idea {n}")
    drafts = [await create(owner, draft_body(proposal_world, title=f"Race {n}")) for n in range(3)]
    results = await asyncio.gather(*(publish(owner, d["id"]) for d in drafts))
    assert sorted(r.status_code for r in results) == [200, 402, 402]
    [active] = await rows(
        owner_engine,
        "SELECT count(*) AS n FROM proposals WHERE owner_id = :u AND status = 'published'",
        u=user_of(owner),
    )
    assert active.n == 3


# --- AC-PROP-2 and AC-SUB-5 (REQ-BIL-02, REQ-PROP-03): tags per proposal on the real tag route ---


async def _orgs(owner_engine: AsyncEngine, n: int, verification: str) -> list[Org]:
    return [
        await add_org(owner_engine, f"Cap {verification} {i}", verification=verification, niche_id=None, roles=None)
        for i in range(n)
    ]


async def test_sixth_tag_402(developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine) -> None:
    """AC-PROP-2: a Free developer with 5 tags on a proposal tags a 6th org: 402; the first 5 tags persist."""
    orgs = await _orgs(owner_engine, 6, "unclaimed")
    dev, proposal_id = await pitchable(developers, proposal_world)
    assert (await pitch(dev, proposal_id, *orgs[:3])).status_code == 201
    for org in orgs[3:5]:
        assert (await pitch(dev, proposal_id, org)).status_code == 201
    before = await counts(owner_engine, user_of(dev))
    refused = await pitch(dev, proposal_id, orgs[5])
    assert refused.status_code == 402, refused.text
    assert refused.json()["detail"] == {
        "code": "plan_limit",
        "message": "This needs a higher plan.",
        "limit_key": "tags_per_proposal",
        "limit": 5,
        "used": 5,
        "plan": "dev_free",
        "upgrade": {"plan": "dev_pro_monthly", "url": "/billing/upgrade?plan=dev_pro_monthly"},
    }
    assert await counts(owner_engine, user_of(dev)) == before
    tagged = await rows(owner_engine, "SELECT org_id FROM tags WHERE proposal_id = :p", p=proposal_id)
    assert {r.org_id for r in tagged} == {org.id for org in orgs[:5]}


async def test_a_batch_past_the_cap_creates_nothing(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    orgs = await _orgs(owner_engine, 6, "unclaimed")
    dev, proposal_id = await pitchable(developers, proposal_world)
    assert (await pitch(dev, proposal_id, *orgs[:3])).status_code == 201
    refused = await pitch(dev, proposal_id, *orgs[3:])  # 3 + 3 > 5
    assert (refused.status_code, refused.json()["detail"]["used"]) == (402, 3)
    assert (await counts(owner_engine, user_of(dev)))["tags"] == 3
    whole = await pitch(dev, proposal_id, *_orgs_ids(orgs[3:5]))
    assert whole.status_code == 201  # 3 + 2 = 5 fits
    assert whole.json()["cap"] == {"used": 5, "limit": 5, "plan": "dev_free"}


def _orgs_ids(orgs: list[Org]) -> list[UUID]:
    return [org.id for org in orgs]


async def test_tags_never_paywalled(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """AC-SUB-5: the 1st-5th tags to claimed (E2) organisations never return 402, each opening its engagement, and
    no other paywall (NDA, tracker, messaging) stands in the way of tagging."""
    orgs = await _orgs(owner_engine, 5, "e2")
    dev, proposal_id = await pitchable(developers, proposal_world)
    for org in orgs:
        response = await pitch(dev, proposal_id, org)
        assert response.status_code == 201, response.text
        assert response.json()["tags"][0]["engagement_id"] is not None
    assert (await counts(owner_engine, user_of(dev)))["engagements"] == 5
