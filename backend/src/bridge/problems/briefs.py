"""Problem Briefs (REQ-DIR-05; docs/spec/06 6.2 last bullet, 6.5, 6.12; plan limits docs/spec/05).

A verified organisation posts a Problem Brief: a ProblemCard (a ``problems`` row, ``source = org_brief``) with its own
``problem_briefs`` row (visibility, optional budget band and deadline). Plain code decides everything here:

- Who: the organisation's owner, admin, signatory or reviewer post, change and close (the RLS editor set); any member
  reads. Only an E2 (legally verified) organisation posts: anything else is 403 ``verification_required`` (the
  database refuses a published Brief of an organisation that is not E2 as well); a suspended or delisted one is 403
  ``org_unavailable`` (as an engagement's opening refuses it).
- How many: the plan's ``problem_briefs`` limit counts open Briefs (not closed, its deadline unset or not passed,
  its problem not rejected or archived), under a per-organisation advisory lock so parallel posts cannot pass it (402
  ``plan_limit``, the next plan up); and whatever the plan, at most ``briefs.daily_posts`` (policy.yaml) posts per
  organisation and Nairobi day, under the same lock (each files a moderation case; 429 ``briefs_daily_limit``).
- What: the text is public once approved, so it is cleaned to plain text, carries no contact details (the
  sanitiser's rule) and keeps the ProblemCard's lengths; the niche, county and budget band come from the lists; the
  deadline is today or later (Africa/Nairobi, on the platform clock). Refusals are 422 ``invalid_brief`` with a code
  per field, never quoting the text. ``invited`` is not available yet (422 ``visibility_not_available``).
- Review: the problem is inserted ``pending_review`` (held when the developer problems' pre-screen holds it) with its
  Brief as a ``draft``, and a moderation case is filed (``new_org_brief``). Staff approval (``app_moderate_problem``,
  revision 0006) publishes the problem and the draft Brief of an E2 organisation together; nothing here ever writes
  ``published``, and nothing of a draft is readable beyond the organisation and staff.
- Closing sets a published Brief ``closed`` (a draft is 409 ``brief_not_published``: revision 0006 closes only from
  ``published``): it leaves Discover and frees its plan slot; the problem stays published, and its page and the
  proposals' links to it stay readable. The moderated text of a published Brief never changes here (revision 0006
  refuses it with SQLSTATE 55000: 409 ``brief_frozen``).

The rules themselves (text, state, band) are ``bridge.problems.brief_rules``; developers read Briefs on Discover's
Briefs view (``bridge.matching.discover.briefs_view``) and on their problem page.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge import pagination
from bridge.audit.service import record as audit
from bridge.billing import entitlements
from bridge.config import Settings
from bridge.directory.models import Niche
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.matching.config import Weights, get_weights
from bridge.matching.schemas import BudgetBandOut
from bridge.models.enums import (
    BriefStatus,
    BriefVisibility,
    ModerationState,
    OrgVerification,
    ProblemStatus,
)
from bridge.problems import brief_rules
from bridge.problems import service as problems
from bridge.problems.brief_policy import get_briefs_policy
from bridge.problems.brief_schemas import BriefIn, BriefList, BriefOut, BriefPatch, BriefPlanOut
from bridge.problems.models import Problem, ProblemBrief
from bridge.proposals.prescreen import PreScreen, ScreenInput, listed_org_names
from bridge.proposals.sanitise import FieldError
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.models import Organization

PROBLEM_BRIEFS: Final = "problem_briefs"  # the plan limit (plans.yaml): open Briefs
NEW_BRIEF_REASON: Final = "new_org_brief"  # every Brief waits for staff review
# [[COPY-REVIEW]] the refusals' sentences (the field sentences are bridge.problems.brief_rules.MESSAGES).
NOT_VERIFIED: Final = "Only organisations with legal verification (E2) can post Problem Briefs."
NOT_AVAILABLE: Final = "Invited-only Briefs are not available yet. Post a public Brief."
DAILY_LIMIT: Final = "Your organisation has posted as many Briefs as it can today. Try again tomorrow."
UNAVAILABLE: Final = "Your organisation cannot post Problem Briefs while it is suspended or delisted."
CLOSED: Final = "This Brief is closed. Post a new one to ask again."
NOT_PUBLISHED: Final = "This Brief is still in review: it can be closed once it is published."
FROZEN: Final = "A published Brief keeps the text staff approved. Post a new Brief to change it."
NO_BRIEF: Final = "No Brief of your organisation has this id."

_NOW = text("SELECT app_clock_now()")
# One plan count at a time per organisation (as bridge.matching.scouts): released when the request commits or rolls
# back, so parallel posts cannot pass the plan's problem_briefs limit.
_PLAN_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
# Briefs the organisation posted since the start of today in Nairobi (the database clock, as problems.created_at).
_POSTED_TODAY = text(
    "SELECT count(*) FROM problems WHERE org_id = :org AND source = 'org_brief'"
    " AND created_at >= (date_trunc('day', now() AT TIME ZONE 'Africa/Nairobi') AT TIME ZONE 'Africa/Nairobi')"
)
_COUNTY = text("SELECT count(*) FROM regions WHERE code = :code AND kind = 'county'")
_OPEN_BRIEFS = text(
    "SELECT count(*) FROM problem_briefs b JOIN problems p ON p.id = b.problem_id"
    " WHERE b.org_id = :org AND b.status <> 'closed' AND (b.deadline IS NULL OR b.deadline >= :today)"
    " AND p.status IN ('pending_review', 'published')"
)
_INSERT_PROBLEM = text(
    "INSERT INTO problems (id, source, niche_id, county_code, title, statement, affected_group, status, created_by,"
    " org_id, moderation_state) VALUES (:id, 'org_brief', :niche, :county, :title, :statement, :affected,"
    " 'pending_review', :user, :org, CAST(:moderation AS moderation_state))"
)
_INSERT_BRIEF = text(
    "INSERT INTO problem_briefs (problem_id, org_id, visibility, budget_band, deadline, status)"
    " VALUES (:id, :org, 'public', :band, :deadline, 'draft')"
)
_LOCK_BRIEF = text("SELECT status FROM problem_briefs WHERE problem_id = :id AND org_id = :org FOR UPDATE")
_UPDATE_BRIEF = text(
    "UPDATE problem_briefs SET budget_band = CASE WHEN :set_band THEN CAST(:band AS varchar) ELSE budget_band END,"
    " deadline = CASE WHEN :set_deadline THEN CAST(:deadline AS date) ELSE deadline END, updated_at = now()"
    " WHERE problem_id = :id AND org_id = :org"
)
_CLOSE_BRIEF = text(
    "UPDATE problem_briefs SET status = 'closed', updated_at = now() WHERE problem_id = :id AND org_id = :org"
)
# Published, clear proposals whose current version links the problem (Discover's proposal_count rule).
_PROPOSAL_COUNTS = text(
    "SELECT pp.problem_id, count(DISTINCT p.id) AS n FROM proposal_problems pp"
    " JOIN proposals p ON p.current_version_id = pp.proposal_version_id"
    " WHERE pp.problem_id = ANY(:ids) AND p.status = 'published' AND p.moderation_state = 'clear'"
    " GROUP BY pp.problem_id"
)
_Parent = aliased(Niche)


# --- database ---------------------------------------------------------------------------------------------------------


async def today(db: AsyncSession) -> date:
    """Today in Africa/Nairobi on the platform clock (the dev/test clock where it is enabled)."""
    now: datetime = (await db.execute(_NOW)).scalar_one()
    return now.astimezone(problems.NAIROBI).date()


async def open_briefs(db: AsyncSession, org_id: UUID) -> int:
    """The organisation's open Briefs (the plan count): not closed, deadline unset or today or later (Africa/Nairobi,
    the platform clock), problem not rejected or archived."""
    params = {"org": org_id, "today": await today(db)}
    return int((await db.execute(_OPEN_BRIEFS, params)).scalar_one())


async def proposal_counts(db: AsyncSession, problem_ids: Iterable[UUID]) -> dict[UUID, int]:
    ids = list(problem_ids)
    if not ids:
        return {}
    return {row.problem_id: int(row.n) for row in (await db.execute(_PROPOSAL_COUNTS, {"ids": ids})).all()}


async def _choice_errors(
    db: AsyncSession,
    weights: Weights,
    *,
    niche_id: UUID | None = None,
    county_code: str | None = None,
    budget_band: str | None = None,
    deadline: date | None = None,
) -> list[FieldError]:
    errors = []
    known = select(func.count()).select_from(Niche).where(Niche.id == niche_id, Niche.active)
    if niche_id is not None and not await db.scalar(known):
        errors.append(brief_rules.error("niche_id", "unknown_niche"))
    if county_code is not None and not (await db.execute(_COUNTY, {"code": county_code})).scalar_one():
        errors.append(brief_rules.error("county_code", "unknown_county"))
    if budget_band is not None and weights.band(budget_band) is None:
        errors.append(brief_rules.error("budget_band", "unknown_budget_band"))
    if deadline is not None and deadline < await today(db):
        errors.append(brief_rules.error("deadline", "deadline_past"))
    return errors


async def _require_e2(db: AsyncSession, org_id: UUID) -> None:
    """403 unless the organisation is E2 (``verification_required``), and neither suspended nor delisted
    (``org_unavailable``; its members still read it under RLS)."""
    org = (
        await db.execute(
            select(Organization.verification, Organization.suspended_at, Organization.delisted_at).where(
                Organization.id == org_id
            )
        )
    ).one_or_none()
    if org is None or org.verification is not OrgVerification.E2:
        raise forbidden("verification_required", NOT_VERIFIED)
    if org.suspended_at is not None or org.delisted_at is not None:
        raise forbidden("org_unavailable", UNAVAILABLE)


def _db_refusal(exc: DBAPIError) -> ApiError | None:
    """The database's refusals of a Brief's transaction that the API words; anything else is raised as it is."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "55000":  # revision 0006's text guard: a published Brief keeps its moderated text
        return ApiError(409, "brief_frozen", FROZEN)
    if sqlstate in ("23503", "23514"):  # a niche or county gone meanwhile, or a CHECK: the form was checked first
        return brief_rules.invalid([])
    return None


