"""REQ-PROP-01 drafts through the API: a draft is Tier 0 (its owner's only), Tier 1 is sanitised on every save (422
with the field, REQ-PROP-02), Tier 2 is stored only sealed under the proposal's key in ``proposal_confidential``, and
partial saves apply only what was sent."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import (
    SECRET_APPROACH,
    SECRET_LINK,
    SECRET_PRICING,
    Developers,
    ProposalWorld,
    create,
    draft_body,
    rows,
    user_of,
)


async def test_a_new_draft_is_the_owners_only(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    created = await create(owner, draft_body(proposal_world))
    assert created["status"] == "draft"
    assert created["current"] is None
    draft = created["draft"]
    assert draft["version_no"] == 1
    assert draft["status"] == "draft"
    assert draft["cert_id"] is None
    assert draft["teaser"]["title"] == "Cold-chain alerts"
    assert draft["teaser"]["niche"] == {
        "id": str(proposal_world.niche_id),
        "slug": proposal_world.niche_slug,
        "label": proposal_world.niche_label,
    }
    assert [p["id"] for p in draft["problems"]] == [str(proposal_world.problem_id)]
    assert draft["confidential"]["approach"] == SECRET_APPROACH
    assert draft["confidential"]["pricing"] == SECRET_PRICING
    assert draft["confidential"]["links"] == [SECRET_LINK]

    # Tier 2 is stored only as ciphertext, in its own table.
    [stored] = await rows(
        owner_engine,
        "SELECT ciphertext, wrapped_dek, kms_key_id FROM proposal_confidential WHERE proposal_id = :p",
        p=created["id"],
    )
    assert SECRET_APPROACH.encode() not in bytes(stored.ciphertext)
    assert stored.kms_key_id.startswith("local:")
    [version] = await rows(owner_engine, "SELECT * FROM proposal_versions WHERE proposal_id = :p", p=created["id"])
    assert SECRET_APPROACH not in str(version._asdict())

    # The owner's own Tier-2 read is audited (docs/spec/06 6.1: every read of the Tier-2 tables), ids only.
    reads = await rows(
        owner_engine,
        "SELECT actor_user_id, payload FROM audit_events WHERE action = 'proposal.tier2_read' AND subject_id = :p",
        p=created["id"],
    )
    assert [(r.actor_user_id, r.payload) for r in reads] == [
        (user_of(owner), {"version_ids": [draft["id"]], "by_owner": True})
    ]

    listed = (await owner.get("/api/me/proposals")).json()["items"]
    assert [(i["id"], i["status"], i["title"], i["has_draft"]) for i in listed] == [
        (created["id"], "draft", "Cold-chain alerts", True)
    ]

    other = await developers()
    assert (await other.get(f"/api/me/proposals/{created['id']}")).status_code == 404
    assert (await other.patch(f"/api/me/proposals/{created['id']}", json={})).status_code == 404
    assert (await other.get(f"/api/proposals/{created['id']}")).status_code == 404
    assert (await owner.get(f"/api/proposals/{created['id']}")).status_code == 404  # a draft is no teaser
    assert (await other.get("/api/me/proposals")).json()["items"] == []


async def test_partial_saves_apply_only_what_was_sent(developers: Developers, proposal_world: ProposalWorld) -> None:
    owner = await developers()
    created = await create(owner, {"teaser": {"title": "First idea"}})
    pid = created["id"]
    assert created["draft"]["problems"] == []
    assert created["draft"]["confidential"]["links"] == []

    saved = await owner.patch(
        f"/api/me/proposals/{pid}",
        json={"teaser": {"summary": "<p>Alerts when <b>coolers</b> warm.</p>"}, "confidential": {"notes": "n1"}},
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()["draft"]
    assert draft["teaser"]["title"] == "First idea"
    assert draft["teaser"]["summary"] == "Alerts when coolers warm."  # plain text
    assert draft["confidential"]["notes"] == "n1"

    saved = await owner.patch(
        f"/api/me/proposals/{pid}",
        json={"teaser": {"title": None}, "problem_ids": [str(proposal_world.problem_id)]},
    )
    draft = saved.json()["draft"]
    assert draft["teaser"]["title"] is None
    assert draft["teaser"]["summary"] == "Alerts when coolers warm."
    assert draft["confidential"]["notes"] == "n1"
    assert [p["id"] for p in draft["problems"]] == [str(proposal_world.problem_id)]

    saved = await owner.patch(f"/api/me/proposals/{pid}", json={"problem_ids": []})
    assert saved.json()["draft"]["problems"] == []


@pytest.mark.parametrize(
    ("teaser", "field", "code"),
    [
        ({"summary": "Details at coldchain.co.ke"}, "summary", "contains_domain"),
        ({"title": "Mail jane@example.com"}, "title", "contains_email"),
        ({"problem_statement": "Call 0712 345 678"}, "problem_statement", "contains_phone"),
        ({"impact_claims": "Pay via till 123456"}, "impact_claims", "contains_payment_number"),
        ({"summary": "See https://example.test"}, "summary", "contains_url"),
        ({"summary": " ".join(["word"] * 151)}, "summary", "too_many_words"),
        ({"summary": "Write to janedoe @gmail.com"}, "summary", "contains_email"),
        ({"summary": "Write to jane<b></b>@gmail.com"}, "summary", "contains_email"),
        ({"summary": "See ex\u0430mple.com"}, "summary", "contains_domain"),
        (
            {"problem_statement": "Call \u0660\u0667\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668"},
            "problem_statement",
            "contains_phone",
        ),
    ],
)
async def test_contact_details_are_refused_on_save(
    developers: Developers, teaser: dict[str, Any], field: str, code: str, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    refused = await owner.post("/api/me/proposals", json={"teaser": teaser})
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "invalid_teaser"
    assert [(e["field"], e["code"]) for e in detail["errors"]] == [(field, code)]
    assert await rows(owner_engine, "SELECT id FROM proposals WHERE owner_id = :u", u=user_of(owner)) == []

    created = await create(owner, {"teaser": {"title": "Clean"}})
    patched = await owner.patch(f"/api/me/proposals/{created['id']}", json={"teaser": teaser})
    assert patched.status_code == 422
    assert patched.json()["detail"]["errors"][0]["code"] == code


async def test_unknown_references_are_refused(developers: Developers, proposal_world: ProposalWorld) -> None:
    owner = await developers()
    for body, code in [
        ({"teaser": {"niche_id": "00000000-0000-7000-8000-000000000000"}}, "unknown_niche"),
        ({"teaser": {"county_code": "KE-99"}}, "unknown_county"),
        ({"problem_ids": [str(proposal_world.held_problem_id)]}, "unknown_problem"),
        ({"problem_ids": ["00000000-0000-7000-8000-000000000000"]}, "unknown_problem"),
    ]:
        response = await owner.post("/api/me/proposals", json=body)
        assert response.status_code == 422, body
        assert response.json()["detail"]["code"] == code
    extra = await owner.post("/api/me/proposals", json={"teaser": {"owner_id": "x"}})
    assert extra.status_code == 422
    bad_link = await owner.post("/api/me/proposals", json={"confidential": {"links": ["javascript:alert(1)"]}})
    assert bad_link.status_code == 422


async def test_a_new_problem_is_kept_in_the_draft_until_publishing(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    body = draft_body(proposal_world, link=False)
    body["new_problem"] = {"title": "Milk spoils on the way", "statement": "Farmers lose a third of the milk."}
    created = await create(owner, body)
    assert created["draft"]["new_problem"] == {
        "title": "Milk spoils on the way",
        "statement": "Farmers lose a third of the milk.",
        "niche_id": None,
    }
    assert await rows(owner_engine, "SELECT id FROM problems WHERE created_by = :u", u=user_of(owner)) == []

    cleared = await owner.patch(f"/api/me/proposals/{created['id']}", json={"new_problem": None})
    assert cleared.json()["draft"]["new_problem"] is None
    refused = await owner.patch(
        f"/api/me/proposals/{created['id']}",
        json={"new_problem": {"title": "Call 0712 345 678", "statement": "x"}},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["errors"][0]["field"] == "new_problem.title"
