"""Tracker read models (REQ-ENG-02, REQ-ENG-03 data; docs/spec/06 6.9 Rendering and Persistence).

Everything is read under the caller's RLS as a party. The History (``history``) is built only from rows both parties
read alike (events, endorsements, user display names), so its JSON is the same for the developer and the organisation
(AC-TRACK-3) once the developer is named; the detail view adds the caller's own party, roles and action buttons.

The developer is a pseudonymous handle to the organisation until the engagement's chain has reached
``INTEREST_CONFIRMED`` or a later main-path state (docs/spec/06 6.1; ``proposals.access.REVEALED_STATES``, the render's
``owner_named`` rule): until then the organisation's summary, detail and History carry the registered version's
``owner_handle`` in place of the developer's display name and no developer user id (the History's developer events and
endorsements name no user). The developer's own view is unchanged. Reveal of the developer's contact
details (``contact_reveal``) is for the organisation's named contact only, from ``INTEREST_CONFIRMED`` on, and is
audit-logged.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.models import User
from bridge.engagements import chain, documents
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.commands import agreement_document
from bridge.engagements.models import (
    Agreement,
    Engagement,
    EngagementEndorsement,
    EngagementEvent,
    EngagementMessage,
    EngagementMessageRead,
    EngagementNote,
    Milestone,
    PaymentRecord,
    Signature,
)
from bridge.engagements.schemas import (
    AgreementOut,
    ContactOut,
    ContactRevealOut,
    DocumentOut,
    DocumentRefOut,
    DueOut,
    EndorsementOut,
    EngagementDetail,
    EngagementSummary,
    HistoryEventOut,
    HistoryMessageOut,
    HistoryOut,
    MilestoneOut,
    NoteOut,
    PaymentOut,
    PendingOut,
    SideLimitsOut,
    SignatureOut,
)
from bridge.engagements.service import Loaded, Party, app_now, entering_event, load, load_holidays, load_many
from bridge.errors import forbidden, not_found
from bridge.legal.models import LegalTemplate, NdaTemplate
from bridge.models.enums import (
    AgreementStatus,
    EngagementActorRole,
    EngagementEndReason,
    EngagementParty,
    EngagementState,
    MilestoneState,
    SignatureDocumentKind,
)
from bridge.proposals.access import REVEALED_STATES
from bridge.proposals.models import ProposalVersion
from bridge.tenancy.models import Organization


async def _names(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
    return {row.id: row.display_name for row in rows}


HANDLE_FALLBACK = "Developer"  # a version without a handle (never registered): the organisation sees this
FORMER_MEMBER = "Former member"  # [[COPY-REVIEW]] a message's sender whose name the caller can no longer read


def sender_name(names: dict[UUID, str], sender_user_id: UUID) -> str:
    """A thread message's sender as the thread and the History tab both name them (``party_names``' names)."""
    return names.get(sender_user_id) or FORMER_MEMBER


async def developer_revealed(db: AsyncSession, engagement_id: UUID) -> bool:
    """Whether the organisation may know who the developer is: the chain has reached a ``REVEALED_STATES`` state."""
    found = await db.scalar(
        select(EngagementEvent.id)
        .where(EngagementEvent.engagement_id == engagement_id, EngagementEvent.to_state.in_(REVEALED_STATES))
        .limit(1)
    )
    return found is not None


async def developer_identity(
    db: AsyncSession, engagement: Engagement, *, developer_caller: bool
) -> tuple[UUID | None, str, bool]:
    """(user id, name, named) of the developer as the caller may see them: the developer and, once revealed, the
    organisation get the id and the display name; before that the organisation gets the version's handle only."""
    if developer_caller or await developer_revealed(db, engagement.id):
        name = await db.scalar(select(User.display_name).where(User.id == engagement.developer_id))
        return engagement.developer_id, name or HANDLE_FALLBACK, True
    handle = await db.scalar(select(ProposalVersion.owner_handle).where(ProposalVersion.id == engagement.version_id))
    return None, handle or HANDLE_FALLBACK, False