async def _write_brief(db: AsyncSession, statement: Any, params: dict[str, Any]) -> None:
    """A write to ``problem_briefs``: its policies' E2 guard on a published Brief refuses an organisation that is no
    longer E2 (42501, checked first: a race) as ``verification_required``; only here is 42501 worded so."""
    try:
        await db.execute(statement, params)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != "42501":
            raise
        await db.rollback()
        raise forbidden("verification_required", NOT_VERIFIED) from exc


@asynccontextmanager
async def _writing(db: AsyncSession) -> AsyncIterator[None]:
    """Run the block's writes and commit; a refusal by the database rolls back and answers as the API does."""
    try:
        yield
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        mapped = _db_refusal(exc)
        if mapped is None:
            raise
        raise mapped from exc


def _select() -> Select[Any]:
    return (
        select(
            Problem.id,
            Problem.title,
            Problem.statement,
            Problem.affected_group,
            Problem.niche_id,
            Niche.slug.label("niche_slug"),
            Niche.name_en.label("niche_name"),
            _Parent.name_en.label("parent_name"),
            Problem.country,
            Problem.county_code,
            Problem.status.label("problem_status"),
            Problem.moderation_state,
            Problem.created_at,
            Problem.published_at,
            ProblemBrief.visibility,
            ProblemBrief.budget_band,
            ProblemBrief.deadline,
            ProblemBrief.status.label("brief_status"),
        )
        .join(ProblemBrief, ProblemBrief.problem_id == Problem.id)
        .outerjoin(Niche, Niche.id == Problem.niche_id)
        .outerjoin(_Parent, _Parent.id == Niche.parent_id)
    )


