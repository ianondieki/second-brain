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

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import or_, select, text
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


async def load_holidays(db: AsyncSession, today: date, *, since: date | None = None) -> frozenset[date]:
    """Observed Kenyan public holidays from ``today`` (or from ``since``, a past date a count starts at: the day a
    stage was paused or entered) over the window any deadline needs (REQ-BD-01)."""
    start = min(today, since) if since is not None else today
    rows = await db.execute(
        select(Holiday.observed_on).where(
            Holiday.country == "KE", Holiday.observed_on >= start, Holiday.observed_on <= today + HOLIDAY_WINDOW
        )
    )
    return frozenset(rows.scalars().all())


async def entering_event(
    db: AsyncSession, engagement_id: UUID, state: EngagementState, *, from_main_path: bool = False
) -> EngagementEvent | None:
    """The latest event that entered ``state`` (a state change; the genesis too). ``from_main_path``: not a return
    from a side state, so the stage's own start (its count and deadline began there)."""
    query = select(EngagementEvent).where(
        EngagementEvent.engagement_id == engagement_id,
        EngagementEvent.to_state == state,
        EngagementEvent.from_state.is_distinct_from(EngagementEvent.to_state),
    )
    if from_main_path:
        query = query.where(
            or_(EngagementEvent.from_state.is_(None), EngagementEvent.from_state.not_in(list(sm.RETURNING)))
        )
    found: EngagementEvent | None = await db.scalar(query.order_by(EngagementEvent.seq.desc()).limit(1))
    return found


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
    stage_round: int  # how many times the engagement entered its state (the database's stage_round of endorsements)
    first_round: int = 1  # the round its latest entry from the main path began: a return from a side state continues it
    nda: DocumentRef | None = None
    certificate: DocumentRef | None = None
    latest_agreement: Agreement | None = None
    final_agreement: Agreement | None = None
    signed_agreement: Agreement | None = None
    milestones: list[Milestone] = field(default_factory=list)
    final_payment: PaymentRecord | None = None


# The command whose event carries the document a state's signatures are for (the NDA, the acceptance certificate).
_DOCUMENT_OF: Final = {
    EngagementState.NDA_PENDING: (sm.Command.SEND_NDA, SignatureDocumentKind.MUTUAL_NDA),
    EngagementState.SIGN_OFF: (sm.Command.ACCEPT_DELIVERY, SignatureDocumentKind.ACCEPTANCE_CERTIFICATE),
}


def _document(event: EngagementEvent, kind: SignatureDocumentKind) -> DocumentRef:
    payload = dict(event.payload)
    return DocumentRef(kind, UUID(payload["document_ref"]), bytes.fromhex(payload["document_sha256"]), payload)


async def load(
    db: AsyncSession, engagement: Engagement, *, deals_enabled: bool, developer_caller: bool = False
) -> Loaded:
    """The facts of ``engagement`` for the state machine, and the rows behind them. ``developer_caller``: the caller
    is the engagement's developer, the only one who may read their verification level (D2, for signing)."""
    loaded = await load_many(db, [engagement], deals_enabled=deals_enabled, developer_caller=developer_caller)
    return loaded[engagement.id]