async def party_names(
    db: AsyncSession, engagement: Engagement, user_ids: Iterable[UUID], *, developer_caller: bool
) -> dict[UUID, str]:
    """The display names of the parties among ``user_ids`` as the tracker shows them to the caller: the developer by
    ``developer_identity``'s rule (their handle for the organisation until named), everyone else by name."""
    wanted = set(user_ids)
    names = await _names(db, wanted - {engagement.developer_id})
    if engagement.developer_id in wanted:
        _, names[engagement.developer_id], _ = await developer_identity(
            db, engagement, developer_caller=developer_caller
        )
    return names


async def unread_counts(db: AsyncSession, reader_id: UUID, engagement_ids: Sequence[UUID]) -> dict[UUID, int]:
    """Per engagement of ``engagement_ids``: the thread's messages by others that ``reader_id`` has not read (newer
    than their read marker, or all of them without one), in one statement however many engagements (REQ-ENG-11)."""
    if not engagement_ids:
        return {}
    m, r = EngagementMessage, EngagementMessageRead
    rows = await db.execute(
        select(m.engagement_id, func.count())
        .select_from(m)
        .outerjoin(r, and_(r.engagement_id == m.engagement_id, r.user_id == reader_id))
        .where(
            m.engagement_id.in_(list(engagement_ids)),
            m.sender_user_id != reader_id,
            or_(r.last_read_at.is_(None), m.created_at > r.last_read_at),
        )
        .group_by(m.engagement_id)
    )
    return {engagement_id: int(count) for engagement_id, count in rows.tuples()}


@dataclass(frozen=True, slots=True)
class _Shown:
    """What summaries show beside the engagements' own columns, read for all of them at once: the organisations'
    names, the versions' titles and handles, which engagements have revealed their developer, and the display names
    of the developers the caller may see (``developer_identity``'s rule)."""

    orgs: dict[UUID, str]
    versions: dict[UUID, tuple[str | None, str | None]]
    revealed: set[UUID]
    developers: dict[UUID, str]


async def _shown(db: AsyncSession, engagements: Sequence[Engagement], *, developer_caller: bool) -> _Shown:
    orgs = await db.execute(
        select(Organization.id, Organization.legal_name).where(
            Organization.id.in_(list({e.org_id for e in engagements}))
        )
    )
    versions = await db.execute(
        select(ProposalVersion.id, ProposalVersion.title, ProposalVersion.owner_handle).where(
            ProposalVersion.id.in_(list({e.version_id for e in engagements}))
        )
    )
    revealed: set[UUID] = set()
    if not developer_caller:
        found = await db.scalars(
            select(EngagementEvent.engagement_id)
            .where(
                EngagementEvent.engagement_id.in_([e.id for e in engagements]),
                EngagementEvent.to_state.in_(REVEALED_STATES),
            )
            .distinct()
        )
        revealed = set(found.all())
    named = [e.developer_id for e in engagements if developer_caller or e.id in revealed]
    return _Shown(
        orgs=dict(orgs.tuples().all()),  # a list: a Result has keys(), so dict() would treat it as a mapping
        versions={row.id: (row.title, row.owner_handle) for row in versions},
        revealed=revealed,
        developers=await _names(db, named),
    )


def due_out(deadline: datetime, now: datetime, holidays: frozenset[date]) -> DueOut:
    """The current step's deadline: its business days from ``now`` and ``due_at``, the deadline itself in UTC, the
    very instant ``overdue`` is tested against (REQ-TRACK-03), so a countdown and the flag never disagree."""
    d = sm.due(deadline, now, holidays)
    return DueOut(
        due_on=d.due_on,
        due_at=deadline.astimezone(UTC),
        business_days_left=d.business_days_left,
        overdue=d.overdue,
    )