def _out(row: Any, proposal_count: int, weights: Weights) -> BriefOut:
    status = BriefStatus(row.brief_status)
    problem_status, moderation = ProblemStatus(row.problem_status), ModerationState(row.moderation_state)
    return BriefOut(
        id=row.id,
        title=row.title,
        statement=row.statement,
        affected_group=row.affected_group,
        niche=problems.niche_out(row.niche_id, row.niche_slug, row.niche_name, row.parent_name),
        country=row.country,
        county_code=row.county_code,
        visibility=row.visibility,
        budget_band=brief_rules.band_out(row.budget_band, weights),
        deadline=row.deadline,
        status=status,
        problem_status=problem_status,
        moderation_state=moderation,
        state=brief_rules.brief_state(status, problem_status, moderation),
        proposal_count=proposal_count,
        created_at=row.created_at,
        published_at=row.published_at if problem_status is ProblemStatus.PUBLISHED else None,
    )


# --- the organisation's Briefs ----------------------------------------------------------------------------------------


async def get_one(db: AsyncSession, org_id: UUID, problem_id: UUID) -> BriefOut:
    row = (await db.execute(_select().where(Problem.id == problem_id, ProblemBrief.org_id == org_id))).one_or_none()
    if row is None:
        raise not_found(NO_BRIEF)
    counts = await proposal_counts(db, [row.id])
    return _out(row, counts.get(row.id, 0), get_weights())