async def load_many(
    db: AsyncSession, engagements: Sequence[Engagement], *, deals_enabled: bool, developer_caller: bool = False
) -> dict[UUID, Loaded]:
    """``load`` for each of ``engagements`` with one query per kind of row, however many there are (the lists,
    P16-E1): the current stage's round and endorsements, the agreement versions, the signed agreement's milestones,
    the final payment, the NDA or acceptance certificate and its signatures, and the developer's level."""
    if not engagements:
        return {}
    ids = [e.id for e in engagements]
    # Every state change in chain order: how many times each engagement entered its state (the database's
    # stage_round for endorsements), which round its latest entry from the main path began, and, in a side state,
    # the state it was entered from.
    entered = await db.execute(
        select(EngagementEvent.engagement_id, EngagementEvent.from_state, EngagementEvent.to_state)
        .where(
            EngagementEvent.engagement_id.in_(ids),
            EngagementEvent.from_state.is_distinct_from(EngagementEvent.to_state),
        )
        .order_by(EngagementEvent.engagement_id, EngagementEvent.seq)
    )
    changes: dict[UUID, list[tuple[EngagementState | None, EngagementState]]] = defaultdict(list)
    for eid, from_state, to_state in entered.tuples():
        changes[eid].append((from_state, to_state))
    rounds = {e.id: _rounds(changes[e.id], e.state) for e in engagements}
    endorsements = await db.execute(
        select(
            EngagementEndorsement.engagement_id,
            EngagementEndorsement.stage,
            EngagementEndorsement.stage_round,
            EngagementEndorsement.party,
        ).where(
            EngagementEndorsement.engagement_id.in_(ids),
            EngagementEndorsement.stage.in_(list({e.state for e in engagements})),
            EngagementEndorsement.milestone_id.is_(None),
        )
    )
    endorsed: dict[UUID, set[EngagementParty]] = defaultdict(set)
    states = {e.id: e.state for e in engagements}
    for eid, stage, stage_round, party in endorsements.tuples():
        first, current, _ = rounds[eid]
        if stage is states[eid] and first <= stage_round <= current:  # this entry's, a pause in between included
            endorsed[eid].add(party)
    agreements: dict[UUID, list[Agreement]] = defaultdict(list)
    for agreement in (
        await db.execute(
            select(Agreement)
            .where(Agreement.engagement_id.in_(ids))
            .order_by(Agreement.engagement_id, Agreement.version.desc())
        )
    ).scalars():
        agreements[agreement.engagement_id].append(agreement)
    milestones: dict[UUID, list[Milestone]] = defaultdict(list)
    signed_ids = [a.id for versions in agreements.values() for a in versions if a.status is AgreementStatus.SIGNED]
    if signed_ids:
        found_milestones = await db.execute(
            select(Milestone).where(Milestone.agreement_id.in_(signed_ids)).order_by(Milestone.seq)
        )
        for milestone in found_milestones.scalars():
            milestones[milestone.agreement_id].append(milestone)
    payments: dict[UUID, PaymentRecord] = {}
    found_payments = await db.execute(
        select(PaymentRecord)
        .where(PaymentRecord.engagement_id.in_(ids), PaymentRecord.milestone_id.is_(None))
        .order_by(PaymentRecord.engagement_id, PaymentRecord.recorded_at, PaymentRecord.id)
    )
    for payment in found_payments.scalars():
        payments.setdefault(payment.engagement_id, payment)
    documents: dict[UUID, DocumentRef] = {}
    with_documents = {e.id: _DOCUMENT_OF[e.state] for e in engagements if e.state in _DOCUMENT_OF}
    if with_documents:
        latest = await db.execute(
            select(EngagementEvent)
            .where(
                EngagementEvent.engagement_id.in_(list(with_documents)),
                EngagementEvent.command.in_(list({command.value for command, _ in with_documents.values()})),
            )
            .order_by(EngagementEvent.engagement_id, EngagementEvent.command, EngagementEvent.seq.desc())
            .distinct(EngagementEvent.engagement_id, EngagementEvent.command)
        )
        for event in latest.scalars():
            command, kind = with_documents[event.engagement_id]
            if event.command == command.value:
                documents[event.engagement_id] = _document(event, kind)
    signing: dict[UUID, tuple[SignatureDocumentKind, UUID]] = {}
    for e in engagements:
        final = next((a for a in agreements.get(e.id, ()) if a.status is AgreementStatus.FINAL), None)
        if e.id in documents:
            signing[e.id] = (documents[e.id].kind, documents[e.id].ref)
        elif e.state is EngagementState.AGREEMENT_SIGNING and final is not None:
            signing[e.id] = (SignatureDocumentKind.AGREEMENT, final.id)
    signatures: dict[tuple[UUID, SignatureDocumentKind, UUID], set[EngagementParty]] = defaultdict(set)
    if signing:
        found_signatures = await db.execute(
            select(Signature.engagement_id, Signature.document_kind, Signature.document_ref, Signature.party).where(
                Signature.engagement_id.in_(list(signing))
            )
        )
        for eid, kind, ref, party in found_signatures.tuples():
            signatures[(eid, kind, ref)].add(party)
    levels: dict[UUID, DevVerification | None] = {}
    if developer_caller:
        found_levels = await db.execute(
            select(DeveloperProfile.user_id, DeveloperProfile.verification_level).where(
                DeveloperProfile.user_id.in_(list({e.developer_id for e in engagements}))
            )
        )
        levels = dict(found_levels.tuples().all())
    return {
        e.id: _loaded(
            e,
            rounds=rounds[e.id],
            endorsed=frozenset(endorsed.get(e.id, ())),
            agreements=agreements.get(e.id, []),
            milestones=milestones,
            payment=payments.get(e.id),
            document=documents.get(e.id),
            signed=frozenset(signatures.get((e.id, *signing[e.id]), ())) if e.id in signing else frozenset(),
            developer_d2=developer_caller and levels.get(e.developer_id) in _D2_OR_ABOVE,
            deals_enabled=deals_enabled,
        )
        for e in engagements
    }


