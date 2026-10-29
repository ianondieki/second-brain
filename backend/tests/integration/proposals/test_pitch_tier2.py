"""A Pitch opens Tier 2 to the organisations it reached, and only to them (REQ-PROP-03 with P3's REQ-REPO-01 and
REQ-SEC-01; docs/spec/06 6.1 "auto-grant to orgs I tagged", 6.3).

An E2 organisation whose reviewer meets every other condition of ``can_view_tier2`` (verified domain and address,
TOTP and a fresh second factor, the Master Enterprise Terms accepted by a signatory, ``FEATURE_TIER2_ENABLED`` on) is
refused Tier 2 until the developer pitches the proposal to it; after the Pitch (the default ``grant_on_tag`` hook) the
reviewer accepts the Evaluation NDA and reads the marked page. The E0 and E1 organisations of the same Pitch are held:
no grant exists for them and the E1 organisation's reviewer is still refused.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import SECRET_APPROACH, Developers, ProposalWorld, published, rows
from tests.integration.proposals.pitch_helpers import add_org, pitch
from tests.integration.proposals.tier2_scene import add_e2_org, add_member, add_user, new_template, run, viewer_client

GRANTS = "SELECT org_id, status, source, counts_as_unlock FROM disclosure_grants WHERE proposal_id = :p"


async def test_an_e2_pitch_opens_tier2_after_the_nda_and_a_held_tag_grants_nothing(
    developers: Developers, proposal_world: ProposalWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    dev = await developers()
    proposal_id = (await published(dev, proposal_world, title="Pitched idea"))["proposal_id"]
    tag = UUID(proposal_id).hex[-10:]
    buyer_domain, claimed_domain = f"buyer-{tag}.example.test", f"claimed-{tag}.example.test"
    async with owner_engine.begin() as conn:
        terms = await new_template(conn, "master_enterprise_terms")
        await new_template(conn, "evaluation_nda")  # the current Evaluation NDA
        buyer, _ = await add_e2_org(conn, f"Buyer {tag} Limited", buyer_domain, terms, "{signatory}")
        reviewer = await add_user(conn, f"rita-{tag}@{buyer_domain}", f"Rita Reviewer {tag}")
        await add_member(conn, buyer, reviewer, "{reviewer}")
        claimed, _ = await add_e2_org(conn, f"Claimed {tag} Limited", claimed_domain, terms, "{signatory}")
        await run(conn, "UPDATE organizations SET verification = 'e1' WHERE id = :o", o=claimed)
        claimed_reviewer = await add_user(conn, f"cleo-{tag}@{claimed_domain}", "Cleo Reviewer")
        await add_member(conn, claimed, claimed_reviewer, "{reviewer}")
    unclaimed = (await add_org(owner_engine, f"Listed {tag}", verification="unclaimed", niche_id=None, roles=None)).id

    async with AsyncExitStack() as stack:
        viewer = await viewer_client(stack, app_engine, dev, reviewer)
        held_viewer = await viewer_client(stack, app_engine, dev, claimed_reviewer)
        nda_path = f"/api/orgs/{buyer}/proposals/{proposal_id}/nda"
        page_path = f"/api/orgs/{buyer}/proposals/{proposal_id}/tier2"

        # Before the Pitch: every other condition holds, but no grant.
        before = await viewer.get(page_path)
        assert (before.status_code, before.json()["detail"]["code"]) == (403, "grant_required")

        response = await pitch(dev, proposal_id, buyer, claimed, unclaimed)
        assert response.status_code == 201, response.text
        assert [t["status"] for t in response.json()["tags"]] == [
            "delivered",
            "held_pending_verification",
            "held_unclaimed",
        ]
        grants = await rows(owner_engine, GRANTS, p=proposal_id)
        assert [(g.org_id, g.status, g.source, g.counts_as_unlock) for g in grants] == [
            (buyer, "active", "auto_tagged", False)
        ]

        # The reviewer accepts the Evaluation NDA, then reads the marked page.
        assert (await viewer.get(page_path)).json()["detail"]["code"] == "nda_required"
        terms_shown = (await viewer.get(nda_path)).json()
        accepted = await viewer.post(
            nda_path,
            json={
                "template_id": terms_shown["template_id"],
                "sha256": terms_shown["sha256"],
                "logging_notice_version": terms_shown["logging_notice"]["version"],
            },
        )
        assert accepted.status_code == 201, accepted.text
        page = await viewer.get(page_path)
        assert page.status_code == 200, page.text
        assert page.headers["content-type"].startswith("text/html")
        assert SECRET_APPROACH in page.text
        assert f"Rita Reviewer {tag}" in page.text  # the per-viewer mark
        views = await rows(owner_engine, "SELECT org_id FROM document_views WHERE proposal_id = :p", p=proposal_id)
        assert [v.org_id for v in views] == [buyer]

        # The held tags granted nothing: the E1 organisation's reviewer is refused, and no grant names either.
        held = await held_viewer.get(f"/api/orgs/{claimed}/proposals/{proposal_id}/tier2")
        assert (held.status_code, held.json()["detail"]["code"]) == (403, "org_not_e2")
        assert SECRET_APPROACH not in held.text
        assert (
            await rows(owner_engine, GRANTS + " AND org_id = ANY(:held)", p=proposal_id, held=[claimed, unclaimed])
            == []
        )