async def list_briefs(
    db: AsyncSession, settings: Settings, org_id: UUID, *, limit: int, after: pagination.MomentCursor | None
) -> BriefList:
    """The organisation's Briefs, newest first (every status), what its plan allows and the budget band codes."""
    stmt = _select().where(ProblemBrief.org_id == org_id)
    if after is not None:
        if after.at is None:  # this list's cursors always carry a moment
            raise pagination.invalid_cursor()
        same = and_(Problem.created_at == after.at, Problem.id < after.id)
        stmt = stmt.where(or_(Problem.created_at < after.at, same))
    rows = (await db.execute(stmt.order_by(Problem.created_at.desc(), Problem.id.desc()).limit(limit + 1))).all()
    page, weights = rows[:limit], get_weights()
    counts = await proposal_counts(db, [row.id for row in page])
    ent = await entitlements.for_subject(db, settings, org_id=org_id)
    last = page[-1] if len(rows) > limit else None
    return BriefList(
        items=[_out(row, counts.get(row.id, 0), weights) for row in page],
        next_cursor=None if last is None else pagination.encode(last.created_at, last.id),
        plan=BriefPlanOut(
            plan=ent.plan_code, problem_briefs=ent.limit(PROBLEM_BRIEFS), used=await open_briefs(db, org_id)
        ),
        budget_bands=[BudgetBandOut(code=b.code, label=b.label) for b in weights.budget_bands],
    )