def _rounds(
    changes: Sequence[tuple[EngagementState | None, EngagementState]], state: EngagementState
) -> tuple[int, int, EngagementState | None]:
    """(first round, current round, paused from) of an engagement in ``state`` from its state changes in chain order:
    a return from a side state (docs/spec/06 6.9: ON_HOLD, INFO_REQUESTED) enters the stage again in the database's
    count but continues it, so what was endorsed before the pause still counts."""
    first = current = 0
    for from_state, to_state in changes:
        if to_state is state:
            current += 1
            if from_state not in sm.RETURNING:
                first = current
    paused_from = None
    if state in sm.RETURNING and changes and changes[-1][1] is state:
        paused_from = changes[-1][0]
    return first, current, paused_from


def _loaded(
    engagement: Engagement,
    *,
    rounds: tuple[int, int, EngagementState | None],
    endorsed: frozenset[EngagementParty],
    agreements: Sequence[Agreement],
    milestones: Mapping[UUID, Sequence[Milestone]],
    payment: PaymentRecord | None,
    document: DocumentRef | None,
    signed: frozenset[EngagementParty],
    developer_d2: bool,
    deals_enabled: bool,
) -> Loaded:
    """One engagement's ``Loaded`` from the rows ``load_many`` read (agreements newest version first)."""
    latest = agreements[0] if agreements else None
    final = next((a for a in agreements if a.status is AgreementStatus.FINAL), None)
    signed_agreement = next((a for a in agreements if a.status is AgreementStatus.SIGNED), None)
    own_milestones = list(milestones.get(signed_agreement.id, ())) if signed_agreement is not None else []
    first_round, stage_round, paused_from = rounds
    loaded = Loaded(sm.Facts(), stage_round, first_round, latest_agreement=latest, final_agreement=final)
    loaded.signed_agreement, loaded.milestones, loaded.final_payment = signed_agreement, own_milestones, payment
    if engagement.state is EngagementState.NDA_PENDING:
        loaded.nda = document
    elif engagement.state is EngagementState.SIGN_OFF:
        loaded.certificate = document
    drafted_by = None
    terms_source = final or latest
    if latest is not None:
        drafted_by = EngagementParty.DEVELOPER if latest.created_by == engagement.developer_id else EngagementParty.ORG
    loaded.facts = sm.Facts(
        endorsed=endorsed,
        signed=signed,
        contact_named=engagement.contact_user_id is not None,
        draft_by=drafted_by,
        draft_status=latest.status if latest is not None else None,
        ip_terms=terms_source.ip_terms if terms_source is not None else None,
        milestones=tuple(m.state for m in own_milestones),
        developer_d2=developer_d2,
        payment_recorded=payment is not None,
        deals_enabled=deals_enabled,
        paused_from=paused_from,
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
