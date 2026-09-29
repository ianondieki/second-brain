"""The engagement tracker's tables (REQ-ENG-01, REQ-ENG-02; docs/spec/06 6.9; revisions 0002 and 0003).

One engagement = one proposal x one organisation (docs/spec/03). ``engagement_events`` is the single source of truth:
an append-only, hash-chained log (``hash = sha256(prev_hash || canonical)``; the canonical form is documented in
revision 0003 and recomputed by ``bridge.engagements.chain``), and ``engagements.state`` is its projection, written by
the database in the same statement as the event. The application never sets ``state``, ``end_reason``,
``stage_entered_at``, ``stage_deadline_at``, ``ended_at`` or ``lock_version`` itself: it appends an event.

Rules the database enforces (revision 0003; the state machine in ``engagements/state_machine.py`` enforces the rest):

- Every engagement starts its chain when it is inserted (a genesis event, seq 1, written by the database). An event
  names the state the engagement is in as ``from_state`` (a stale one is refused), and none follows a terminal state.
  ``IN_IMPLEMENTATION`` needs a signed agreement, ``PAYMENT_FINAL`` both parties' signatures of the acceptance
  certificate, and ``CLOSED`` (from ``PAYMENT_FINAL``) the developer's confirmation of the final payment at the
  recorded amount.
- Parties only: the engagement's developer and the members of its organisation read every tracker row; staff admin
  reads them; nobody else sees anything. Each row names its actor as the caller (a system row names nobody).
- Event payloads hold only ids, codes, dates, amounts and digests: string values match ``[A-Za-z0-9_.:+-]{0,128}``
  and keys ``[a-z][a-z0-9_]*`` (free text and personal data go to a mutable details store, as for the audit log).
- Endorsements, signatures and events are append-only; a payment record changes once, by the developer's
  confirmation. The platform records payments and never moves money.
- Times (event ``created_at``, ``stage_entered_at``, ``ended_at``, ``endorsed_at``, ``signed_at``, ``recorded_at``,
  ``confirmed_at``) are the database's, on the shared clock ``app_clock_now()`` (the test clock's offset applies only
  where the owner enabled it: dev, test and staging databases).

ORM notes: after appending an event, refresh the ``Engagement`` (its projection changed in the database). The
engagement's ``lock_version`` is a server-side version counter (bumped by the database on every UPDATE), so a stale
ORM update raises ``StaleDataError``. Never set the database's columns (``seq``, ``prev_hash``, ``hash``, the times,
``stage_round``): values sent are replaced or refused.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Interval,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import (
    AgreementStatus,
    ContactChannel,
    EndorsementMethod,
    EngagementActorRole,
    EngagementEndReason,
    EngagementOrigin,
    EngagementParty,
    EngagementState,
    IpTerms,
    MilestoneState,
    PaymentMethod,
    SignatureDocumentKind,
    StepUpMethod,
)
from bridge.models.types import pg_enum

DECLINED_REASONS = (
    "'NOT_PRIORITY', 'ALREADY_IN_PROGRESS_INTERNALLY', 'BUDGET', 'NOT_RELEVANT', 'NEEDS_MATURITY', 'OTHER',"
    " 'BY_DEVELOPER'"
)
EXPIRED_REASONS = "'NO_REVIEW', 'NO_DECISION', 'CONTACT_NOT_MADE', 'NO_DEV_RESPONSE'"
TERMINAL = "'DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED'"


def end_reason_matches(state_column: str) -> str:
    """docs/spec/06 6.9 Codes: DECLINED and EXPIRED carry their own reason codes; no other state has one."""
    return (
        f"({state_column} = 'DECLINED' AND end_reason IN ({DECLINED_REASONS}))"
        f" OR ({state_column} = 'EXPIRED' AND end_reason IN ({EXPIRED_REASONS}))"
        f" OR ({state_column} NOT IN ('DECLINED', 'EXPIRED') AND end_reason IS NULL)"
    )


VIA_ENGAGEMENT = {"info": {"tenancy": Tenancy.ORG_OR_USER, "via": "engagements"}}
SHA256_SIZE = "octet_length({column}) = 32"


class Engagement(IdMixin, TimestampsMixin, Base):
    """One proposal x one organisation (docs/spec/03). ``state`` is the projection of ``engagement_events``."""

    __tablename__ = "engagements"
    __table_args__ = (
        UniqueConstraint("proposal_id", "org_id"),
        ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_engagements_version",
        ),
        CheckConstraint(end_reason_matches("state"), name="end_reason_matches_state"),
        # Set by the database when the engagement enters a terminal state (and only then).
        CheckConstraint(f"(ended_at IS NOT NULL) = (state IN ({TERMINAL}))", name="ended_exactly_when_terminal"),
        # The organisation's named contact (docs/spec/06 6.9 stage 3): person, channel and contact-by date together.
        CheckConstraint(
            "(contact_user_id IS NULL) = (contact_channel IS NULL)"
            " AND (contact_channel IS NULL) = (contact_by IS NULL)",
            name="contact_complete",
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "developer_id"}},
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"))
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    developer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    version_id: Mapped[UUID] = mapped_column()
    origin: Mapped[EngagementOrigin] = mapped_column(pg_enum(EngagementOrigin, "engagement_origin"))
    state: Mapped[EngagementState] = mapped_column(pg_enum(EngagementState, "engagement_state"))
    end_reason: Mapped[EngagementEndReason | None] = mapped_column(
        pg_enum(EngagementEndReason, "engagement_end_reason")
    )
    # Revision 0003. The database's: when the current stage was entered (the entering event's created_at) and its
    # deadline (the entering event's stage_deadline_at, set by the state machine from policy.yaml), when a terminal
    # state was entered, and the optimistic-concurrency counter (bumped on every UPDATE).
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stage_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, server_default="0", server_onupdate=FetchedValue())
    # Written by the organisation's owner, admin or signatory; the contact is an active member of the organisation.
    contact_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    contact_channel: Mapped[ContactChannel | None] = mapped_column(pg_enum(ContactChannel, "contact_channel"))
    contact_by: Mapped[date | None] = mapped_column(Date)

    __mapper_args__ = {"version_id_col": lock_version, "version_id_generator": False}  # noqa: RUF012


class EngagementEvent(IdMixin, Base):
    """One entry of an engagement's hash chain. INSERT-only (grants and triggers). ``seq``, ``prev_hash``, ``hash``
    and ``created_at`` are set by the database under the engagement's row lock; send ``from_state`` as the state the
    command was checked against (a stale one is refused) and ``to_state`` as the state it leads to (equal for an
    event that changes no state, such as one party's endorsement)."""

    __tablename__ = "engagement_events"
    __table_args__ = (
        UniqueConstraint("engagement_id", "seq"),
        UniqueConstraint("engagement_id", "prev_hash"),
        CheckConstraint(end_reason_matches("to_state"), name="end_reason_matches_state"),
        CheckConstraint("command ~ '^[a-z][a-z0-9_]{0,39}$'", name="command_is_a_code"),
        # A system event (a job) names no user; every other event names its actor.
        CheckConstraint("(actor_role = 'system') = (actor_user_id IS NULL)", name="actor_matches_role"),
        CheckConstraint("app_event_payload_is_valid(payload)", name="payload_holds_ids_and_codes"),
        CheckConstraint(
            f"{SHA256_SIZE.format(column='prev_hash')} AND {SHA256_SIZE.format(column='hash')}",
            name="hashes_are_sha256",
        ),
        VIA_ENGAGEMENT,
    )

    engagement_id: Mapped[UUID] = mapped_column(ForeignKey("engagements.id"))
    seq: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[EngagementActorRole] = mapped_column(pg_enum(EngagementActorRole, "engagement_actor_role"))
    command: Mapped[str] = mapped_column(String(40))
    from_state: Mapped[EngagementState | None] = mapped_column(pg_enum(EngagementState, "engagement_state"))
    to_state: Mapped[EngagementState] = mapped_column(pg_enum(EngagementState, "engagement_state"))
    end_reason: Mapped[EngagementEndReason | None] = mapped_column(
        pg_enum(EngagementEndReason, "engagement_end_reason")
    )
    # The deadline of the stage this event enters (or, unchanged state, a new deadline for it); NULL for none.
    stage_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, server_default=FetchedValue())
    hash: Mapped[bytes] = mapped_column(LargeBinary, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EngagementEndorsement(IdMixin, Base):
    """One party's endorsement of a dual-endorsement stage (docs/spec/06 6.9), or of a milestone's acceptance at
    ``IN_IMPLEMENTATION``. Append-only; only the stage the engagement is in can be endorsed. ``stage_round`` (the
    database's) counts the times the engagement has entered ``stage``, so a stage entered again (a disputed first
    contact returns to stage 3) is endorsed afresh."""

    __tablename__ = "engagement_endorsements"
    __table_args__ = (
        # One endorsement per party of each entry into a stage (and of each milestone; NULL counts as one value).
        Index(
            "uq_engagement_endorsements_once",
            "engagement_id",
            "stage",
            "stage_round",
            "party",
            "milestone_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["milestone_id", "engagement_id"],
            ["milestones.id", "milestones.engagement_id"],
            name="fk_engagement_endorsements_milestone",
        ),
        # An automatic endorsement (a job) names no user and acts as the system; every other names its endorser.
        CheckConstraint(
            "(method = 'auto') = (user_id IS NULL) AND (method = 'auto') = (role = 'system')", name="auto_names_nobody"
        ),
        CheckConstraint(
            "(party = 'developer' AND role IN ('developer', 'system'))"
            " OR (party = 'org' AND role IN ('owner', 'admin', 'reviewer', 'signatory', 'finance', 'system'))",
            name="role_matches_party",
        ),
        VIA_ENGAGEMENT,
    )

    engagement_id: Mapped[UUID] = mapped_column(ForeignKey("engagements.id"))
    stage: Mapped[EngagementState] = mapped_column(pg_enum(EngagementState, "engagement_state"))
    stage_round: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    milestone_id: Mapped[UUID | None] = mapped_column()
    party: Mapped[EngagementParty] = mapped_column(pg_enum(EngagementParty, "engagement_party"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[EngagementActorRole] = mapped_column(pg_enum(EngagementActorRole, "engagement_actor_role"))
    method: Mapped[EndorsementMethod] = mapped_column(pg_enum(EndorsementMethod, "endorsement_method"))
    endorsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Agreement(IdMixin, TimestampsMixin, Base):
    """A version of the definitive agreement (docs/spec/06 6.9 stage 8, AC-TRACK-10). A draft is edited by either
    party; marking it ``final`` needs the IP terms, the deemed-acceptance clause, the final PDF's SHA-256 and at least
    one milestone, and freezes all of them; it becomes ``signed`` once both parties signed that PDF."""

    __tablename__ = "agreements"
    __table_args__ = (
        UniqueConstraint("engagement_id", "version"),
        UniqueConstraint("id", "engagement_id"),  # target of the milestones' (agreement_id, engagement_id) key
        Index(
            "uq_agreements_signed_engagement", "engagement_id", unique=True, postgresql_where=text("status = 'signed'")
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "exclusivity IS NULL OR (btrim(exclusivity) <> '' AND length(exclusivity) <= 500)", name="exclusivity"
        ),
        # 0 = the clause says a milestone is never deemed accepted; otherwise after that many days (docs/spec/06 6.9).
        CheckConstraint("deemed_acceptance_days BETWEEN 0 AND 90", name="deemed_acceptance_days"),
        CheckConstraint("final_pdf_sha256 IS NULL OR octet_length(final_pdf_sha256) = 32", name="final_pdf_sha256"),
        CheckConstraint(
            "status = 'draft' OR (ip_terms IS NOT NULL AND deemed_acceptance_days IS NOT NULL"
            " AND final_pdf_sha256 IS NOT NULL)",
            name="final_is_complete",
        ),
        VIA_ENGAGEMENT,
    )

    engagement_id: Mapped[UUID] = mapped_column(ForeignKey("engagements.id"))
    version: Mapped[int] = mapped_column(SmallInteger)
    ip_terms: Mapped[IpTerms | None] = mapped_column(pg_enum(IpTerms, "ip_terms"))
    exclusivity: Mapped[str | None] = mapped_column(Text)
    deemed_acceptance_days: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[AgreementStatus] = mapped_column(
        pg_enum(AgreementStatus, "agreement_status"), server_default=AgreementStatus.DRAFT.value
    )
    final_pdf_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class Milestone(IdMixin, TimestampsMixin, Base):
    """A milestone of an agreement (docs/spec/06 6.9 milestone sub-tracker). Planned while the agreement is a draft;
    once the agreement is signed it moves PLANNED -> IN_PROGRESS -> SUBMITTED_FOR_REVIEW (the developer) ->
    ACCEPTED | CHANGES_REQUESTED (the organisation), and CHANGES_REQUESTED -> IN_PROGRESS (the developer)."""

    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("agreement_id", "seq"),
        UniqueConstraint("id", "engagement_id"),  # target of endorsements' and payments' (milestone, engagement) key
        ForeignKeyConstraint(
            ["agreement_id", "engagement_id"],
            ["agreements.id", "agreements.engagement_id"],
            name="fk_milestones_agreement",
        ),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("btrim(deliverable) <> '' AND length(deliverable) <= 500", name="deliverable"),
        CheckConstraint("amount_kes_minor > 0", name="amount_positive"),
        CheckConstraint("review_window_bd BETWEEN 1 AND 60", name="review_window_bd"),
        VIA_ENGAGEMENT,
    )

    agreement_id: Mapped[UUID] = mapped_column()
    engagement_id: Mapped[UUID] = mapped_column(ForeignKey("engagements.id"), index=True)
    seq: Mapped[int] = mapped_column(SmallInteger)
    deliverable: Mapped[str] = mapped_column(Text)
    amount_kes_minor: Mapped[int] = mapped_column(BigInteger)  # KES in cents (minor units)
    due_date: Mapped[date] = mapped_column(Date)
    review_window_bd: Mapped[int] = mapped_column(SmallInteger)
    state: Mapped[MilestoneState] = mapped_column(
        pg_enum(MilestoneState, "milestone_state"), server_default=MilestoneState.PLANNED.value
    )


class Signature(IdMixin, Base):
    """An internal simple e-signature (docs/spec/06 6.9 SignatureProvider, Release 1) of one party on one document.
    Append-only. The signer signs as themselves after a TOTP or passkey step-up: the developer (D2 for an agreement)
    or an organisation signatory. An agreement is signed only in its final version and at its final PDF's hash, and
    never internally when its IP terms are an assignment or an exclusive licence (AC-TRACK-10)."""

    __tablename__ = "signatures"
    __table_args__ = (
        UniqueConstraint("engagement_id", "document_kind", "document_ref", "party"),
        CheckConstraint(SHA256_SIZE.format(column="document_sha256"), name="document_sha256"),
        VIA_ENGAGEMENT,
    )

    engagement_id: Mapped[UUID] = mapped_column(ForeignKey("engagements.id"))
    document_kind: Mapped[SignatureDocumentKind] = mapped_column(
        pg_enum(SignatureDocumentKind, "signature_document_kind")
    )
    # The agreement's id, the milestone's id, or the application's id of the NDA or acceptance certificate.
    document_ref: Mapped[UUID] = mapped_column()
    document_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    signer_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    party: Mapped[EngagementParty] = mapped_column(pg_enum(EngagementParty, "engagement_party"))
    step_up_method: Mapped[StepUpMethod] = mapped_column(pg_enum(StepUpMethod, "step_up_method"))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(200))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentRecord(IdMixin, Base):
    """A payment the organisation says it made (docs/spec/06 6.9 stage 12 and the milestone payments), confirmed
    once by the developer with the amount received. No code path moves money: the platform never holds funds. The
    record never changes except that one confirmation (trigger) and is never deleted."""

    __tablename__ = "payment_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["milestone_id", "engagement_id"],
            ["milestones.id", "milestones.engagement_id"],
            name="fk_payment_records_milestone",
        ),
        CheckConstraint("amount_kes_minor > 0", name="amount_positive"),
        CheckConstraint(
            "confirmed_amount_kes_minor IS NULL OR confirmed_amount_kes_minor >= 0", name="confirmed_amount"
        ),
        CheckConstraint("reference IS NULL OR btrim(reference) <> ''", name="reference_not_blank"),
        CheckConstraint(
            "(confirmed_by IS NULL) = (confirmed_at IS NULL)"
            " AND (confirmed_at IS NULL) = (confirmed_amount_kes_minor IS NULL)",
            name="confirmation_complete",
        ),
        VIA_ENGAGEMENT,
    )

    engagement_id: Mapped[UUID] = mapped_column(ForeignKey("engagements.id"), index=True)
    milestone_id: Mapped[UUID | None] = mapped_column()  # NULL: the final payment
    amount_kes_minor: Mapped[int] = mapped_column(BigInteger)  # KES in cents (minor units)
    method: Mapped[PaymentMethod] = mapped_column(pg_enum(PaymentMethod, "payment_method"))
    reference: Mapped[str | None] = mapped_column(String(64))  # the M-Pesa or bank reference
    paid_on: Mapped[date] = mapped_column(Date)
    recorded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_onupdate=FetchedValue())
    confirmed_amount_kes_minor: Mapped[int | None] = mapped_column(BigInteger)


class DevTestClock(Base):
    """The dev/test clock shared by the API and the worker: one row, an offset added to the database clock
    (``app_clock_now()``) where the owner enabled it. Readable by the app; moved only forward, only through
    ``app_set_test_clock(offset)``, which the test-clock router calls (dev, test and staging only; the router is not
    in the production image, and a production database never has the clock enabled)."""

    __tablename__ = "test_clock"
    __table_args__ = (
        CheckConstraint("singleton", name="singleton"),
        CheckConstraint("clock_offset >= interval '0' AND clock_offset <= interval '366 days'", name="clock_offset"),
        {"info": {"tenancy": Tenancy.SYSTEM}},
    )

    singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True, server_default=text("true"))
    # Set by the owner (python -m bridge.seed outside production); nothing else enables it.
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    clock_offset: Mapped[timedelta] = mapped_column(Interval, server_default=text("'00:00:00'::interval"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "Agreement",
    "DevTestClock",
    "Engagement",
    "EngagementEndorsement",
    "EngagementEvent",
    "Milestone",
    "PaymentRecord",
    "Signature",
]
