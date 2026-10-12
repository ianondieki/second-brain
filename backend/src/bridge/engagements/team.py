"""Team triage (REQ-ENG-15, D-68; docs/spec/03: the ``reviewer`` "may Recommend internally without changing state").

An organisation assigns each engagement to one of its members and its members record internal recommendations
(pursue, pass or discuss, with an optional one-line note). Both are the organisation's own data (revision 0013:
org-scoped tables, read and written by its members only): they appear on organisation-side responses only
(``TeamFacts`` on the organisation's list, its tracker detail, its Inbox and its pipeline; ``TeamOut``, the team sheet)
and never on a developer's. Neither changes the engagement's state; only the tracker's commands do.

- **Assign** (``PUT …/assignee``): an owner, admin, reviewer or signatory (403 ``role_not_allowed`` otherwise, checked
  before any write) assigns an owner, admin, reviewer or signatory of the organisation (422 ``invalid_assignee``), or
  nobody (``user_id`` null); the same assignee again is 409 ``unchanged``. The engagement's own developer is never
  assignable, even as a member (422 ``invalid_assignee``, before any write: N30 would tell them the organisation's
  triage of their own proposal, D-68), and never on the team sheet's roster. The database's backstop for this (an
  assignee-is-not-the-developer clause in ``engagement_assignments_guard``) is for the next revision; until then the
  API's check is the only one. The live row is closed (the database stamps ``unassigned_at``) and the next inserted in
  one transaction; a concurrent assignment loses on the partial unique index (409). The assignee is told (N30, in-app)
  unless they assigned themselves. Each member changes an organisation's assignments at most ``ASSIGNMENTS_PER_HOUR``
  times in any hour (429 ``too_many_assignments`` with ``Retry-After``, after the role check and before any write; the
  ``login_attempts`` ledger, keyed by an HMAC of the organisation and the member): flipping the assignee between a
  colleague and nobody would otherwise append rows, audit rows and N30s without bound. A refused change is not counted.
- **Recommend** (``PUT …/recommendation``): the same roles; one row per member, upserted; an empty note is none
  (NULL); a note of exactly ``NOTE_REDACTED`` (D-54's marker of a redaction) is refused (422 ``invalid_note``).
  **Withdraw** (``DELETE …/recommendation``): any member removes their own.
- Each assignment and recommendation change appends an ``audit_events`` row on the organisation's chain: ids and the
  stance only. A note is never in an audit row, an event payload, a log line, a notice or an email.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.audit.service import record as audit
from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements.models import (
    NOTE_REDACTED,
    RECOMMENDATION_NOTE_MAX_CHARS,
    TRIAGE_ROLES,
    Engagement,
    EngagementAssignment,
    EngagementRecommendation,
)
from bridge.engagements.plain import one_line
from bridge.engagements.schemas import (
    EngagementSummary,
    MyRecommendationOut,
    OrgEngagementSummary,
    RecommendationBody,
    RecommendationOut,
    StanceCounts,
    TeamFacts,
    TeamMemberOut,
    TeamOut,
    TeamPerson,
)
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import EngagementParty, MembershipStatus, OrgRole, RecommendationStance
from bridge.notifications import em2
from bridge.notifications.in_app import MAX_TITLE_CHARS, post_in_app
from bridge.proposals.models import ProposalVersion
from bridge.teams import limits
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.models import Membership
from bridge.web_paths import engagement_path

TRIAGE: Final = frozenset(TRIAGE_ROLES)
# The one role the team sheet names a member by.
ROLE_ORDER: Final = (OrgRole.OWNER, OrgRole.ADMIN, OrgRole.SIGNATORY, OrgRole.REVIEWER)
N30: Final = "engagement.n30"
ASSIGNMENTS_PER_HOUR: Final = 30  # assignee changes per member and organisation in any hour
ASSIGNMENT_WINDOW: Final = timedelta(hours=1)
ASSIGNMENT_PURPOSE: Final = "engagement_assignment"  # the ledger's purpose label (with the organisation's id)
FORMER_MEMBER: Final = "Former member"  # [[COPY-REVIEW]] a member whose name the caller can no longer read (history's)
# [[COPY-REVIEW]] the API's refusals (the web app shows its own words) and N30's lines.
ROLE_NOT_ALLOWED: Final = "Only an owner, admin, reviewer or signatory assigns engagements and recommends."
INVALID_ASSIGNEE: Final = "Assign an owner, admin, reviewer or signatory of this organisation."
BOTH_PARTIES: Final = "This is your own proposal's engagement, so the organisation's team sheet is not yours to see."
UNCHANGED: Final = "The engagement is already assigned that way."
ASSIGN_RACE: Final = "Someone assigned this engagement at the same moment. Reload and try again."
RECOMMEND_RACE: Final = "Your recommendation changed at the same moment. Reload and try again."
INVALID_NOTE: Final = f"Write the note on one line, at most {RECOMMENDATION_NOTE_MAX_CHARS} characters."
ASSIGNED_TITLE: Final = '{who} assigned you "{title}"'
ASSIGNED_BODY: Final = "It is in your Assigned to me list. Open the tracker to pick it up."
SOME_PROPOSAL: Final = "a proposal"
TOO_MANY_ASSIGNMENTS: Final = "You have changed assignments many times this hour. Try again later."

log = get_logger(__name__)


def require_triage(org: OrgContext) -> None:
    """403 ``role_not_allowed`` unless the caller is an owner, admin, reviewer or signatory of the organisation."""
    if not org.roles & TRIAGE:
        raise forbidden("role_not_allowed", ROLE_NOT_ALLOWED)


async def org_engagement(db: AsyncSession, org_id: UUID, engagement_id: UUID, caller_id: UUID) -> Engagement:
    """The organisation's engagement (read under the member's RLS), or 404: another organisation's, or none; 403
    ``both_parties`` for its own developer, who never reads the organisation's triage even as a member of it (the
    security review of revision 0013)."""
    found: Engagement | None = await db.scalar(
        select(Engagement).where(Engagement.id == engagement_id, Engagement.org_id == org_id)
    )
    if found is None:
        raise not_found()
    if found.developer_id == caller_id:
        raise forbidden("both_parties", BOTH_PARTIES)
    return found


# ------------------------------------------------------------------------------------------------------------ reads


async def team_facts(
    db: AsyncSession, org_id: UUID, engagement_ids: Sequence[UUID], viewer_id: UUID
) -> dict[UUID, TeamFacts]:
    """The triage of each of ``engagement_ids`` as ``viewer_id``, a member of ``org_id``, reads it: three statements
    however many engagements (the lists, P16-E1). An engagement whose developer is ``viewer_id`` (a developer who is
    also a member of the organisation) gets none: they never read the organisation's triage of their own proposal."""
    if not engagement_ids:
        return {}
    found = await db.scalars(
        select(Engagement.id).where(
            Engagement.id.in_(list(engagement_ids)),
            Engagement.org_id == org_id,
            Engagement.developer_id != viewer_id,
        )
    )
    ids = list(found.all())
    if not ids:
        return {}
    assignees = await _assignees(db, org_id, ids)
    r = EngagementRecommendation
    rows = await db.execute(
        select(r.engagement_id, r.member_user_id, r.stance, r.note).where(r.org_id == org_id, r.engagement_id.in_(ids))
    )
    counts: dict[UUID, dict[RecommendationStance, int]] = defaultdict(lambda: dict.fromkeys(RecommendationStance, 0))
    mine: dict[UUID, MyRecommendationOut] = {}
    for eid, member, stance, note in rows.tuples():
        counts[eid][stance] += 1
        if member == viewer_id:
            mine[eid] = MyRecommendationOut(stance=stance, note=note)
    return {
        eid: TeamFacts(assignee=assignees.get(eid), recommendations=_tally(counts[eid]), mine=mine.get(eid))
        for eid in ids
    }


