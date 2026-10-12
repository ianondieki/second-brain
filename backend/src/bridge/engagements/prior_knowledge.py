"""The prior-knowledge declaration (REQ-PROV-06; docs/spec/06 6.4 pt 5): "within 10 business days of first Tier-2
access an org may declare existing similar work by submitting the hash of dated internal evidence; shown to the owner;
declarations are not recorded on the platform after this window".

**The window** is the database's (revision 0013, ``app_prior_knowledge_window``: one rule for the API and the
INSERT trigger): it opens at the organisation's first Tier-2 view of the engagement's proposal (the earliest
``document_views`` row of that organisation and proposal, by any of its members) and closes at the end of the 10th
Kenyan business day after that view's day in Africa/Nairobi (``window_closes_on``); both are null before any view.
"Today" is the Nairobi day on the shared clock (the test clock where it is on).

**Declaring** (``POST /api/orgs/{org_id}/engagements/{id}/prior-knowledge``, an owner, admin or signatory): the
evidence's SHA-256 (hashed in the browser: no file is ever uploaded), the organisation's own one-line title for it and
the evidence's date (no later than today, and on or before the Nairobi day of the first Tier-2 view: prior knowledge
predates the access; the security review of revision 0013). Refused, in this order: 403 ``role_not_allowed``; 422 for
the body (``invalid_evidence_title``, a title of exactly ``EVIDENCE_TITLE_REDACTED`` included: it marks a data-subject
request's redaction; ``evidence_date_in_future``); 404 for an engagement that is not the
organisation's (403 ``both_parties`` for its own developer); 409 ``already_declared`` (one per engagement); 409
``engagement_ended`` (revision 0003's chain takes no event once an engagement has ended; checked before the window);
403 ``no_tier2_access_yet`` before any view; 403 ``declaration_window_closed`` with the spec's sentence after the
closing day; 422 ``evidence_after_first_view``. The row is append-only
(``prior_knowledge_declarations``); the engagement's event chain gains ``prior_knowledge_declared`` (from and to the
current state; payload: the declaration's id, the organisation's id and the hash's hex, nothing else) and the
organisation's audit chain a row (ids only); the owner is told (N31, in-app and by status email: the organisation's
name and the idea's title, never the evidence's title or hash) by the tracker's notification job, queued in the same
transaction. The database refuses the same things (the window, the organisation, proposal and version, the role) as a
backstop; its refusals map to the same answers.

**Reading**: the organisation's tracker carries the window (``OrgPriorKnowledgeOut``), the developer's the declaration
(``DeveloperPriorKnowledgeOut``); staff admin reads declarations for a dispute's evidence pack (docs/spec/06 6.12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.engagements import notify
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.models import (
    DECLARATION_ROLES,
    EVIDENCE_TITLE_MAX_CHARS,
    EVIDENCE_TITLE_REDACTED,
    Engagement,
    EngagementEvent,
    PriorKnowledgeDeclaration,
)
from bridge.engagements.plain import one_line
from bridge.engagements.schemas import (
    DeclarationBody,
    DeclarationOut,
    DeveloperPriorKnowledgeOut,
    OrgPriorKnowledgeOut,
)
from bridge.engagements.service import app_now, db_refusal, lock_engagement
from bridge.engagements.team import org_engagement
from bridge.errors import ApiError, forbidden
from bridge.ids import uuid7
from bridge.models.enums import EngagementActorRole, OrgRole
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.models import Organization

COMMAND: Final = sm.PRIOR_KNOWLEDGE_DECLARED  # the engagement event's command code (no state change)
DECLARERS: Final = frozenset(DECLARATION_ROLES)
# The declarer's role on the event, the tracker's preference (state_machine.ROLE_PREFERENCE) among the declarers'.
ACTOR_ROLES: Final = (
    (OrgRole.SIGNATORY, EngagementActorRole.SIGNATORY),
    (OrgRole.OWNER, EngagementActorRole.OWNER),
    (OrgRole.ADMIN, EngagementActorRole.ADMIN),
)
_WINDOW: Final = text("SELECT first_tier2_view_at, window_closes_on FROM app_prior_knowledge_window(:engagement)")
# [[COPY-REVIEW]] docs/spec/06 6.4 pt 5's sentence (the spec's words, capitalised as a sentence) and the API's other
# refusals (the web app shows its own words).
WINDOW_CLOSED: Final = "Declarations are not recorded on the platform after this window."
NO_TIER2_YET: Final = "The declaration window opens when your organisation first views the full proposal."
ALREADY_DECLARED: Final = "Your organisation has already declared prior knowledge on this engagement."
ENGAGEMENT_ENDED: Final = "This engagement has ended, so no declaration can be recorded on it."
ROLE_NOT_ALLOWED: Final = "Only an owner, admin or signatory declares prior knowledge."
INVALID_TITLE: Final = f"Give the evidence a title on one line, at most {EVIDENCE_TITLE_MAX_CHARS} characters."
FUTURE_EVIDENCE: Final = "The evidence's date cannot be after today."
EVIDENCE_AFTER_VIEW: Final = (
    "Prior knowledge predates your organisation's first view of the full proposal: date the evidence on or before"
    " that day."
)
SOME_ORGANISATION: Final = "The organisation"


@dataclass(frozen=True, slots=True)
class Window:
    """The organisation's declaration window on one engagement; both null before its first Tier-2 view."""

    first_tier2_view_at: datetime | None
    window_closes_on: date | None

    def open_on(self, today: date) -> bool:
        return self.window_closes_on is not None and today <= self.window_closes_on


