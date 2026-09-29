"""Matches API: the "Scout matches" tab and a match's page (REQ-SCOUT-02, REQ-SCOUT-03; docs/spec/06 6.8).

- ``GET /api/orgs/{org_id}/matches[?scout_id=]``: any member; newest first (at most 200).
- ``GET /api/orgs/{org_id}/matches/{id}``: any member; the match with its rules, the organisation's engagement for
  the proposal if one exists, and whether the caller may express interest now (and why not: ``org_not_e2``,
  ``org_unavailable`` (suspended or delisted), ``role_required``, ``engagement_exists``, ``proposal_unavailable``).
- ``POST /api/orgs/{org_id}/matches/{id}/feedback``: a member who acts on proposals (owner, admin, signatory or
  reviewer; else 403) marks it relevant or not relevant (with a reason code), as themselves. A feedback stays its
  author's: another member's answer is 409 ``feedback_given`` (the database's ``agent_matches_feedback_guard`` is
  the backstop).

Reads have no side effect (a digest link only opens a page: nothing changes on GET). Each match shows the proposal's
current teaser (Tier 1 only, through ``current_version_id``), or none once the proposal is no longer published and
clear (``available`` false: then no why and no rules either, since both quote or describe the teaser);
``demo_fallback`` is true when no model wrote the why.
"""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.deps import Db
from bridge.directory.service import niche_label
from bridge.errors import ERROR_RESPONSES, ApiError, forbidden, not_found
from bridge.matching.schemas import FeedbackIn, InterestState, MatchDetail, MatchList, MatchOut
from bridge.models.enums import OrgRole, OrgVerification
from bridge.proposals.schemas import NicheOut, TeaserOut
from bridge.tenancy.deps import OrgContext, OrgMember

router = APIRouter(tags=["scouts"], responses=ERROR_RESPONSES)
PREFIX: Final = "/api/orgs/{org_id}/matches"
ACTING: Final = frozenset({OrgRole.OWNER, OrgRole.ADMIN, OrgRole.SIGNATORY, OrgRole.REVIEWER})
LIST_LIMIT: Final = 200
_MATCHES: Final = (
    "SELECT m.id, m.scout_id, m.proposal_id, m.score, m.rationale, m.rationale_demo_fallback, m.injection_suspected,"
    " m.rule_breakdown, m.created_at, m.digest_sent_at, m.feedback, m.feedback_reason, (p.id IS NOT NULL) AS available,"
    " v.title, v.country, v.county_code, v.maturity, v.ask, v.problem_statement, v.impact_claims, v.summary,"
    " v.owner_handle, n.id AS niche_id, n.slug AS niche_slug, n.name_en AS niche_name, pn.name_en AS parent_name"
    " FROM agent_matches m"
    " LEFT JOIN proposals p ON p.id = m.proposal_id AND p.status = 'published' AND p.moderation_state = 'clear'"
    " LEFT JOIN proposal_versions v ON v.id = p.current_version_id"
    " LEFT JOIN niches n ON n.id = coalesce(v.niche_id, m.niche_id) LEFT JOIN niches pn ON pn.id = n.parent_id"
    " WHERE m.org_id = :org"
)
_ORG = text("SELECT verification, suspended_at, delisted_at FROM organizations WHERE id = :org")
_ENGAGEMENT = text("SELECT id FROM engagements WHERE proposal_id = :proposal AND org_id = :org")
_FEEDBACK_BY = text("SELECT feedback_by FROM agent_matches WHERE id = :id AND org_id = :org")
_FEEDBACK = text(
    "UPDATE agent_matches SET feedback = CAST(:feedback AS match_feedback), feedback_reason = :reason,"
    " feedback_by = :user, feedback_at = app_clock_now() WHERE id = :id AND org_id = :org"
)


def _out(row: Any) -> dict[str, Any]:
    niche = None
    if row.niche_id is not None:
        niche = NicheOut(id=row.niche_id, slug=row.niche_slug, label=niche_label(row.niche_name, row.parent_name))
    teaser = None
    if row.available:
        teaser = TeaserOut(
            title=row.title,
            niche=niche,
            country=row.country,
            county_code=row.county_code,
            maturity=row.maturity,
            ask=row.ask,
            problem_statement=row.problem_statement,
            impact_claims=row.impact_claims,
            summary=row.summary,
        )
    source = (row.rule_breakdown or {}).get("why_source")
    return {
        "id": row.id,
        "scout_id": row.scout_id,
        "proposal_id": row.proposal_id,
        "available": row.available,
        "owner_handle": row.owner_handle if row.available else None,
        "teaser": teaser,
        "niche": niche,
        "score": row.score,
        "why": row.rationale if row.available else None,
        "why_source": "model" if source == "model" and row.available else "code",
        "demo_fallback": row.rationale_demo_fallback,
        "injection_suspected": row.injection_suspected,
        "created_at": row.created_at,
        "digest_sent_at": row.digest_sent_at,
        "feedback": row.feedback,
        "feedback_reason": row.feedback_reason,
    }


