"""Niche taxonomy, regions, organisation niches, claims and directory invitations (docs/spec/03 Organisation axes;
docs/spec/06 6.2; docs/spec/08 core tables; REQ-DIR-01..04)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, LargeBinary, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import ClaimLevel, ClaimStatus, DirectoryInvitationStatus, RegionKind
from bridge.models.types import CIText, pg_enum

GLOBAL = {"info": {"tenancy": Tenancy.GLOBAL}}


class Niche(IdMixin, CreatedMixin, Base):
    """Two-level niche taxonomy mapped to ISIC Rev.4; extendable by admin (docs/spec/03)."""

    __tablename__ = "niches"
    __table_args__ = (GLOBAL,)

    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("niches.id"))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    isic_code: Mapped[str | None] = mapped_column(String(8))
    name_en: Mapped[str] = mapped_column(String(120))
    name_sw: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")


class Region(CreatedMixin, Base):
    """Country and county (MVP: KE and the 47 counties, docs/spec/03). ``code`` is ISO 3166 / 3166-2."""

    __tablename__ = "regions"
    __table_args__ = (GLOBAL,)

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    kind: Mapped[RegionKind] = mapped_column(pg_enum(RegionKind, "region_kind"))
    name: Mapped[str] = mapped_column(String(80))
    county_code: Mapped[str | None] = mapped_column(String(3), unique=True)


class OrgNiche(Base):
    __tablename__ = "org_niches"
    __table_args__ = ({"info": {"tenancy": Tenancy.ORG, "tenant_column": "org_id"}},)

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    niche_id: Mapped[UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)


class OrgClaim(IdMixin, TimestampsMixin, Base):
    """A claim of an organisation at E1 (domain-email OTP + DNS TXT) or E2 (manual legal-entity review).

    Readable by the claimant, the organisation's owners and admins, and staff admin/moderator. The app writes the
    claimant's progress; approval runs only through ``app_approve_claim_e1`` (automatic E1) and ``app_decide_claim``
    (staff admin), which set ``organizations.verification`` and create the claimant's membership. The OTP is compared
    in SQL by ``app_confirm_claim_otp``; ``otp_verified_at`` is never the app's to set. The OTP columns change only
    through the definer functions: ``otp_attempts`` counts every attempt and is never reset, and a new code comes from
    ``app_reissue_claim_otp`` (at most 5 reissues, then manual review). One open claim per claimant and organisation,
    and one new claim per claimant and organisation per 24 hours (trigger).
    """

    __tablename__ = "org_claims"
    __table_args__ = (
        Index(
            "uq_org_claims_open_claimant_org",
            "org_id",
            "claimant_user_id",
            unique=True,
            postgresql_where=text("status IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed')"),
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "claimant_user_id"}},
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    claimant_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(CIText())
    email_address: Mapped[str] = mapped_column(CIText())
    level: Mapped[ClaimLevel] = mapped_column(pg_enum(ClaimLevel, "claim_level"))
    status: Mapped[ClaimStatus] = mapped_column(pg_enum(ClaimStatus, "claim_status"))
    otp_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    otp_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    otp_reissues: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    otp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dns_token: Mapped[str | None] = mapped_column(String(64))
    dns_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # E2 facts (docs/spec/06 6.2): checked by a person (ManualReviewVerifier); never a faked BRS/KRA call.
    registration_no: Mapped[str | None] = mapped_column(String(64))
    cr12_date: Mapped[date | None] = mapped_column(Date)
    kra_pin: Mapped[str | None] = mapped_column(String(16))
    sector_register: Mapped[str | None] = mapped_column(String(80))
    public_entity_requested: Mapped[bool] = mapped_column(Boolean, server_default="false")
    document_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)


class DirectoryInvitation(IdMixin, TimestampsMixin, Base):
    """An aggregated, content-free invitation to an E0 organisation's published role address, approved by staff
    admin (docs/spec/06 6.2: at most one per 30 days and two per lifetime; never to an opted-out organisation)."""

    __tablename__ = "directory_invitations"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = ({"info": {"tenancy": Tenancy.STAFF, "tenant_column": "org_id"}},)

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    to_address: Mapped[str] = mapped_column(CIText())
    status: Mapped[DirectoryInvitationStatus] = mapped_column(
        pg_enum(DirectoryInvitationStatus, "directory_invitation_status"),
        server_default=DirectoryInvitationStatus.PROPOSED.value,
    )
    reason: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
