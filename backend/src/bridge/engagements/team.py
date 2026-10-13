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
- **Niche defaults** (REQ-TEN-02, P28 track C; ``assign_niche_default``): a new engagement in ``SUBMITTED`` or
  ``ORG_INTEREST`` that has never been assigned goes to the organisation's default reviewer for its version's niche
  (else the niche's parent's), through this module's insert, in a session bound to a triage member of the
  organisation (``assigned_by``, the INSERT policy's writer). Never over an assignment (live or closed: someone chose),
  never to the engagement's own developer, and never to a member who no longer holds a triage role. Audited as a
  system event (the rule assigned it, ``reason: niche_default``); the assignee is told (N30) unless they are the
  member whose action opened the engagement. Hooked where an engagement opens: an organisation member's interest
  (``ORG_INTEREST``, in the signatory's transaction: ``bridge.engagements.interest_router``) and a Pitch (``SUBMITTED``,
  opened in the developer's session, which reads none of the organisation's rows: after the commit,
  ``apply_niche_defaults`` asks ``app_niche_default_assignee`` and binds the member it names).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.audit.service import record as audit
from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant, tenant_of
from bridge.directory.models import Niche
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
from bridge.models.enums import (
    AuditActor,
    EngagementParty,
    EngagementState,
    MembershipStatus,
    OrgRole,
    RecommendationStance,
)
from bridge.notifications import em2
from bridge.notifications.in_app import MAX_TITLE_CHARS, post_in_app
from bridge.proposals.models import ProposalVersion
from bridge.teams import limits
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.models import Membership, OrgNicheDefault
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
# [[COPY-REVIEW]] N30's lines for an assignment by the organisation's niche default (REQ-TEN-02).
DEFAULT_TITLE: Final = 'Assigned to you as the niche\'s default reviewer: "{title}"'
DEFAULT_BODY: Final = "A new engagement in a niche you cover. Open the tracker to pick it up."
DEFAULT_STATES: Final = frozenset({EngagementState.SUBMITTED, EngagementState.ORG_INTEREST})
_DEFAULT_ASSIGNEE: Final = text("SELECT app_niche_default_assignee(:engagement)")  # revision 0015's definer

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
    """The organisation's list items: each summary with its triage (``team_facts``: constant statements).
    ``PipelineItem.team`` is filled by ``with_team`` at the merge with the pipeline (P27 card, contract B:
    docs/platform/tasks/P27.md)."""
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


async def _post_n30(
    factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    org_id: UUID,
    engagement_id: UUID,
    assignment_id: UUID,
    title: str,
    body: str,
) -> bool:
    """N30 (in-app) to ``user_id``, after the assignment committed, in a session bound to them; once per assignment
    (dedupe ``n30:<assignment>``). Never raises: a notice never undoes what it tells."""
    try:
        async with factory() as db:
            await bind_tenant(db, user_id=user_id, org_id=org_id)
            wrote = await post_in_app(
                db,
                user_id=user_id,
                org_id=org_id,
                kind=N30,
                title=title,
                body=body,
                link=engagement_path(EngagementParty.ORG, engagement_id),
                dedupe_key=f"n30:{assignment_id}",
            )
            await db.commit()
            return wrote
    except Exception as exc:  # a notice never undoes what it tells
        log.error("engagement.n30_failed", user_id=str(user_id), error_type=type(exc).__name__)
        return False


async def tell_assignee(
    factory: async_sessionmaker[AsyncSession],
    *,
    assigned: Assigned,
    org_id: UUID,
    engagement_id: UUID,
    assigner_name: str,
) -> bool:
    """N30 to the new assignee (in-app), after the assignment committed (``_post_n30``)."""
    if assigned.assignee_id is None or assigned.assignment_id is None:
        return False
    return await _post_n30(
        factory,
        user_id=assigned.assignee_id,
        org_id=org_id,
        engagement_id=engagement_id,
        assignment_id=assigned.assignment_id,
        title=assigned_title(assigner_name, assigned.title),
        body=ASSIGNED_BODY,
    )


# ---------------------------------------------------------------------------------------- niche defaults (REQ-TEN-02)


@dataclass(frozen=True, slots=True)
class DefaultAssigned:
    """An assignment made by the organisation's niche default: whom to tell after the commit (N30)."""

    engagement_id: UUID
    assignment_id: UUID
    assignee_id: UUID
    title: str
    tell: bool  # False when the assignee is the member whose action opened the engagement


def default_title(title: str) -> str:
    """N30's title for a niche default's assignment, cut to the bell's 200 characters by shortening the title."""
    title = em2.one_line(title)
    full = DEFAULT_TITLE.format(title=title)
    if len(full) <= MAX_TITLE_CHARS:
        return full
    room = max(MAX_TITLE_CHARS - len(DEFAULT_TITLE.format(title="")) - 1, 0)
    return DEFAULT_TITLE.format(title=title[:room] + "…")[:MAX_TITLE_CHARS]


async def _default_for(db: AsyncSession, org_id: UUID, niche_id: UUID | None) -> UUID | None:
    """The organisation's default reviewer for ``niche_id``, else for its parent niche (read as a member)."""
    if niche_id is None:
        return None
    parent = await db.scalar(select(Niche.parent_id).where(Niche.id == niche_id))
    niches = [niche_id] if parent is None else [niche_id, parent]
    rows = await db.execute(
        select(OrgNicheDefault.niche_id, OrgNicheDefault.user_id).where(
            OrgNicheDefault.org_id == org_id, OrgNicheDefault.niche_id.in_(niches)
        )
    )
    found = dict(rows.tuples().all())
    return found.get(niche_id) or (found.get(parent) if parent is not None else None)


async def assign_niche_default(
    db: AsyncSession, org_id: UUID, engagement_id: UUID, *, opener: UUID | None = None
) -> DefaultAssigned | None:
    """Assign a new engagement to its niche's default reviewer (see the module docstring), in the caller's transaction
    (a savepoint: a refusal leaves it usable), bound to a triage member of ``org_id``; None when none was assigned.
    ``opener`` is who opened the engagement (the bound member when None): the assignee is told unless it is them."""
    actor, _ = tenant_of(db)
    engagement: Engagement | None = await db.scalar(
        select(Engagement).where(Engagement.id == engagement_id, Engagement.org_id == org_id)
    )
    if actor is None or engagement is None or engagement.state not in DEFAULT_STATES:
        return None
    ever = await db.scalar(select(EngagementAssignment.id).where(EngagementAssignment.engagement_id == engagement.id))
    if ever is not None:  # someone already assigned it (or unassigned it on purpose): never overwritten
        return None
    version = (
        await db.execute(
            select(ProposalVersion.niche_id, ProposalVersion.title).where(ProposalVersion.id == engagement.version_id)
        )
    ).one_or_none()
    assignee = await _default_for(db, org_id, version.niche_id if version else None)
    if assignee is None or assignee == engagement.developer_id or not await _is_triage_member(db, org_id, assignee):
        return None
    assignment_id = uuid7()
    try:
        async with db.begin_nested():
            await db.execute(
                insert(EngagementAssignment).values(
                    id=assignment_id,
                    engagement_id=engagement.id,
                    org_id=org_id,
                    assignee_user_id=assignee,
                    assigned_by=actor,
                )
            )
    except DBAPIError as exc:  # a race (someone assigned it meanwhile) or the guard: the engagement stays as it is
        log.warning("engagement.niche_default_skipped", sqlstate=getattr(exc.orig, "sqlstate", None))
        return None
    await audit(
        db,
        "engagement.assigned",
        actor_user_id=None,
        actor_kind=AuditActor.SYSTEM,
        org_id=org_id,
        subject_type="engagement",
        subject_id=engagement.id,
        payload={
            "engagement_id": str(engagement.id),
            "assignment_id": str(assignment_id),
            "assignee_user_id": str(assignee),
            "reason": "niche_default",
        },
    )
    title = (version.title if version else None) or SOME_PROPOSAL
    return DefaultAssigned(engagement.id, assignment_id, assignee, title, tell=assignee != (opener or actor))


async def assign_niche_default_safely(db: AsyncSession, org_id: UUID, engagement_id: UUID) -> DefaultAssigned | None:
    """``assign_niche_default`` in a savepoint that any error rolls back, logged: the rule never undoes the action that
    opened the engagement (a signatory's interest, committed by the caller afterwards)."""
    try:
        async with db.begin_nested():
            return await assign_niche_default(db, org_id, engagement_id)
    except Exception as exc:
        failed = type(exc).__name__
        log.error("engagement.niche_default_failed", engagement_id=str(engagement_id), error_type=failed)
        return None


async def tell_default_assignee(
    factory: async_sessionmaker[AsyncSession], org_id: UUID, assigned: DefaultAssigned | None
) -> bool:
    """N30 to the niche default's assignee, after the commit, unless they opened the engagement themselves."""
    if assigned is None or not assigned.tell:
        return False
    return await _post_n30(
        factory,
        user_id=assigned.assignee_id,
        org_id=org_id,
        engagement_id=assigned.engagement_id,
        assignment_id=assigned.assignment_id,
        title=default_title(assigned.title),
        body=DEFAULT_BODY,
    )


async def apply_niche_defaults(
    factory: async_sessionmaker[AsyncSession], developer_id: UUID, opened: Sequence[tuple[UUID, UUID]]
) -> list[DefaultAssigned]:
    """After a Pitch committed its ``SUBMITTED`` engagements (``(engagement, organisation)`` pairs): each one's niche
    default through ``app_niche_default_assignee`` (revision 0015: the developer's session reads none of the
    organisation's rows), then, when it names a member, ``assign_niche_default`` in a session bound to that member
    and the organisation (``assigned_by`` the member, P27's path; a unique violation means someone assigned it first:
    nothing is done) and N30 to them. Never raises: an error is logged and the next engagement is tried."""
    done: list[DefaultAssigned] = []
    for engagement_id, org_id in opened:
        try:
            async with factory() as db:
                await bind_tenant(db, user_id=developer_id)
                member: UUID | None = await db.scalar(_DEFAULT_ASSIGNEE, {"engagement": engagement_id})
            if member is None:
                continue
            async with factory() as db:
                await bind_tenant(db, user_id=member, org_id=org_id)
                assigned = await assign_niche_default(db, org_id, engagement_id, opener=developer_id)
                await db.commit()
        except Exception as exc:  # the Pitch stands whatever happens here
            failed = type(exc).__name__
            log.error("engagement.niche_default_failed", engagement_id=str(engagement_id), error_type=failed)
            continue
        if assigned is not None:
            await tell_default_assignee(factory, org_id, assigned)
            done.append(assigned)
    return done