async def _row(db: AsyncSession, org_id: UUID, match_id: UUID) -> Any:
    row = (await db.execute(text(f"{_MATCHES} AND m.id = :id"), {"org": org_id, "id": match_id})).one_or_none()
    if row is None:
        raise not_found("No match of your organisation has this id.")
    return row


async def interest_state(db: AsyncSession, org: OrgContext, proposal_id: UUID, available: bool) -> InterestState:
    """Express interest needs an E2 organisation that is not suspended, a signatory, no engagement yet and a
    published, clear proposal (docs/spec/06 6.8, 6.9 stage 0; the command checks all of it again)."""
    found = (await db.execute(_ORG, {"org": org.org_id})).one()
    engagement = (await db.execute(_ENGAGEMENT, {"proposal": proposal_id, "org": org.org_id})).scalar_one_or_none()
    reason = None
    if found.verification != OrgVerification.E2:
        reason = "org_not_e2"
    elif found.suspended_at is not None or found.delisted_at is not None:
        reason = "org_unavailable"
    elif OrgRole.SIGNATORY not in org.roles:
        reason = "role_required"
    elif engagement is not None:
        reason = "engagement_exists"
    elif not available:
        reason = "proposal_unavailable"
    return InterestState(allowed=reason is None, reason=reason)


async def _detail(db: AsyncSession, org: OrgContext, match_id: UUID) -> MatchDetail:
    row = await _row(db, org.org_id, match_id)
    engagement = (await db.execute(_ENGAGEMENT, {"proposal": row.proposal_id, "org": org.org_id})).scalar_one_or_none()
    return MatchDetail(
        **_out(row),
        rule_breakdown=dict(row.rule_breakdown or {}) if row.available else {},
        engagement_id=engagement,
        interest=await interest_state(db, org, row.proposal_id, row.available),
    )


@router.get(PREFIX)
async def list_matches(
    org: OrgMember, db: Db, scout_id: Annotated[UUID | None, Query(description="Only this scout's matches.")] = None
) -> MatchList:
    """The organisation's scout matches, newest first."""
    sql = _MATCHES + (" AND m.scout_id = :scout" if scout_id is not None else "")
    sql += " ORDER BY m.created_at DESC, m.id DESC LIMIT :limit"
    rows = (await db.execute(text(sql), {"org": org.org_id, "scout": scout_id, "limit": LIST_LIMIT})).all()
    return MatchList(items=[MatchOut(**_out(row)) for row in rows])


@router.get(f"{PREFIX}/{{match_id}}")
async def get_match(match_id: UUID, org: OrgMember, db: Db) -> MatchDetail:
    """One match: its teaser, niche label, score, why, rules and the Express interest state (read only)."""
    return await _detail(db, org, match_id)


@router.post(f"{PREFIX}/{{match_id}}/feedback")
async def match_feedback(match_id: UUID, body: FeedbackIn, org: OrgMember, db: Db) -> MatchDetail:
    """Relevant, or not relevant with a reason code (docs/spec/06 6.8 feedback), recorded as the caller."""
    await _row(db, org.org_id, match_id)  # 404 before 403: another organisation's match is not confirmed
    if not org.roles & ACTING:
        raise forbidden("role_required", "Only owners, admins, signatories and reviewers give feedback on matches.")
    given_by = (await db.execute(_FEEDBACK_BY, {"id": match_id, "org": org.org_id})).scalar_one_or_none()
    if given_by is not None and given_by != org.live.user.id:
        raise ApiError(409, "feedback_given", "Another member already gave feedback on this match.")
    params = {
        "feedback": body.feedback.value,
        "reason": body.reason,
        "user": org.live.user.id,
        "id": match_id,
        "org": org.org_id,
    }
    try:
        await db.execute(_FEEDBACK, params)
        await db.commit()
    except DBAPIError as exc:  # the guard: another member answered meanwhile
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "42501":
            raise
        raise ApiError(409, "feedback_given", "Another member already gave feedback on this match.") from exc
    return await _detail(db, org, match_id)