def _summary(
    engagement: Engagement,
    loaded: Loaded,
    shown: _Shown,
    now: datetime,
    holidays: frozenset[date],
    *,
    developer_caller: bool,
    unread: int = 0,
) -> EngagementSummary:
    title, handle = shown.versions.get(engagement.version_id, (None, None))
    named = developer_caller or engagement.id in shown.revealed
    developer_id = engagement.developer_id if named else None
    developer = (shown.developers.get(engagement.developer_id) if named else handle) or HANDLE_FALLBACK
    due = None
    if engagement.stage_deadline_at is not None and engagement.ended_at is None:
        due = due_out(engagement.stage_deadline_at, now, holidays)
    return EngagementSummary(
        id=engagement.id,
        proposal_id=engagement.proposal_id,
        version_id=engagement.version_id,
        proposal_title=title or "Proposal",
        org_id=engagement.org_id,
        org_name=shown.orgs.get(engagement.org_id, "Organisation"),
        developer_id=developer_id,
        developer_name=developer,
        developer_named=named,
        origin=engagement.origin,
        state=engagement.state,
        stage_label=sm.STAGE_LABELS.get(engagement.state, engagement.state.value),
        stage_group=sm.STAGE_GROUPS.get(engagement.state),
        end_reason=engagement.end_reason,
        stage_entered_at=engagement.stage_entered_at,
        stage_deadline_at=engagement.stage_deadline_at,
        due=due,
        ended_at=engagement.ended_at,
        lock_version=engagement.lock_version,
        whose_turn=list(sm.whose_turn(engagement.state, loaded.facts)),
        updated_at=engagement.updated_at,
        paused_from=loaded.facts.paused_from,
        unread_messages=unread,
    )


async def summary(
    db: AsyncSession,
    engagement: Engagement,
    loaded: Loaded,
    now: datetime,
    holidays: frozenset[date],
    *,
    developer_caller: bool,
    reader_id: UUID | None = None,
) -> EngagementSummary:
    shown = await _shown(db, [engagement], developer_caller=developer_caller)
    unread = (await unread_counts(db, reader_id, [engagement.id])).get(engagement.id, 0) if reader_id else 0
    return _summary(engagement, loaded, shown, now, holidays, developer_caller=developer_caller, unread=unread)


async def summaries(
    db: AsyncSession,
    engagements: Sequence[Engagement],
    *,
    deals_enabled: bool,
    developer_caller: bool,
    reader_id: UUID | None = None,
) -> list[EngagementSummary]:
    """The summary of each engagement (the lists), with one query per kind of row however many there are (P16-E1);
    with ``reader_id``, each counts the thread's messages that reader has not read."""
    if not engagements:
        return []
    now = await app_now(db)
    holidays = await load_holidays(db, local_date(now))
    loaded = await load_many(db, engagements, deals_enabled=deals_enabled, developer_caller=developer_caller)
    shown = await _shown(db, engagements, developer_caller=developer_caller)
    unread = await unread_counts(db, reader_id, [e.id for e in engagements]) if reader_id else {}
    return [
        _summary(e, loaded[e.id], shown, now, holidays, developer_caller=developer_caller, unread=unread.get(e.id, 0))
        for e in engagements
    ]


def _endorsement(row: EngagementEndorsement, names: dict[UUID, str], hidden: UUID | None = None) -> EndorsementOut:
    """``hidden``: the developer's user id while the caller may not see it (the name is then the handle)."""
    return EndorsementOut(
        id=row.id,
        stage=row.stage,
        stage_round=row.stage_round,
        milestone_id=row.milestone_id,
        party=row.party,
        user_id=None if row.user_id is not None and row.user_id == hidden else row.user_id,
        name=names.get(row.user_id) if row.user_id else None,
        role=row.role,
        method=row.method,
        endorsed_at=row.endorsed_at,
    )


async def _endorsements(db: AsyncSession, engagement_id: UUID) -> list[EngagementEndorsement]:
    rows = await db.execute(
        select(EngagementEndorsement)
        .where(EngagementEndorsement.engagement_id == engagement_id)
        .order_by(EngagementEndorsement.endorsed_at, EngagementEndorsement.id)
    )
    return list(rows.scalars())


