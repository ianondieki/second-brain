"""Organisations, memberships and invitations (REQ-TEN-01). Tenancy ORG: RLS by active membership
(``app_is_member``), narrowed to ``app.org_id`` when a request is scoped to one organisation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
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