async def _assignees(db: AsyncSession, org_id: UUID, ids: Sequence[UUID]) -> dict[UUID, TeamPerson]:
    """The live assignee of each engagement that has one, with their name ("Former member" once unreadable)."""
    a = EngagementAssignment
    live = await db.execute(
        select(a.engagement_id, a.assignee_user_id, User.display_name)
        .outerjoin(User, User.id == a.assignee_user_id)
        .where(a.org_id == org_id, a.engagement_id.in_(list(ids)), a.unassigned_at.is_(None))
    )
    return {eid: TeamPerson(user_id=uid, display_name=name or FORMER_MEMBER) for eid, uid, name in live.tuples()}


async def with_team(
    db: AsyncSession, org_id: UUID, viewer_id: UUID, summaries: Sequence[EngagementSummary]
) -> list[OrgEngagementSummary]:
    """The organisation's list items: each summary with its triage (``team_facts``: constant statements)."""
    # TODO(P27 merge of wt/p27be1): the pipeline fills PipelineItem.team from team_facts(db, org, ids, viewer) too.
    facts = await team_facts(db, org_id, [item.id for item in summaries], viewer_id)
    return [OrgEngagementSummary(**item.model_dump(), team=facts.get(item.id)) for item in summaries]


def _tally(counts: dict[RecommendationStance, int]) -> StanceCounts:
    return StanceCounts(
        pursue=counts[RecommendationStance.PURSUE],
        pass_=counts[RecommendationStance.PASS],
        discuss=counts[RecommendationStance.DISCUSS],
    )


