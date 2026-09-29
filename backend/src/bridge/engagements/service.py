"""Tracker reads shared by the commands and the API (REQ-ENG-01, REQ-ENG-02): who the caller is on an engagement, the
facts the state machine needs, the shared clock and the business-day calendar, and the mapping of the database's
refusals to HTTP errors.

Parties only (docs/spec/08 error semantics): a caller who is neither the engagement's developer nor an active member
of its organisation gets 404, the same as for an engagement that does not exist (staff admin, who may read every
engagement under RLS, is not a party either). A user who is both is refused (403): one person never acts for both
sides (revision 0003, review P1 MINOR 7; round 2 MINOR 2). Organisation members in a role that needs two-step
sign-in get the same checks as ``bridge.tenancy.deps.org_member``, and the transaction is then scoped to the
organisation (``app.org_id``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.admin.models import Holiday
from bridge.auth.sessions import LiveSession
from bridge.db import bind_tenant
from bridge.engagements import state_machine as sm
from bridge.engagements.models import (
    Agreement,
    Engagement,
    EngagementEndorsement,
    EngagementEvent,
    Milestone,
    PaymentRecord,
    Signature,
)
from bridge.errors import ApiError, forbidden, not_found
from bridge.models.enums import (
    MFA_REQUIRED_ORG_ROLES,
    AgreementStatus,
    DevVerification,
    EngagementActorRole,
    EngagementParty,
    EngagementState,
    OrgRole,
    SignatureDocumentKind,
)
from bridge.profiles.models import DeveloperProfile
from bridge.tenancy.service import membership_of

R = EngagementActorRole
ACTOR_ROLES: Final = {
    OrgRole.OWNER: R.OWNER,
    OrgRole.ADMIN: R.ADMIN,
    OrgRole.REVIEWER: R.REVIEWER,
    OrgRole.SIGNATORY: R.SIGNATORY,
    OrgRole.FINANCE: R.FINANCE,
}  # a viewer acts in no tracker role
HOLIDAY_WINDOW: Final = timedelta(days=400)  # covers the longest deadline (30 BD) and a year of test clock
_NOW = text("SELECT app_clock_now()")
_D2_OR_ABOVE = (DevVerification.D2, DevVerification.D3)


@dataclass(frozen=True, slots=True)
class Party:
    """The caller on one engagement: the developer, or an organisation member with their roles."""

    engagement_id: UUID
    live: LiveSession
    actor: sm.Actor
    org_id: UUID
    org_roles: frozenset[OrgRole] = frozenset()

    @property
    def user_id(self) -> UUID:
        return self.live.user.id

    @property
    def is_developer(self) -> bool:
        return self.actor.party is EngagementParty.DEVELOPER


async def resolve_party(db: AsyncSession, live: LiveSession, engagement_id: UUID) -> Party:
    """The caller's party on ``engagement_id``, or 404 (not a party), 403 (both sides, or two-step sign-in missing
    for their role) or 401 (second factor pending)."""
    await bind_tenant(db, user_id=live.user.id)
    engagement = await db.get(Engagement, engagement_id)
    if engagement is None:
        raise not_found()
    membership = await membership_of(db, engagement.org_id, live.user.id)
    is_developer = engagement.developer_id == live.user.id
    if is_developer and membership is not None:
        raise forbidden("both_parties", "You belong to this organisation, so you cannot act on this engagement.")
    if is_developer:
        return Party(engagement_id, live, sm.Actor(EngagementParty.DEVELOPER, sm.DEVELOPER), engagement.org_id)
    if membership is None:
        raise not_found()
    roles = frozenset(OrgRole(r) for r in membership.roles)
    if roles & MFA_REQUIRED_ORG_ROLES:
        if live.user.totp_enabled_at is None:
            raise forbidden("mfa_enrolment_required", "Turn on two-step sign-in to use this organisation.")
        if live.row.mfa_verified_at is None:
            raise ApiError(401, "mfa_required", "Enter the code from your authenticator app.")
    await bind_tenant(db, user_id=live.user.id, org_id=engagement.org_id)
    actor_roles = frozenset(ACTOR_ROLES[r] for r in roles if r in ACTOR_ROLES)
    return Party(engagement_id, live, sm.Actor(EngagementParty.ORG, actor_roles), engagement.org_id, roles)


async def lock_engagement(db: AsyncSession, engagement_id: UUID) -> Engagement:
    """The engagement, re-read and locked FOR UPDATE until commit (both parties pass the UPDATE policy's USING), so
    the state and ``lock_version`` a command checks are the ones its event starts from."""
    found = await db.execute(
        select(Engagement)
        .where(Engagement.id == engagement_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    engagement = found.scalar_one_or_none()
    if engagement is None:  # it was visible a moment ago: the caller lost access meanwhile
        raise not_found()
    return engagement


async def app_now(db: AsyncSession) -> datetime:
    """The shared clock (``app_clock_now()``: the database clock plus the dev/test clock's offset where enabled), so
    deadlines, evidence times and the test clock agree."""
    now: datetime = (await db.execute(_NOW)).scalar_one()
    return now


async def load_holidays(db: AsyncSession, today: date) -> frozenset[date]:
    """Observed Kenyan public holidays from ``today`` over the window any deadline needs (REQ-BD-01)."""
    rows = await db.execute(
        select(Holiday.observed_on).where(
            Holiday.country == "KE", Holiday.observed_on >= today, Holiday.observed_on <= today + HOLIDAY_WINDOW
        )
    )
    return frozenset(rows.scalars().all())


@dataclass(frozen=True, slots=True)
class DocumentRef:
    kind: SignatureDocumentKind
    ref: UUID
    sha256: bytes
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Loaded:
    """Everything a command or the detail view reads about one engagement (under the caller's RLS)."""

    facts: sm.Facts
    stage_round: int
    nda: DocumentRef | None = None
    certificate: DocumentRef | None = None
    latest_agreement: Agreement | None = None
    final_agreement: Agreement | None = None
    signed_agreement: Agreement | None = None
    milestones: list[Milestone] = field(default_factory=list)
    final_payment: PaymentRecord | None = None


async def stage_round(db: AsyncSession, engagement: Engagement) -> int:
    """How many times the engagement entered its current stage (the database's ``stage_round`` for endorsements)."""
    count = await db.scalar(
        select(func.count())
        .select_from(EngagementEvent)
        .where(
            EngagementEvent.engagement_id == engagement.id,
            EngagementEvent.to_state == engagement.state,
            EngagementEvent.from_state.is_distinct_from(EngagementEvent.to_state),
        )
    )
    return int(count or 0)


async def _latest_document(db: AsyncSession, engagement_id: UUID, command: sm.Command) -> DocumentRef | None:
    event = await db.scalar(
        select(EngagementEvent)
        .where(EngagementEvent.engagement_id == engagement_id, EngagementEvent.command == command.value)
        .order_by(EngagementEvent.seq.desc())
        .limit(1)
    )
    if event is None:
        return None
    kind = (
        SignatureDocumentKind.MUTUAL_NDA
        if command is sm.Command.SEND_NDA
        else SignatureDocumentKind.ACCEPTANCE_CERTIFICATE
    )
    payload = dict(event.payload)
    return DocumentRef(kind, UUID(payload["document_ref"]), bytes.fromhex(payload["document_sha256"]), payload)


async def signed_parties(
    db: AsyncSession, engagement_id: UUID, kind: SignatureDocumentKind, ref: UUID
) -> frozenset[EngagementParty]:
    rows = await db.execute(
        select(Signature.party).where(
            Signature.engagement_id == engagement_id, Signature.document_kind == kind, Signature.document_ref == ref
        )
    )
    return frozenset(rows.scalars().all())


async def load(
    db: AsyncSession, engagement: Engagement, *, deals_enabled: bool, developer_caller: bool = False
) -> Loaded:
    """The facts of ``engagement`` for the state machine, and the rows behind them. ``developer_caller``: the caller
    is the engagement's developer, the only one who may read their verification level (D2, for signing)."""
    state = engagement.state
    round_ = await stage_round(db, engagement)
    endorsed = await db.execute(
        select(EngagementEndorsement.party).where(
            EngagementEndorsement.engagement_id == engagement.id,
            EngagementEndorsement.stage == state,
            EngagementEndorsement.stage_round == round_,
            EngagementEndorsement.milestone_id.is_(None),
        )
    )
    agreements = list(
        (
            await db.execute(
                select(Agreement).where(Agreement.engagement_id == engagement.id).order_by(Agreement.version.desc())
            )
        ).scalars()
    )
    latest = agreements[0] if agreements else None
    final = next((a for a in agreements if a.status is AgreementStatus.FINAL), None)
    signed_agreement = next((a for a in agreements if a.status is AgreementStatus.SIGNED), None)
    milestones: list[Milestone] = []
    if signed_agreement is not None:
        milestones = list(
            (
                await db.execute(
                    select(Milestone).where(Milestone.agreement_id == signed_agreement.id).order_by(Milestone.seq)
                )
            ).scalars()
        )
    loaded = Loaded(sm.Facts(), round_, latest_agreement=latest, final_agreement=final)
    loaded.signed_agreement, loaded.milestones = signed_agreement, milestones
    loaded.final_payment = await db.scalar(
        select(PaymentRecord).where(PaymentRecord.engagement_id == engagement.id, PaymentRecord.milestone_id.is_(None))
    )
    signed: frozenset[EngagementParty] = frozenset()
    if state is EngagementState.NDA_PENDING:
        loaded.nda = await _latest_document(db, engagement.id, sm.Command.SEND_NDA)
        if loaded.nda is not None:
            signed = await signed_parties(db, engagement.id, loaded.nda.kind, loaded.nda.ref)
    elif state is EngagementState.AGREEMENT_SIGNING and final is not None:
        signed = await signed_parties(db, engagement.id, SignatureDocumentKind.AGREEMENT, final.id)
    elif state is EngagementState.SIGN_OFF:
        loaded.certificate = await _latest_document(db, engagement.id, sm.Command.ACCEPT_DELIVERY)
        if loaded.certificate is not None:
            signed = await signed_parties(db, engagement.id, loaded.certificate.kind, loaded.certificate.ref)
    developer_d2 = False
    if developer_caller:
        level = await db.scalar(
            select(DeveloperProfile.verification_level).where(DeveloperProfile.user_id == engagement.developer_id)
        )
        developer_d2 = level in _D2_OR_ABOVE
    drafted_by = None
    terms_source = final or latest
    if latest is not None:
        drafted_by = EngagementParty.DEVELOPER if latest.created_by == engagement.developer_id else EngagementParty.ORG
    loaded.facts = sm.Facts(
        endorsed=frozenset(endorsed.scalars().all()),
        signed=signed,
        contact_named=engagement.contact_user_id is not None,
        draft_by=drafted_by,
        draft_status=latest.status if latest is not None else None,
        ip_terms=terms_source.ip_terms if terms_source is not None else None,
        milestones=tuple(m.state for m in milestones),
        developer_d2=developer_d2,
        payment_recorded=loaded.final_payment is not None,
        deals_enabled=deals_enabled,
    )
    return loaded


# --------------------------------------------------------------------------------------------------- refusals


def api_error(error: sm.TrackerError) -> ApiError:
    return ApiError(error.status, error.code, error.message)


def db_refusal(exc: DBAPIError) -> ApiError | None:
    """The API error for a refusal by the database's tracker guards (revision 0003), or None for anything else (a
    bug: re-raise). The application checks first, so these are the backstop: an engagement the caller cannot see is
    404 like any cross-tenant reference; an RLS refusal 403; a trigger's or CHECK's refusal, or a lost race on a
    unique key, 409."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    message = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
    if sqlstate == "42501":
        if "no engagement of the caller" in message:
            return not_found()
        return forbidden("refused", "The database refused this change for your role.")
    if sqlstate in ("23514", "23505", "40001", "40P01"):
        return ApiError(409, "conflict", "The engagement changed or this step is not possible now. Reload and retry.")
    return None