async def create(
    db: AsyncSession, settings: Settings, prescreen: PreScreen, org: OrgContext, body: BriefIn
) -> BriefOut:
    """Post a Brief: 403 unless E2 (and neither suspended nor delisted), 422 for an invited one, 402 beyond the plan,
    429 beyond today's posts, 422 for the form; then the problem (pending review), the draft Brief, its moderation
    case and the audit event in one transaction."""
    await _require_e2(db, org.org_id)
    if body.visibility is not BriefVisibility.PUBLIC:
        raise ApiError(422, "visibility_not_available", NOT_AVAILABLE)
    ent = await entitlements.for_subject(db, settings, org_id=org.org_id)
    await db.execute(_PLAN_LOCK, {"key": f"briefs.plan:{org.org_id}"})
    entitlements.check_count(settings, ent, PROBLEM_BRIEFS, used=await open_briefs(db, org.org_id))
    if (await db.execute(_POSTED_TODAY, {"org": org.org_id})).scalar_one() >= get_briefs_policy().daily_posts:
        raise ApiError(429, "briefs_daily_limit", DAILY_LIMIT)
    weights = get_weights()
    cleaned, errors = brief_rules.text_errors(
        {"title": body.title, "statement": body.statement, "affected_group": body.affected_group}
    )
    errors += await _choice_errors(
        db,
        weights,
        niche_id=body.niche_id,
        county_code=body.county_code,
        budget_band=body.budget_band,
        deadline=body.deadline,
    )
    if errors:
        raise brief_rules.invalid(errors)
    screened = {name: value for name, value in cleaned.items() if value}
    screen = await prescreen.screen(ScreenInput(screened, await listed_org_names(db)))
    moderation = ModerationState.HELD if screen.hold else ModerationState.CLEAR
    problem_id = uuid7()
    async with _writing(db):
        await db.execute(
            _INSERT_PROBLEM,
            {
                "id": problem_id,
                "niche": body.niche_id,
                "county": body.county_code,
                "title": cleaned["title"],
                "statement": cleaned["statement"],
                "affected": cleaned["affected_group"],
                "user": org.live.user.id,
                "org": org.org_id,
                "moderation": moderation.value,
            },
        )
        brief = {"id": problem_id, "org": org.org_id, "band": body.budget_band, "deadline": body.deadline}
        await _write_brief(db, _INSERT_BRIEF, brief)
        classifier = None if screen.classifier is None else json.dumps(screen.classifier)
        await problems.open_case(db, "problem", problem_id, [NEW_BRIEF_REASON, *screen.reasons], classifier)
        await audit(
            db,
            "brief.created",
            actor_user_id=org.live.user.id,
            org_id=org.org_id,
            subject_type="problem",
            subject_id=problem_id,
            payload={"visibility": BriefVisibility.PUBLIC.value, "moderation_state": moderation.value},
        )
    return await get_one(db, org.org_id, problem_id)


async def _locked_status(db: AsyncSession, org_id: UUID, problem_id: UUID) -> BriefStatus:
    status = (await db.execute(_LOCK_BRIEF, {"id": problem_id, "org": org_id})).scalar_one_or_none()
    if status is None:
        raise not_found(NO_BRIEF)
    return BriefStatus(status)


async def update(db: AsyncSession, org: OrgContext, problem_id: UUID, body: BriefPatch) -> BriefOut:
    """Change the budget band or deadline (``null`` clears it) of a Brief that is not closed (409 ``brief_closed``)."""
    changes = body.model_dump(exclude_unset=True)
    if await _locked_status(db, org.org_id, problem_id) is BriefStatus.CLOSED:
        raise ApiError(409, "brief_closed", CLOSED)
    errors = await _choice_errors(
        db, get_weights(), budget_band=changes.get("budget_band"), deadline=changes.get("deadline")
    )
    if errors:
        raise brief_rules.invalid(errors)
    if changes:
        params = {
            "id": problem_id,
            "org": org.org_id,
            "set_band": "budget_band" in changes,
            "band": changes.get("budget_band"),
            "set_deadline": "deadline" in changes,
            "deadline": changes.get("deadline"),
        }
        async with _writing(db):
            await _write_brief(db, _UPDATE_BRIEF, params)
            await audit(
                db,
                "brief.updated",
                actor_user_id=org.live.user.id,
                org_id=org.org_id,
                subject_type="problem",
                subject_id=problem_id,
                payload={"fields": sorted(changes)},
            )
    return await get_one(db, org.org_id, problem_id)


async def close(db: AsyncSession, org: OrgContext, problem_id: UUID) -> BriefOut:
    """Close a published Brief (closing a closed one changes nothing; a draft is 409 ``brief_not_published``): off
    Discover, its plan slot freed, its page kept."""
    status = await _locked_status(db, org.org_id, problem_id)
    if status is BriefStatus.DRAFT:
        raise ApiError(409, "brief_not_published", NOT_PUBLISHED)
    if status is not BriefStatus.CLOSED:
        async with _writing(db):
            await _write_brief(db, _CLOSE_BRIEF, {"id": problem_id, "org": org.org_id})
            await audit(
                db,
                "brief.closed",
                actor_user_id=org.live.user.id,
                org_id=org.org_id,
                subject_type="problem",
                subject_id=problem_id,
                payload={},
            )
    return await get_one(db, org.org_id, problem_id)