def first_role(roles: Iterable[OrgRole]) -> OrgRole | None:
    held = set(roles)
    return next((role for role in ROLE_ORDER if role in held), None)


async def team_view(db: AsyncSession, org_id: UUID, engagement: Engagement) -> TeamOut:
    """The team sheet: the members the engagement may be assigned to (never its own developer, a member or not), its
    assignee and every recommendation."""
    engagement_id = engagement.id
    members = await db.execute(
        select(Membership.user_id, Membership.roles, User.display_name)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.org_id == org_id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.user_id != engagement.developer_id,
        )
        .order_by(User.display_name, Membership.user_id)
    )
    roster = []
    for user_id, roles, name in members.tuples():
        role = first_role(OrgRole(r) for r in roles)
        if role is not None:
            roster.append(TeamMemberOut(user_id=user_id, display_name=name, role=role))
    r = EngagementRecommendation
    rows = await db.execute(
        select(r.member_user_id, User.display_name, r.stance, r.note, r.updated_at)
        .outerjoin(User, User.id == r.member_user_id)
        .where(r.org_id == org_id, r.engagement_id == engagement_id)
        .order_by(r.updated_at.desc(), r.id)
    )
    recommendations = [
        RecommendationOut(user_id=user, display_name=name or FORMER_MEMBER, stance=stance, note=note, updated_at=at)
        for user, name, stance, note, at in rows.tuples()
    ]
    assignee = (await _assignees(db, org_id, [engagement_id])).get(engagement_id)
    return TeamOut(engagement_id=engagement_id, members=roster, assignee=assignee, recommendations=recommendations)


# ----------------------------------------------------------------------------------------------------------- writes


@dataclass(frozen=True, slots=True)
class Assigned:
    """What the router tells the assignee after the commit (N30): nothing when nobody new was assigned or the caller
    assigned themselves."""

    team: TeamOut
    assignment_id: UUID | None
    assignee_id: UUID | None
    title: str


async def _live_assignee(db: AsyncSession, engagement_id: UUID) -> UUID | None:
    found: UUID | None = await db.scalar(
        select(EngagementAssignment.assignee_user_id).where(
            EngagementAssignment.engagement_id == engagement_id, EngagementAssignment.unassigned_at.is_(None)
        )
    )
    return found


async def _is_triage_member(db: AsyncSession, org_id: UUID, user_id: UUID) -> bool:
    roles = await db.scalar(
        select(Membership.roles).where(
            Membership.org_id == org_id, Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE
        )
    )
    return roles is not None and bool(set(roles) & TRIAGE)