async def detail(db: AsyncSession, party: Party, *, deals_enabled: bool) -> EngagementDetail:
    engagement = await db.get(Engagement, party.engagement_id, populate_existing=True)
    if engagement is None:
        raise not_found()
    loaded = await load(db, engagement, deals_enabled=deals_enabled, developer_caller=party.is_developer)
    now = await app_now(db)
    holidays = await load_holidays(db, local_date(now))
    base = await summary(
        db, engagement, loaded, now, holidays, developer_caller=party.is_developer, reader_id=party.user_id
    )
    agreements = list(
        (
            await db.execute(
                select(Agreement).where(Agreement.engagement_id == engagement.id).order_by(Agreement.version.desc())
            )
        ).scalars()
    )
    milestones = list(
        (
            await db.execute(select(Milestone).where(Milestone.engagement_id == engagement.id).order_by(Milestone.seq))
        ).scalars()
    )
    signatures = list(
        (
            await db.execute(
                select(Signature).where(Signature.engagement_id == engagement.id).order_by(Signature.signed_at)
            )
        ).scalars()
    )
    payments = list(
        (
            await db.execute(
                select(PaymentRecord)
                .where(PaymentRecord.engagement_id == engagement.id)
                .order_by(PaymentRecord.recorded_at)
            )
        ).scalars()
    )
    review_due = await review_due_dates(db, engagement.id, milestones)
    endorsements = [  # the current stage's since it was entered from the main path (a pause continues it)
        e
        for e in await _endorsements(db, engagement.id)
        if e.stage is engagement.state and loaded.first_round <= e.stage_round <= loaded.stage_round
    ]
    notes = (
        await db.execute(
            select(EngagementNote)
            .where(EngagementNote.engagement_id == engagement.id)
            .order_by(EngagementNote.event_seq)
        )
    ).scalars()
    names = await _names(
        db,
        [engagement.contact_user_id, *(s.signer_user_id for s in signatures), *(e.user_id for e in endorsements)],
    )
    hidden = None if base.developer_named else engagement.developer_id
    if hidden is not None:
        names[hidden] = base.developer_name
    contact = None
    if engagement.contact_user_id is not None and engagement.contact_channel and engagement.contact_by:
        role = await db.scalar(
            select(EngagementEvent.payload["contact_role"].astext)
            .where(EngagementEvent.engagement_id == engagement.id, EngagementEvent.payload.has_key("contact_role"))
            .order_by(EngagementEvent.seq.desc())
            .limit(1)
        )
        contact = ContactOut(
            user_id=engagement.contact_user_id,
            name=names.get(engagement.contact_user_id),
            role=role,
            channel=engagement.contact_channel,
            contact_by=await _contact_by(db, engagement),
        )
    documents_out = [
        DocumentRefOut(kind=ref.kind, ref=ref.ref, sha256=ref.sha256.hex())
        for ref in (loaded.nda, loaded.certificate)
        if ref is not None
    ]
    return EngagementDetail(
        **base.model_dump(),
        my_party=party.actor.party,
        my_roles=sorted(party.actor.roles),
        actions=list(sm.available(party.actor, engagement.state, loaded.facts)),
        awaiting=[PendingOut(command=p.command, party=p.party) for p in sm.pending(engagement.state, loaded.facts)],
        contact=contact,
        endorsements=[_endorsement(e, names, hidden) for e in endorsements],
        agreements=[
            AgreementOut(
                id=a.id,
                version=a.version,
                status=a.status,
                ip_terms=a.ip_terms,
                exclusivity=a.exclusivity,
                deemed_acceptance_days=a.deemed_acceptance_days,
                document_sha256=a.final_pdf_sha256.hex() if a.final_pdf_sha256 else None,
                drafted_by=EngagementParty.DEVELOPER
                if a.created_by == engagement.developer_id
                else EngagementParty.ORG,
                milestones=[_milestone(m, review_due.get(m.id)) for m in milestones if m.agreement_id == a.id],
                created_at=a.created_at,
            )
            for a in agreements
        ],
        signatures=[
            SignatureOut(
                id=s.id,
                document_kind=s.document_kind,
                document_ref=s.document_ref,
                document_sha256=s.document_sha256.hex(),
                party=s.party,
                signer_user_id=s.signer_user_id,  # signatures come after INTEREST_CONFIRMED: always named
                signer_name=names.get(s.signer_user_id),
                step_up_method=s.step_up_method,
                signed_at=s.signed_at,
            )
            for s in signatures
        ],
        payments=[
            PaymentOut(
                id=p.id,
                milestone_id=p.milestone_id,
                amount_kes_minor=p.amount_kes_minor,
                method=p.method,
                reference=p.reference,
                paid_on=p.paid_on,
                recorded_by=p.recorded_by,
                recorded_at=p.recorded_at,
                confirmed_by=p.confirmed_by,
                confirmed_at=p.confirmed_at,
                confirmed_amount_kes_minor=p.confirmed_amount_kes_minor,
            )
            for p in payments
        ],
        documents=documents_out,
        notes=[
            NoteOut(
                kind=n.kind,  # the database's CHECK holds it to the four kinds
                body=n.body,
                resume_at=n.resume_at,
                by=EngagementParty.DEVELOPER if n.created_by == engagement.developer_id else EngagementParty.ORG,
                at=n.created_at,
                seq=n.event_seq,
            )
            for n in notes
        ],
        side_limits=_side_limits(engagement.state, loaded.facts),
        today=sm.platform_day(now),  # the clock the commands check a hold's date against
    )