async def window(db: AsyncSession, engagement_id: UUID) -> Window:
    """The window as the database computes it, for a reader of the engagement (no row for anyone else: no window)."""
    row = (await db.execute(_WINDOW, {"engagement": engagement_id})).first()
    if row is None:
        return Window(None, None)
    return Window(row.first_tier2_view_at, row.window_closes_on)


async def for_org(
    db: AsyncSession, engagement: Engagement, roles: frozenset[OrgRole], today: date
) -> OrgPriorKnowledgeOut:
    """The organisation's tracker: its window, when it declared and whether the caller may declare now."""
    found = await window(db, engagement.id)
    declared_at = await db.scalar(
        select(PriorKnowledgeDeclaration.declared_at).where(PriorKnowledgeDeclaration.engagement_id == engagement.id)
    )
    can_declare = (
        found.first_tier2_view_at is not None
        and found.open_on(today)
        and declared_at is None
        and engagement.ended_at is None
        and bool(roles & DECLARERS)
    )
    return OrgPriorKnowledgeOut(
        first_tier2_view_at=found.first_tier2_view_at,
        window_closes_on=found.window_closes_on,
        declared_at=declared_at,
        can_declare=can_declare,
    )


async def for_developer(db: AsyncSession, engagement: Engagement) -> DeveloperPriorKnowledgeOut | None:
    """The developer's tracker: the organisation's declaration on their proposal, or None."""
    d = PriorKnowledgeDeclaration
    row = (
        await db.execute(
            select(d.declared_at, d.evidence_sha256, d.evidence_title, d.evidence_dated_on, Organization.legal_name)
            .outerjoin(Organization, Organization.id == d.org_id)
            .where(d.engagement_id == engagement.id)
        )
    ).first()
    if row is None:
        return None
    return DeveloperPriorKnowledgeOut(
        org_name=row.legal_name or SOME_ORGANISATION,
        declared_at=row.declared_at,
        evidence_sha256_hex=bytes(row.evidence_sha256).hex(),
        evidence_title=row.evidence_title,
        evidence_dated_on=row.evidence_dated_on,
    )


def _actor_role(roles: frozenset[OrgRole]) -> EngagementActorRole:
    return next(actor for role, actor in ACTOR_ROLES if role in roles)


def _closed(closes_on: date | None) -> ApiError:
    extra = {"window_closed_on": closes_on.isoformat()} if closes_on is not None else {}
    return ApiError(403, "declaration_window_closed", WINDOW_CLOSED, **extra)


