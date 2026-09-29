"""Organisations, memberships, invitations and the cross-org signal table (REQ-TEN-01). Tenancy ORG: RLS by active
membership (``app_is_member``), narrowed to ``app.org_id`` when a request is scoped to one organisation; every
signed-in user also reads *listed* organisations (unclaimed, E1 or E2 and not delisted: the directory)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import MembershipStatus, OrgKind, OrgRole, OrgSource, OrgVerification
from bridge.models.types import CIText, pg_enum, pg_enum_array

ORG = {"info": {"tenancy": Tenancy.ORG, "tenant_column": "org_id"}}


class Organization(IdMixin, TimestampsMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = ({"info": {"tenancy": Tenancy.ORG, "tenant_column": "id"}},)

    kind: Mapped[OrgKind] = mapped_column(pg_enum(OrgKind, "org_kind"))
    legal_name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(CIText(), unique=True)
    country: Mapped[str] = mapped_column(String(2), server_default="KE")
    regions: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    registration_no: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(String(255))
    verified_domain: Mapped[str | None] = mapped_column(CIText())
    verification: Mapped[OrgVerification] = mapped_column(
        pg_enum(OrgVerification, "org_verification"), server_default=OrgVerification.PENDING.value
    )
    public_entity: Mapped[bool] = mapped_column(Boolean, server_default="false")
    source: Mapped[OrgSource] = mapped_column(pg_enum(OrgSource, "org_source"))
    sector_id: Mapped[UUID | None] = mapped_column(ForeignKey("niches.id"))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    # Directory (docs/spec/06 6.2; revision 0002). Only county_code is the app's to change: the rest are set by the
    # seed, staff and the SECURITY DEFINER claim, delisting and opt-out functions.
    official_domains: Mapped[list[str]] = mapped_column(ARRAY(CIText()), server_default="{}")
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_retrieved_on: Mapped[date | None] = mapped_column(Date)
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invitations_opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    e2_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverify_due_on: Mapped[date | None] = mapped_column(Date)  # annual E2 re-verification
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # no Tier-2 access while set


class Membership(IdMixin, TimestampsMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"), ORG)

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    roles: Mapped[list[OrgRole]] = mapped_column(pg_enum_array(OrgRole, "org_role"))
    status: Mapped[MembershipStatus] = mapped_column(
        pg_enum(MembershipStatus, "membership_status"), server_default=MembershipStatus.ACTIVE.value
    )


class Invitation(IdMixin, CreatedMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (ORG,)

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(CIText())
    roles: Mapped[list[OrgRole]] = mapped_column(pg_enum_array(OrgRole, "org_role"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    invited_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignalEvent(IdMixin, Base):
    """The only table cross-org aggregates read (trends, responsiveness, research hot pairs; docs/spec/08 Tenancy):
    ids, enums and salted hashes, written in the same transaction as the source event. ``bridge_app`` may only
    INSERT; ``aggregate_worker`` may only SELECT."""

    __tablename__ = "signal_events"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (Index("ix_signal_events_kind_ts", "kind", "ts"), {"info": {"tenancy": Tenancy.SYSTEM}})

    item_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(40))
    actor_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    org_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