_ASKING: Final = frozenset({EngagementState.SUBMITTED, EngagementState.UNDER_REVIEW})


def _side_limits(state: EngagementState, facts: sm.Facts) -> SideLimitsOut | None:
    """The caps left for the current stage (in a side state, the stage it returns to): questions in stages 1-2, holds
    and days on hold before the agreement; null once ended or where none applies."""
    stage = facts.paused_from if state in sm.RETURNING else state
    if stage is None or state in sm.TERMINAL:
        return None

    def left(value: int | None) -> int | None:
        return None if value is None else max(value, 0)

    holding = stage in sm.PAUSABLE
    limits = SideLimitsOut(
        questions_left=left(facts.questions_left) if stage in _ASKING else None,
        holds_left=left(facts.holds_left) if holding else None,
        hold_days_left=left(facts.hold_days_left) if holding else None,
    )
    return None if limits == SideLimitsOut(questions_left=None, holds_left=None, hold_days_left=None) else limits


async def _contact_by(db: AsyncSession, engagement: Engagement) -> date:
    """The contact-by date as the tracker shows it: the date the organisation named (kept on the row, quoted by EM2),
    moved like every due date by a hold at stage 3 (docs/spec/06 6.9: due dates shift by the hold's length). While the
    stage's deadline is the named date it entered with, the deadline now is that date moved; otherwise (a date that
    had passed when the stage was entered) the named date stands."""
    named = engagement.contact_by
    assert named is not None  # the caller checked
    deadline = engagement.stage_deadline_at
    if engagement.state is not EngagementState.INTEREST_CONFIRMED or deadline is None:
        return named
    entered = await entering_event(db, engagement.id, EngagementState.INTEREST_CONFIRMED, from_main_path=True)
    if entered is None or entered.stage_deadline_at is None or local_date(entered.stage_deadline_at) != named:
        return named
    return max(named, local_date(deadline))


def _milestone(m: Milestone, review_due_on: date | None) -> MilestoneOut:
    return MilestoneOut(
        id=m.id,
        seq=m.seq,
        deliverable=m.deliverable,
        amount_kes_minor=m.amount_kes_minor,
        due_date=m.due_date,
        review_window_bd=m.review_window_bd,
        state=m.state,
        review_due_on=review_due_on,
    )