def _refusal(exc: DBAPIError, closes_on: date) -> ApiError:
    """The database's backstop (revision 0013's window trigger and CHECKs, revision 0003's chain), in the API's words:
    the checks above run first, so these are races (the engagement ending, the window closing, a second declaration)
    or a bug (re-raised). ``closes_on`` is the window's last day as the caller read it (the day does not move; only
    "today" does), so a window closed in the race names it as the API's own check does."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    message = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
    constraint = str(getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or "")
    if sqlstate == "23514" and ("an evidence title of" in message or "evidence_title_valid" in constraint):
        return ApiError(422, "invalid_evidence_title", INVALID_TITLE)  # the redaction marker; the one-line CHECK
    if sqlstate == "55000":
        if "has ended" in message:
            return ApiError(409, "engagement_ended", ENGAGEMENT_ENDED)
        if "has not viewed" in message:
            return forbidden("no_tier2_access_yet", NO_TIER2_YET)
        return _closed(closes_on)
    if sqlstate == "23505" and "prior_knowledge_declarations" in constraint:
        return ApiError(409, "already_declared", ALREADY_DECLARED)
    if sqlstate == "23514" and ("dated after" in message or "evidence_predates_first_view" in constraint):
        return ApiError(422, "evidence_after_first_view", EVIDENCE_AFTER_VIEW)
    if sqlstate == "23514" and "ended" in message:  # revision 0003's chain: no event once an engagement ended
        return ApiError(409, "engagement_ended", ENGAGEMENT_ENDED)
    mapped = db_refusal(exc)
    if mapped is None:
        raise exc
    if sqlstate == "42501" and mapped.status_code == 403:
        return forbidden("role_not_allowed", ROLE_NOT_ALLOWED)
    return mapped


async def declare(db: AsyncSession, org: OrgContext, engagement_id: UUID, body: DeclarationBody) -> DeclarationOut:
    """Record the organisation's declaration, its chain event, its audit row and the owner's N31 job, in the caller's
    transaction (the router commits)."""
    if not org.roles & DECLARERS:
        raise forbidden("role_not_allowed", ROLE_NOT_ALLOWED)
    try:
        title = one_line(body.evidence_title, EVIDENCE_TITLE_MAX_CHARS)
    except ValueError as exc:
        raise ApiError(422, "invalid_evidence_title", INVALID_TITLE) from exc
    if title is None or title == EVIDENCE_TITLE_REDACTED:  # the marker of a data-subject request's redaction
        raise ApiError(422, "invalid_evidence_title", INVALID_TITLE)
    today = local_date(await app_now(db))
    if body.evidence_dated_on > today:
        raise ApiError(422, "evidence_date_in_future", FUTURE_EVIDENCE)
    engagement = await org_engagement(db, org.org_id, engagement_id, org.live.user.id)
    engagement = await lock_engagement(db, engagement.id)
    d = PriorKnowledgeDeclaration
    if await db.scalar(select(d.id).where(d.engagement_id == engagement.id)) is not None:
        raise ApiError(409, "already_declared", ALREADY_DECLARED)
    if engagement.ended_at is not None or engagement.state in sm.TERMINAL:
        raise ApiError(409, "engagement_ended", ENGAGEMENT_ENDED)
    found = await window(db, engagement.id)
    closes_on = found.window_closes_on
    if found.first_tier2_view_at is None or closes_on is None:  # both or neither (app_prior_knowledge_window)
        raise forbidden("no_tier2_access_yet", NO_TIER2_YET)
    if not found.open_on(today):
        raise _closed(closes_on)
    if body.evidence_dated_on > local_date(found.first_tier2_view_at):
        raise ApiError(422, "evidence_after_first_view", EVIDENCE_AFTER_VIEW)
    declaration_id = uuid7()
    digest = bytes.fromhex(body.evidence_sha256_hex)
    try:
        await db.execute(  # the window's columns and declared_at are the database's: left out, read back
            insert(d).values(
                id=declaration_id,
                engagement_id=engagement.id,
                org_id=org.org_id,
                proposal_id=engagement.proposal_id,
                version_id=engagement.version_id,
                declared_by=org.live.user.id,
                evidence_sha256=digest,
                evidence_title=title,
                evidence_dated_on=body.evidence_dated_on,
            )
        )
        event = EngagementEvent(
            id=uuid7(),
            engagement_id=engagement.id,
            actor_user_id=org.live.user.id,
            actor_role=_actor_role(org.roles),
            command=COMMAND,
            from_state=engagement.state,
            to_state=engagement.state,
            end_reason=None,
            stage_deadline_at=None,  # the stage's deadline stays (a same-state event keeps it)
            payload={"declaration_id": str(declaration_id), "org_id": str(org.org_id), "evidence_sha256": digest.hex()},
        )
        db.add(event)
        await db.flush()
    except DBAPIError as exc:
        raise _refusal(exc, closes_on) from exc
    stored = (  # inserted a moment ago in this transaction: the declarer reads it (the engagement's reader)
        await db.execute(select(d.first_tier2_view_at, d.window_closes_on, d.declared_at).where(d.id == declaration_id))
    ).one()
    await audit(
        db,
        "engagement.prior_knowledge_declared",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="engagement",
        subject_id=engagement.id,
        payload={"engagement_id": str(engagement.id), "declaration_id": str(declaration_id)},
    )
    await notify.enqueue(db, engagement, event)  # N31 to the owner, once the declaration commits
    return DeclarationOut(
        id=declaration_id,
        engagement_id=engagement.id,
        evidence_sha256_hex=digest.hex(),
        evidence_title=title,
        evidence_dated_on=body.evidence_dated_on,
        declared_at=stored.declared_at,
        first_tier2_view_at=stored.first_tier2_view_at,
        window_closes_on=stored.window_closes_on,
    )
