"""Demo seed steps for proposals (``bridge.seed.demo``): drafts and publishing through the API (which queues the T2.4
registration), the problems they describe or link, the Pitch, and one Tier-2 view behind the Evaluation NDA."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings
from bridge.seed.demo.data import PROPOSALS, VIEWED, DemoProposal
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one

# ---------------------------------------------------------------------------------------------------- proposals


async def _existing_proposal(owner: AsyncEngine, owner_id: UUID, title: str) -> Any:
    """The owner's proposal whose first version carries ``title`` (registered versions never change, so a proposal
    renamed later is still found), or its draft; hidden (deleted) ones too."""
    return await _one(
        owner,
        "SELECT p.id, p.status::text AS status, cv.cert_id FROM proposals p"
        " LEFT JOIN proposal_versions cv ON cv.id = p.current_version_id"
        " WHERE p.owner_id = :owner AND EXISTS (SELECT 1 FROM proposal_versions v WHERE v.proposal_id = p.id"
        " AND v.version_no = 1 AND v.title = :title) ORDER BY p.created_at LIMIT 1",
        owner=owner_id,
        title=title,
    )


async def _problem_of(owner: AsyncEngine, report: DemoReport, key: str) -> UUID:
    source = next(p for p in PROPOSALS if p.key == key)
    assert source.new_problem is not None
    row = await _one(
        owner,
        "SELECT id FROM problems WHERE created_by = :user AND title = :title AND source = 'developer'",
        user=report.users[source.owner],
        title=source.new_problem.title,
    )
    if row is None:
        raise DemoSeedError(f"the problem of {key} is missing")
    return UUID(str(row.id))


def _draft(proposal: DemoProposal, niches: dict[str, UUID], linked: list[UUID]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "teaser": {
            "title": proposal.title,
            "niche_id": str(niches[proposal.niche]),
            "county_code": proposal.county,
            "maturity": proposal.maturity.value,
            "ask": proposal.ask.value,
            "problem_statement": proposal.problem_statement,
            "impact_claims": proposal.impact_claims,
            "summary": proposal.summary,
        },
        "confidential": {
            "approach": proposal.approach,
            "architecture": proposal.architecture,
            "pricing": proposal.pricing,
            "links": list(proposal.links),
        },
    }
    if proposal.new_problem is not None:
        body["new_problem"] = {"title": proposal.new_problem.title, "statement": proposal.new_problem.statement}
    if linked:
        body["problem_ids"] = [str(problem) for problem in linked]
    return body


async def ensure_proposal(
    owner: AsyncEngine, actors: Actors, proposal: DemoProposal, niches: dict[str, UUID], report: DemoReport
) -> None:
    found = await _existing_proposal(owner, report.users[proposal.owner], proposal.title)
    if found is not None and found.status == "hidden":
        raise DemoSeedError(f"{proposal.key} was deleted by its owner")
    if found is not None and found.status == "published":
        proposal_id, cert_id = UUID(str(found.id)), str(found.cert_id)
    else:
        actor = await actors.get(proposal.owner)
        if found is None:
            linked = [await _problem_of(owner, report, proposal.links_problem_of)] if proposal.links_problem_of else []
            created = await actor.call(
                "POST", "/api/me/proposals", json=_draft(proposal, niches, linked), expect=(201,)
            )
            proposal_id = UUID(created.json()["id"])
        else:  # a draft left by an interrupted run: publish it as it is
            proposal_id = UUID(str(found.id))
        attestation = (await actor.call("GET", "/api/proposals/attestations")).json()
        statements = {"created_it": True, "not_owned_by_employer_or_client": True, "no_third_party_confidential": True}
        published = await actor.call(
            "POST",
            f"/api/me/proposals/{proposal_id}/publish",
            json={"attestations": statements, "attestation_text_version": attestation["version"]},
        )
        outcome = published.json()
        if outcome["moderation"]["state"] != "clear":
            raise DemoSeedError(f"{proposal.key} was held by the pre-screen: change its fixture text")
        cert_id = str(outcome["cert_id"])
        report.did(f"proposal {proposal.key} published ({cert_id})")
    report.proposals[proposal.key] = proposal_id
    report.cert_ids[proposal.key] = cert_id


async def pitch(owner: AsyncEngine, actors: Actors, proposal: DemoProposal, report: DemoReport) -> None:
    """Tag the proposal's organisations that are not tagged yet (P4's Pitch: E2 delivered, E1 and E0 held)."""
    if proposal.key not in report.proposals:
        raise DemoSeedError(f"{proposal.key} is not there to pitch")
    proposal_id = report.proposals[proposal.key]
    wanted = [report.orgs[name] for name in proposal.pitch_to if name in report.orgs]
    async with owner.connect() as conn:
        tagged = set(
            (
                await conn.execute(
                    text("SELECT org_id FROM tags WHERE proposal_id = :p AND org_id = ANY(:orgs)"),
                    {"p": proposal_id, "orgs": wanted},
                )
            ).scalars()
        )
    missing = [str(org_id) for org_id in wanted if org_id not in tagged]
    if not missing:
        return
    actor = await actors.get(proposal.owner)
    result = await actor.call("POST", f"/api/me/proposals/{proposal_id}/tags", json={"org_ids": missing}, expect=(201,))
    statuses = ", ".join(f"{tag['org']['name']}: {tag['status']}" for tag in result.json()["tags"])
    report.did(f"proposal {proposal.key} pitched ({statuses})")


async def record_view(owner: AsyncEngine, actors: Actors, settings: Settings, report: DemoReport) -> None:
    """A fixture reviewer accepts the Evaluation NDA and opens the proposal's Tier 2 once, so "Who has seen this" has
    a row to show. Only with FEATURE_TIER2_ENABLED (make demo and CI's e2e stack set it; the seed notes the skip
    without it)."""
    proposal, org, reviewer = VIEWED
    if not settings.feature_tier2_enabled:
        report.notes.append("Tier-2 view skipped: FEATURE_TIER2_ENABLED is off")
        return
    if proposal.key not in report.proposals or org.legal_name not in report.orgs:
        raise DemoSeedError(f"{proposal.key} or {org.legal_name} is not there")
    proposal_id, org_id = report.proposals[proposal.key], report.orgs[org.legal_name]
    seen = await _one(
        owner,
        "SELECT 1 FROM document_views WHERE proposal_id = :p AND viewer_user_id = :u LIMIT 1",
        p=proposal_id,
        u=report.users[reviewer.email],
    )
    if seen is not None:
        return
    actor = await actors.get(reviewer.email)
    terms = (await actor.call("GET", f"/api/orgs/{org_id}/proposals/{proposal_id}/nda")).json()
    if terms["acceptance_id"] is None:
        body = {
            "template_id": terms["template_id"],
            "sha256": terms["sha256"],
            "logging_notice_version": terms["logging_notice"]["version"],
        }
        await actor.call("POST", f"/api/orgs/{org_id}/proposals/{proposal_id}/nda", json=body, expect=(201,))
    await actor.call("GET", f"/api/orgs/{org_id}/proposals/{proposal_id}/tier2")
    report.did(f"Tier-2 view of {proposal.key} by {actor.email}")