def _refusal(exc: DBAPIError, *, check: ApiError, unique: ApiError) -> ApiError:
    """The database's backstop, in the API's words (the checks above run first, so these are races): a guard's
    check_violation ``check``, an RLS refusal 403, a lost race on a unique key ``unique``. Anything else is a bug:
    re-raised."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "23514":
        return check
    if sqlstate == "42501":
        return forbidden("role_not_allowed", ROLE_NOT_ALLOWED)
    if sqlstate in ("23505", "40001", "40P01"):
        return unique
    raise exc


async def spend_assignment(db: AsyncSession, settings: Settings, org: OrgContext) -> None:
    """Count one assignee change by the caller in the organisation, or 429 ``too_many_assignments`` (with
    ``Retry-After``) when ``ASSIGNMENTS_PER_HOUR`` of them fall within the last hour. The record joins the caller's
    transaction: committed with the change, rolled back with a refused one."""
    await limits.spend(
        db,
        settings.secret_key.get_secret_value(),
        purpose=f"{ASSIGNMENT_PURPOSE}:{org.org_id}",
        user_id=org.live.user.id,
        limit=ASSIGNMENTS_PER_HOUR,
        window=ASSIGNMENT_WINDOW,
        code="too_many_assignments",
        message=TOO_MANY_ASSIGNMENTS,
    )


async def assign(
    db: AsyncSession, settings: Settings, org: OrgContext, engagement_id: UUID, user_id: UUID | None
) -> Assigned:
    """Assign the engagement to ``user_id`` (None: nobody), in the caller's transaction (the router commits)."""
    require_triage(org)
    await spend_assignment(db, settings, org)
    engagement = await org_engagement(db, org.org_id, engagement_id, org.live.user.id)
    if user_id is not None and user_id == engagement.developer_id:  # D-68: never their own proposal's triage
        raise ApiError(422, "invalid_assignee", INVALID_ASSIGNEE)
    if await _live_assignee(db, engagement.id) == user_id:
        raise ApiError(409, "unchanged", UNCHANGED)
    if user_id is not None and not await _is_triage_member(db, org.org_id, user_id):
        raise ApiError(422, "invalid_assignee", INVALID_ASSIGNEE)
    assignment_id = uuid7() if user_id is not None else None
    try:
        await db.execute(  # the database stamps unassigned_at with the shared clock, whatever is sent
            update(EngagementAssignment)
            .where(EngagementAssignment.engagement_id == engagement.id, EngagementAssignment.unassigned_at.is_(None))
            .values(unassigned_at=func.now())
        )
        if user_id is not None:
            await db.execute(
                insert(EngagementAssignment).values(
                    id=assignment_id,
                    engagement_id=engagement.id,
                    org_id=org.org_id,
                    assignee_user_id=user_id,
                    assigned_by=org.live.user.id,
                )
            )
    except DBAPIError as exc:
        invalid = ApiError(422, "invalid_assignee", INVALID_ASSIGNEE)
        raise _refusal(exc, check=invalid, unique=ApiError(409, "conflict", ASSIGN_RACE)) from exc
    await audit(
        db,
        "engagement.assigned",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="engagement",
        subject_id=engagement.id,
        payload={
            "engagement_id": str(engagement.id),
            "assignment_id": str(assignment_id) if assignment_id else None,
            "assignee_user_id": str(user_id) if user_id else None,
        },
    )
    title = await db.scalar(select(ProposalVersion.title).where(ProposalVersion.id == engagement.version_id))
    told = user_id if user_id is not None and user_id != org.live.user.id else None
    team = await team_view(db, org.org_id, engagement)
    return Assigned(team=team, assignment_id=assignment_id, assignee_id=told, title=title or SOME_PROPOSAL)