async def review_due_dates(db: AsyncSession, engagement_id: UUID, milestones: Sequence[Milestone]) -> dict[UUID, date]:
    """REQ-ENG-09: a milestone under review is due its review window in business days after the Nairobi date of its
    latest submission (a resubmission after changes starts a new window)."""
    waiting = {str(m.id): m for m in milestones if m.state is MilestoneState.SUBMITTED_FOR_REVIEW}
    if not waiting:
        return {}
    milestone_id = EngagementEvent.payload["milestone_id"].astext
    rows = await db.execute(
        select(milestone_id, func.max(EngagementEvent.created_at))
        .where(
            EngagementEvent.engagement_id == engagement_id,
            EngagementEvent.command == sm.Command.SUBMIT_MILESTONE.value,
            milestone_id.in_(list(waiting)),
        )
        .group_by(milestone_id)
    )
    submitted = {key: local_date(at) for key, at in rows.tuples()}  # the chain records every submission
    holidays = await load_holidays(db, min(submitted.values())) if submitted else frozenset()
    return {
        waiting[key].id: add_business_days(on, waiting[key].review_window_bd, holidays) for key, on in submitted.items()
    }


async def history(db: AsyncSession, engagement_id: UUID, *, developer_caller: bool) -> HistoryOut:
    """The History tab: the chain as the database stores it (payload read back as its jsonb text, as the verifier
    hashes it) and every endorsement, with the actors' display names; the developer's events and endorsements name
    their handle and no user for the organisation until the developer is named."""
    engagement = await db.get(Engagement, engagement_id)
    if engagement is None:
        raise not_found()
    connection = await db.connection()
    rows = await chain.load_chain(connection, engagement_id)
    endorsements = await _endorsements(db, engagement_id)
    messages = (
        await db.execute(
            select(
                EngagementMessage.id,
                EngagementMessage.sender_party,
                EngagementMessage.sender_user_id,
                EngagementMessage.created_at,
            )
            .where(EngagementMessage.engagement_id == engagement_id)
            .order_by(EngagementMessage.created_at, EngagementMessage.id)
        )
    ).all()
    names = await _names(
        db,
        [*(r.actor_user_id for r in rows), *(e.user_id for e in endorsements), *(m.sender_user_id for m in messages)],
    )
    _, handle, named = await developer_identity(db, engagement, developer_caller=developer_caller)
    hidden = None if named else engagement.developer_id
    if hidden is not None:
        names[hidden] = handle
    events = [
        HistoryEventOut(
            id=r.id,
            seq=r.seq,
            created_at=r.created_at,
            actor_user_id=None if r.actor_user_id is not None and r.actor_user_id == hidden else r.actor_user_id,
            actor_name=names.get(r.actor_user_id) if r.actor_user_id else None,
            actor_role=EngagementActorRole(r.actor_role),
            command=r.command,
            from_state=EngagementState(r.from_state) if r.from_state else None,
            to_state=EngagementState(r.to_state),
            end_reason=EngagementEndReason(r.end_reason) if r.end_reason else None,
            stage_deadline_at=r.stage_deadline_at,
            payload=_payload(r.payload_text),
            prev_hash=r.prev_hash.hex(),
            hash=r.hash.hex(),
        )
        for r in rows
    ]
    return HistoryOut(
        engagement_id=engagement_id,
        chain_verified=bool(rows) and not chain.verify_rows(rows),
        events=events,
        endorsements=[_endorsement(e, names, hidden) for e in endorsements],
        messages=[  # who wrote and when (AC-TRACK-9), never the text; the developer by handle until named
            HistoryMessageOut(
                id=m.id,
                sender_party=m.sender_party,
                sender_name=sender_name(names, m.sender_user_id),
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


def _payload(text_value: str) -> dict[str, object]:
    value = json.loads(text_value)
    return value if isinstance(value, dict) else {}


async def document(db: AsyncSession, engagement: Engagement, kind: SignatureDocumentKind) -> DocumentOut:
    """The exact text of a signed (or to-be-signed) document, re-rendered from the recorded facts, with the recorded
    hash and whether the text still matches it. 404 when the engagement has no such document yet."""
    if kind is SignatureDocumentKind.AGREEMENT:
        agreement = await db.scalar(
            select(Agreement)
            .where(Agreement.engagement_id == engagement.id)
            .order_by(Agreement.version.desc())
            .limit(1)
        )
        if agreement is None:
            raise not_found("This engagement has no agreement yet.")
        rendered = await agreement_document(db, agreement)
        recorded = agreement.final_pdf_sha256 or rendered.sha256  # a draft is not signed yet: its own hash
        return DocumentOut(
            kind=kind, ref=agreement.id, sha256=recorded.hex(), text=rendered.text, intact=recorded == rendered.sha256
        )
    command = sm.Command.SEND_NDA if kind is SignatureDocumentKind.MUTUAL_NDA else sm.Command.ACCEPT_DELIVERY
    if kind not in (SignatureDocumentKind.MUTUAL_NDA, SignatureDocumentKind.ACCEPTANCE_CERTIFICATE):
        raise not_found()
    event = await db.scalar(
        select(EngagementEvent)
        .where(EngagementEvent.engagement_id == engagement.id, EngagementEvent.command == command.value)
        .order_by(EngagementEvent.seq.desc())
        .limit(1)
    )
    if event is None:
        raise not_found("This engagement has no such document yet.")
    payload = dict(event.payload)
    ref, recorded = UUID(payload["document_ref"]), bytes.fromhex(payload["document_sha256"])
    if kind is SignatureDocumentKind.MUTUAL_NDA:
        found = await db.execute(
            select(NdaTemplate, LegalTemplate)
            .join(LegalTemplate, LegalTemplate.id == NdaTemplate.legal_template_id)
            .where(NdaTemplate.id == UUID(payload["template_id"]))
        )
        row = found.first()
        if row is None:
            raise not_found("The NDA template of this document is gone.")
        nda, legal = row
        rendered = documents.mutual_nda(
            ref=ref,
            engagement_id=engagement.id,
            proposal_id=engagement.proposal_id,
            org_id=engagement.org_id,
            developer_id=engagement.developer_id,
            template_version=nda.version,
            template_sha256=nda.sha256,
            template_body=legal.body,
        )
    else:
        signed = await db.scalar(
            select(Agreement).where(
                Agreement.engagement_id == engagement.id, Agreement.status == AgreementStatus.SIGNED
            )
        )
        if signed is None or signed.final_pdf_sha256 is None:
            raise not_found("The signed agreement of this certificate is not readable.")
        milestone_ids = (
            await db.execute(select(Milestone.id).where(Milestone.agreement_id == signed.id).order_by(Milestone.seq))
        ).scalars()
        rendered = documents.acceptance_certificate(
            ref=ref,
            engagement_id=engagement.id,
            agreement_id=signed.id,
            agreement_sha256=signed.final_pdf_sha256,
            milestone_ids=list(milestone_ids),
        )
    return DocumentOut(
        kind=kind, ref=ref, sha256=recorded.hex(), text=rendered.text, intact=recorded == rendered.sha256
    )


async def contact_reveal(db: AsyncSession, party: Party) -> ContactRevealOut:
    """The developer's verified email for the organisation's named contact (docs/spec/06 6.9 stage 3; AC-TRACK-9):
    403 for anyone else and before ``INTEREST_CONFIRMED``. Each reveal is audit-logged on the organisation's chain."""
    engagement = await db.get(Engagement, party.engagement_id)
    if engagement is None:
        raise not_found()
    if party.is_developer or engagement.contact_user_id != party.user_id:
        raise forbidden(
            "not_the_contact", "Only the organisation's named contact sees the developer's contact details."
        )
    state = engagement.state
    if state in sm.RETURNING:  # paused: the stage it returns to decides (a hold does not hide a revealed contact)
        paused = await entering_event(db, engagement.id, state)
        state = paused.from_state if paused is not None and paused.from_state is not None else state
    if state not in sm.CONTACT_REVEALED:
        raise forbidden("contact_not_revealed", "Contact details are shared once the organisation approves to proceed.")
    developer = await db.get(User, engagement.developer_id)
    if developer is None:
        raise not_found()
    await audit(
        db,
        "engagement.contact_revealed",
        actor_user_id=party.user_id,
        org_id=party.org_id,
        subject_type="engagement",
        subject_id=engagement.id,
        payload={"engagement_id": str(engagement.id)},
    )
    return ContactRevealOut(
        developer_name=developer.display_name,
        email=developer.email if developer.email_verified_at is not None else None,
        phone=None,
    )
