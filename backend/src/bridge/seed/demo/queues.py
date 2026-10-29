"""The demo's staff queues (P15; REQ-ADM-01, REQ-MOD-01, REQ-DIR-03 queue; M2 walkthrough step 6). Part of
``python -m bridge.seed --demo``, after the scout, so each queue of the ``/admin`` console has an item on ``make demo``.

**Moderation** (the demo staff moderator, ``data.STAFF_MODERATOR``): Amina publishes ``HELD`` through the API. Its
problem statement names SACCO B (fixture) negatively, so the rules pre-screen holds it (``names_real_org_negative``):
the teaser stays private and a case is filed (``app_open_moderation_case``), and the new problem it describes is
published with its own open case, as every developer-reported problem is. The moderator may approve or reject it
(``POST /api/admin/moderation/cases/{id}/decision``). The seeded P1, P2, P3 and P5 problems are in the queue too.

**Claims** (the demo staff admin, read only in the prototype): County Government of C (fixture), E1 on its domain,
asks for E2. Its owner files the claim as the claim flow will: an ``org_claims`` row written by the claimant under
Row-Level Security (the INSERT policy: their own open claim, the address on the claimed domain, no proof or decision
columns), ``level`` e2, awaiting review, public entity requested; there are no documents (no upload path yet). As an
active owner the claimant competes with nobody, so it is no dispute. The claims queue shows it with its 2-business-day
review SLA; nobody decides it in the prototype.

P9's re-seed rules: the proposal is looked for by its first title and the claim by claimant and organisation (any
status), so a case a moderator decided, a proposal Amina changed or a claim that was withdrawn is left as it is, and a
used demo signs nobody in. Dev and test only (``demo_refusal``, checked by the seed before any step).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.models.enums import ModerationState, ProposalAsk, ProposalMaturity
from bridge.seed.demo.data import AMINA, COUNTY_C, SACCO_B, DemoProblem, DemoProposal
from bridge.seed.demo.proposals import _draft, _existing_proposal
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one

HELD = DemoProposal(
    key="P6",
    owner=AMINA.email,
    title="Clear loan-fee statements for SACCO members",
    niche=SACCO_B.niche,
    county="KE-22",
    maturity=ProposalMaturity.IDEA,
    ask=ProposalAsk.PILOT,
    problem_statement=(
        f"Members say {SACCO_B.legal_name} overcharges them on late-repayment fees and cannot explain the charges on"
        " their statements."
    ),
    impact_claims="Aims to cut fee disputes at the branch counter by showing every charge with its reason.",
    summary=(
        "A member statement that lists each fee next to the repayment it came from, with the rule that set it, and a"
        " short form to query a charge."
    ),
    approach=(
        "Fee rules are read from the SACCO's product sheet; each charge on the loan ledger is matched to the rule and"
        " the repayment that triggered it, and the statement explains it in one line."
    ),
    architecture="A statement service over a read-only copy of the loan ledger, and a query form for members.",
    pricing="KES 40,000 setup per SACCO, then KES 3 per member statement.",
    new_problem=DemoProblem(
        title="SACCO members cannot check loan fees",
        statement=(
            "Members of small SACCOs see fees on their statements with no explanation and cannot tell whether a charge"
            " is right."
        ),
    ),
)
CLAIMED: Final = COUNTY_C  # asks for E2 (it is E1 on its domain)

_CLAIM_OF: Final = "SELECT 1 FROM org_claims WHERE org_id = :org AND claimant_user_id = :user LIMIT 1"
_FILE_CLAIM: Final = text(
    "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status,"
    " public_entity_requested) VALUES (:id, :org, :user, :domain, :email, 'e2', 'pending_review', true)"
)


async def seed_queues(
    owner: AsyncEngine,
    actors: Actors,
    factory: async_sessionmaker[AsyncSession],
    niches: dict[str, UUID],
    report: DemoReport,
) -> None:
    """An item in each staff queue (see the module docstring): the claim first (no sign-in), then the held proposal."""
    await ensure_claim(owner, factory, report)
    await ensure_held_proposal(owner, actors, niches, report)


async def ensure_claim(owner: AsyncEngine, factory: async_sessionmaker[AsyncSession], report: DemoReport) -> None:
    """County C's owner asks for E2: a claim awaiting review, written by the claimant under RLS."""
    if CLAIMED.owner is None or CLAIMED.domain is None:
        raise DemoSeedError(f"{CLAIMED.legal_name} has no owner or domain to claim with")
    org_id, user_id = report.orgs.get(CLAIMED.legal_name), report.users.get(CLAIMED.owner.email)
    if org_id is None or user_id is None:
        raise DemoSeedError(f"{CLAIMED.legal_name} or its owner is not there to claim E2")
    if await _one(owner, _CLAIM_OF, org=org_id, user=user_id) is not None:
        return
    async with factory() as db:
        await bind_tenant(db, user_id=user_id, org_id=org_id)
        params = {
            "id": uuid7(),
            "org": org_id,
            "user": user_id,
            "domain": CLAIMED.domain,
            "email": CLAIMED.owner.email,
        }
        await db.execute(_FILE_CLAIM, params)
        await db.commit()
    report.did(f"E2 claim of {CLAIMED.legal_name} by {CLAIMED.owner.email} (awaiting review)")


async def ensure_held_proposal(owner: AsyncEngine, actors: Actors, niches: dict[str, UUID], report: DemoReport) -> None:
    """Amina publishes ``HELD`` through the API; the pre-screen holds it for the moderator."""
    owner_id = report.users.get(HELD.owner)
    if owner_id is None:
        raise DemoSeedError(f"{HELD.owner} is not there to publish {HELD.key}")
    found = await _existing_proposal(owner, owner_id, HELD.title)
    if found is not None and found.status == "hidden":
        raise DemoSeedError(f"{HELD.key} was deleted by its owner")
    if found is not None and found.status == "published":
        report.proposals[HELD.key] = UUID(str(found.id))
        report.cert_ids[HELD.key] = str(found.cert_id)
        return
    actor = await actors.get(HELD.owner)
    if found is None:
        created = await actor.call("POST", "/api/me/proposals", json=_draft(HELD, niches, []), expect=(201,))
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
    if outcome["moderation"]["state"] != ModerationState.HELD.value:
        raise DemoSeedError(f"{HELD.key} was not held by the pre-screen: change its fixture text")
    report.proposals[HELD.key] = proposal_id
    report.cert_ids[HELD.key] = str(outcome["cert_id"])
    report.did(f"proposal {HELD.key} published and held for moderation ({outcome['cert_id']})")


__all__ = ["CLAIMED", "HELD", "ensure_claim", "ensure_held_proposal", "seed_queues"]