async def recommend(db: AsyncSession, org: OrgContext, engagement_id: UUID, body: RecommendationBody) -> TeamOut:
    """Record (or change) the caller's recommendation, in the caller's transaction (the router commits)."""
    require_triage(org)
    engagement = await org_engagement(db, org.org_id, engagement_id, org.live.user.id)
    try:
        note = one_line(body.note, RECOMMENDATION_NOTE_MAX_CHARS)
    except ValueError as exc:
        raise ApiError(422, "invalid_note", INVALID_NOTE) from exc
    if note == NOTE_REDACTED:  # D-54's marker of a redaction: never a member's words
        raise ApiError(422, "invalid_note", INVALID_NOTE)
    r = EngagementRecommendation
    mine = (r.engagement_id == engagement.id, r.member_user_id == org.live.user.id)
    current = (await db.execute(select(r.stance, r.note).where(*mine))).first()
    if current is None or tuple(current) != (body.stance, note):
        statement = pg_insert(r).values(
            id=uuid7(),
            engagement_id=engagement.id,
            org_id=org.org_id,
            member_user_id=org.live.user.id,
            stance=body.stance,
            note=note,  # NULL for none: a blank note fails the CHECK
        )
        statement = statement.on_conflict_do_update(
            index_elements=[r.engagement_id, r.member_user_id],
            set_={"stance": statement.excluded.stance, "note": statement.excluded.note},
        )
        try:
            await db.execute(statement)
        except DBAPIError as exc:
            refused = forbidden("role_not_allowed", ROLE_NOT_ALLOWED)  # the guard: no longer a triage member
            raise _refusal(exc, check=refused, unique=ApiError(409, "conflict", RECOMMEND_RACE)) from exc
        await audit(
            db,
            "engagement.recommended",
            actor_user_id=org.live.user.id,
            org_id=org.org_id,
            subject_type="engagement",
            subject_id=engagement.id,
            payload={"engagement_id": str(engagement.id), "stance": body.stance.value},
        )
    return await team_view(db, org.org_id, engagement)


async def withdraw(db: AsyncSession, org: OrgContext, engagement_id: UUID) -> TeamOut:
    """Remove the caller's own recommendation (any member; nothing to remove is no change)."""
    engagement = await org_engagement(db, org.org_id, engagement_id, org.live.user.id)
    r = EngagementRecommendation
    removed = await db.execute(
        delete(r).where(r.engagement_id == engagement.id, r.member_user_id == org.live.user.id).returning(r.id)
    )
    if removed.first() is not None:
        await audit(
            db,
            "engagement.recommendation_withdrawn",
            actor_user_id=org.live.user.id,
            org_id=org.org_id,
            subject_type="engagement",
            subject_id=engagement.id,
            payload={"engagement_id": str(engagement.id)},
        )
    return await team_view(db, org.org_id, engagement)


# ------------------------------------------------------------------------------------------------------------ N30


def assigned_title(who: str, title: str) -> str:
    """N30's title, cut to the bell's 200 characters by shortening the proposal's title."""
    who, title = em2.one_line(who), em2.one_line(title)
    full = ASSIGNED_TITLE.format(who=who, title=title)
    if len(full) <= MAX_TITLE_CHARS:
        return full
    room = max(MAX_TITLE_CHARS - len(ASSIGNED_TITLE.format(who=who, title="")) - 1, 0)
    return ASSIGNED_TITLE.format(who=who, title=title[:room] + "…")[:MAX_TITLE_CHARS]


async def tell_assignee(
    factory: async_sessionmaker[AsyncSession],
    *,
    assigned: Assigned,
    org_id: UUID,
    engagement_id: UUID,
    assigner_name: str,
) -> bool:
    """N30 to the new assignee (in-app), after the assignment committed, in a session bound to them; once per
    assignment (dedupe ``n30:<assignment>``). Never raises: a notice never undoes what it tells."""
    if assigned.assignee_id is None or assigned.assignment_id is None:
        return False
    try:
        async with factory() as db:
            await bind_tenant(db, user_id=assigned.assignee_id, org_id=org_id)
            wrote = await post_in_app(
                db,
                user_id=assigned.assignee_id,
                org_id=org_id,
                kind=N30,
                title=assigned_title(assigner_name, assigned.title),
                body=ASSIGNED_BODY,
                link=engagement_path(EngagementParty.ORG, engagement_id),
                dedupe_key=f"n30:{assigned.assignment_id}",
            )
            await db.commit()
            return wrote
    except Exception as exc:  # a notice never undoes what it tells
        log.error("engagement.n30_failed", user_id=str(assigned.assignee_id), error_type=type(exc).__name__)
        return False
