"""The staff admin's claims queue, read only (REQ-DIR-03 queue, REQ-ADM-01; docs/spec/06 6.2, 6.12; PLAN §8 P15).

``/api/admin/claims``: a sub-router of the admin console. Staff admin only (``bridge.admin.deps``: 404 for everyone
else, 403 for moderators and support, 403 ``step_up_required`` for an old second factor); docs/spec/03 gives claims
to the admin role. The database repeats the rule: ``org_claims`` rows are read under Row-Level Security, whose policy
admits staff (``app_is_staff``), and ``otp_hash`` is not even selectable by ``bridge_app``.

- ``GET /api/admin/claims?view=review`` (the default): the claims awaiting staff, ``pending_review`` and ``disputed``,
  oldest first. A ``pending_review`` claim carries its review SLA (policy.yaml ``claims.review_sla_bd``, 2 Kenyan
  business days from the Nairobi day it was submitted, due at the end of that day, on the shared clock); a dispute
  carries its open ``claim_dispute`` moderation case instead. ``view=in_progress``: claims still waiting for the
  claimant (the email code, the DNS record), newest first. ``view=closed``: approved, rejected and withdrawn claims,
  newest decision first. At most 200 per view.
- ``GET /api/admin/claims/{claim_id}``: the same item with the evidence (the domain email, both proofs, the E2 facts, a
  count of the uploaded documents), the organisation's official and verified domains, its other open claims and the
  moderation cases about the claim. Never the OTP digest, the DNS token or the documents' storage keys.

Nothing here decides a claim: the prototype has no claim decision (``app_decide_claim`` is not called, and no route
but these two GETs exists), so reading is all a staff admin can do. An organisation staff cannot read under RLS (only
listed ones are: not delisted, verification unclaimed, E1 or E2) shows its id alone.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.admin.deps import StaffAdmin
from bridge.auth.deps import Db
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.engagements.state_machine import due, end_of_day
from bridge.errors import ERROR_RESPONSES, not_found
from bridge.models.enums import (
    ClaimLevel,
    ClaimStatus,
    ModerationCaseStatus,
    ModerationSource,
    OrgKind,
    OrgVerification,
)

router = APIRouter(prefix="/api/admin/claims", tags=["admin"], responses=ERROR_RESPONSES)

ClaimView = Literal["review", "in_progress", "closed"]


# ------------------------------------------------------------------------------------------------------ the SLA


@dataclass(frozen=True, slots=True)
class ClaimsPolicy:
    """``review_sla_bd``: business days staff have to review a claim awaiting review (docs/spec/06 6.2: 2 BD)."""

    review_sla_bd: int


def parse_claims_policy(data: Any) -> ClaimsPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("claims")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'claims'")
    if set(section) != {"review_sla_bd"}:
        raise PolicyError(f"policy.yaml: claims must have exactly ['review_sla_bd'], got {sorted(section)}")
    value = section["review_sla_bd"]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
        raise PolicyError(f"policy.yaml: claims.review_sla_bd must be a whole number from 1 to 20, got {value!r}")
    return ClaimsPolicy(review_sla_bd=value)


def load_claims_policy(path: Path = POLICY_FILE) -> ClaimsPolicy:
    return parse_claims_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_claims_policy() -> ClaimsPolicy:
    """The process-wide claims policy (read once; a bad value stops the first request that needs it)."""
    return load_claims_policy()


class ClaimSla(BaseModel):
    due_on: date = Field(description="The last day of the review window (Nairobi); due by its end")
    business_days_left: int = Field(description="Kenyan business days from today to the due day; negative once late")
    overdue: bool


def review_sla(created_at: datetime, now: datetime, holidays: Collection[date], sla_bd: int) -> ClaimSla:
    """The review countdown of a claim submitted at ``created_at``: due at the end of the ``sla_bd``-th Kenyan business
    day after its Nairobi submission day (the tracker's convention, ``bridge.engagements.calendar``)."""
    deadline = end_of_day(add_business_days(local_date(created_at), sla_bd, holidays))
    countdown = due(deadline, now, holidays)
    return ClaimSla(due_on=countdown.due_on, business_days_left=countdown.business_days_left, overdue=countdown.overdue)


# ---------------------------------------------------------------------------------------------------- responses


class ClaimOrgOut(BaseModel):
    id: UUID
    legal_name: str | None = Field(description="Null when staff cannot read the organisation (it is not listed)")
    slug: str | None
    kind: OrgKind | None
    verification: OrgVerification | None


class PersonOut(BaseModel):
    id: UUID
    display_name: str


class ClaimOut(BaseModel):
    id: UUID
    org: ClaimOrgOut
    claimant: PersonOut
    domain: str
    level: ClaimLevel
    status: ClaimStatus
    created_at: datetime = Field(description="When the claim was submitted (the review SLA counts from here)")
    updated_at: datetime
    decided_at: datetime | None
    otp_verified: bool = Field(description="The domain-email code was confirmed")
    dns_verified: bool = Field(description="The DNS TXT record was found")
    sla: ClaimSla | None = Field(description="The review SLA of a claim awaiting review; null otherwise")
    dispute_case_id: UUID | None = Field(description="The open claim_dispute moderation case of a disputed claim")


class ClaimList(BaseModel):
    view: ClaimView
    review_sla_bd: int
    items: list[ClaimOut]


class OtherClaimOut(BaseModel):
    id: UUID
    claimant: PersonOut
    domain: str
    level: ClaimLevel
    status: ClaimStatus
    created_at: datetime


class ClaimCaseOut(BaseModel):
    id: UUID
    source: ModerationSource
    status: ModerationCaseStatus
    created_at: datetime


class ClaimDetailOut(ClaimOut):
    email_address: str = Field(description="The domain address the code went to")
    otp_verified_at: datetime | None
    dns_verified_at: datetime | None
    otp_attempts: int
    otp_reissues: int
    registration_no: str | None
    cr12_date: date | None
    kra_pin: str | None
    sector_register: str | None
    public_entity_requested: bool
    document_count: int = Field(description="Uploaded evidence documents (no download in the prototype)")
    official_domains: list[str] = Field(description="The organisation's official domains (listed from registers)")
    verified_domain: str | None
    domain_is_official: bool = Field(description="The claimed domain is one of the official domains")
    reviewed_by: PersonOut | None
    decision_reason: str | None
    other_claims: list[OtherClaimOut] = Field(description="The organisation's other open claims, oldest first")
    cases: list[ClaimCaseOut] = Field(description="Moderation cases about this claim, oldest first")


# ------------------------------------------------------------------------------------------------------ queries

_ITEM: Final = (
    "SELECT c.id, c.org_id, o.legal_name, CAST(o.slug AS text) AS slug, o.kind, o.verification, c.claimant_user_id,"
    " u.display_name AS claimant_name, CAST(c.domain AS text) AS domain, c.level, c.status, c.created_at,"
    " c.updated_at, c.decided_at,"
    " c.otp_verified_at, c.dns_verified_at,"
    " (SELECT m.id FROM moderation_cases m WHERE m.subject_type = 'org_claim' AND m.subject_id = c.id"
    " AND m.source = 'claim_dispute' AND m.status IN ('open', 'held', 'escalated')"
    " ORDER BY m.created_at, m.id LIMIT 1) AS dispute_case_id"
)
_FROM: Final = (
    " FROM org_claims c LEFT JOIN organizations o ON o.id = c.org_id JOIN users u ON u.id = c.claimant_user_id"
)
_DETAIL = text(
    _ITEM + ", CAST(c.email_address AS text) AS email_address, c.otp_attempts, c.otp_reissues, c.registration_no,"
    " c.cr12_date, c.kra_pin, c.sector_register, c.public_entity_requested,"
    " coalesce(cardinality(c.document_keys), 0) AS document_count,"
    " CAST(coalesce(o.official_domains, '{}') AS text[]) AS official_domains,"
    " CAST(o.verified_domain AS text) AS verified_domain,"
    " coalesce(c.domain = ANY (o.official_domains), false) AS domain_is_official,"
    " c.reviewed_by, r.display_name AS reviewer_name, c.decision_reason"
    + _FROM
    + " LEFT JOIN users r ON r.id = c.reviewed_by WHERE c.id = :id"
)
_OTHER_CLAIMS = text(
    "SELECT c.id, c.claimant_user_id, u.display_name AS claimant_name, CAST(c.domain AS text) AS domain, c.level,"
    " c.status, c.created_at"
    " FROM org_claims c JOIN users u ON u.id = c.claimant_user_id"
    " WHERE c.org_id = :org AND c.id <> :id AND c.status IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed')"
    " ORDER BY c.created_at, c.id"
)
_CASES = text(
    "SELECT id, source, status, created_at FROM moderation_cases"
    " WHERE subject_type = 'org_claim' AND subject_id = :id ORDER BY created_at, id"
)
_NOW = text("SELECT app_clock_now()")
_HOLIDAYS = text("SELECT observed_on FROM holidays WHERE country = 'KE' AND observed_on >= :since")


# Each view: its statuses and its order, at most 200 claims.
_VIEWS: Final[Mapping[ClaimView, TextClause]] = {
    "review": text(
        _ITEM + _FROM + " WHERE c.status IN ('pending_review', 'disputed') ORDER BY c.created_at, c.id LIMIT 200"
    ),
    "in_progress": text(
        _ITEM + _FROM + " WHERE c.status IN ('otp_sent', 'dns_pending') ORDER BY c.created_at DESC, c.id DESC LIMIT 200"
    ),
    "closed": text(
        _ITEM
        + _FROM
        + " WHERE c.status IN ('approved', 'rejected', 'withdrawn')"
        + " ORDER BY coalesce(c.decided_at, c.updated_at) DESC, c.id DESC LIMIT 200"
    ),
}


async def _sla_of(db: AsyncSession, rows: list[Any], policy: ClaimsPolicy) -> dict[UUID, ClaimSla]:
    """The review SLA of each claim awaiting review, on the shared clock and the Kenyan holiday calendar."""
    waiting = [row for row in rows if row.status == ClaimStatus.PENDING_REVIEW]
    if not waiting:
        return {}
    now: datetime = (await db.execute(_NOW)).scalar_one()
    since = min(local_date(row.created_at) for row in waiting)
    holidays = frozenset((await db.execute(_HOLIDAYS, {"since": since})).scalars().all())
    return {row.id: review_sla(row.created_at, now, holidays, policy.review_sla_bd) for row in waiting}


def _item(row: Any, sla: ClaimSla | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "org": ClaimOrgOut(
            id=row.org_id, legal_name=row.legal_name, slug=row.slug, kind=row.kind, verification=row.verification
        ),
        "claimant": PersonOut(id=row.claimant_user_id, display_name=row.claimant_name),
        "domain": row.domain,
        "level": row.level,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "decided_at": row.decided_at,
        "otp_verified": row.otp_verified_at is not None,
        "dns_verified": row.dns_verified_at is not None,
        "sla": sla,
        "dispute_case_id": row.dispute_case_id,
    }


# ------------------------------------------------------------------------------------------------------- routes


@router.get("")
async def list_claims(
    staff: StaffAdmin,
    db: Db,
    view: Annotated[ClaimView, Query(description="review (default), in_progress or closed")] = "review",
) -> ClaimList:
    policy = get_claims_policy()
    rows = list((await db.execute(_VIEWS[view])).all())
    slas = await _sla_of(db, rows, policy)
    return ClaimList(
        view=view,
        review_sla_bd=policy.review_sla_bd,
        items=[ClaimOut(**_item(row, slas.get(row.id))) for row in rows],
    )


@router.get("/{claim_id}")
async def get_claim(claim_id: UUID, staff: StaffAdmin, db: Db) -> ClaimDetailOut:
    row = (await db.execute(_DETAIL, {"id": claim_id})).one_or_none()
    if row is None:
        raise not_found("No such claim.")
    slas = await _sla_of(db, [row], get_claims_policy())
    others = (await db.execute(_OTHER_CLAIMS, {"org": row.org_id, "id": claim_id})).all()
    cases = (await db.execute(_CASES, {"id": claim_id})).all()
    return ClaimDetailOut(
        **_item(row, slas.get(row.id)),
        email_address=row.email_address,
        otp_verified_at=row.otp_verified_at,
        dns_verified_at=row.dns_verified_at,
        otp_attempts=row.otp_attempts,
        otp_reissues=row.otp_reissues,
        registration_no=row.registration_no,
        cr12_date=row.cr12_date,
        kra_pin=row.kra_pin,
        sector_register=row.sector_register,
        public_entity_requested=row.public_entity_requested,
        document_count=row.document_count,
        official_domains=list(row.official_domains),
        verified_domain=row.verified_domain,
        domain_is_official=row.domain_is_official,
        reviewed_by=None if row.reviewed_by is None else PersonOut(id=row.reviewed_by, display_name=row.reviewer_name),
        decision_reason=row.decision_reason,
        other_claims=[
            OtherClaimOut(
                id=other.id,
                claimant=PersonOut(id=other.claimant_user_id, display_name=other.claimant_name),
                domain=other.domain,
                level=other.level,
                status=other.status,
                created_at=other.created_at,
            )
            for other in others
        ],
        cases=[
            ClaimCaseOut(id=case.id, source=case.source, status=case.status, created_at=case.created_at)
            for case in cases
        ],
    )
