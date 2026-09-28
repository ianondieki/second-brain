"""Developer profiles, niche interests, consents and developer verification (REQ-CON-01, REQ-PROV-04).
Tenancy USER: RLS by ``app.user_id``."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import ConsentPurpose, DevVerification, KycStatus, NicheInterest
from bridge.models.types import CIText, Vector, pg_enum

USER = {"info": {"tenancy": Tenancy.USER, "tenant_column": "user_id"}}


class DeveloperProfile(TimestampsMixin, Base):
    __tablename__ = "developer_profiles"
    __table_args__ = (USER,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    handle: Mapped[str] = mapped_column(CIText(), unique=True)
    verification_level: Mapped[DevVerification] = mapped_column(
        pg_enum(DevVerification, "dev_verification"), server_default=DevVerification.D0.value
    )
    headline: Mapped[str | None] = mapped_column(String(160))
    bio: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(2), server_default="KE")
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    profile_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    # docs/spec/08 Embeddings: the model and version that produced the vector, stored per row (re-embed on change).
    embed_model: Mapped[str | None] = mapped_column(String(80))
    embed_version: Mapped[str | None] = mapped_column(String(40))


class DeveloperNiche(Base):
    """Liked niches (3-5, all plans) drive ranking; followed niches (capped per plan) drive trending (docs/spec/05)."""

    __tablename__ = "developer_niches"
    __table_args__ = (USER,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    niche_id: Mapped[UUID] = mapped_column(ForeignKey("niches.id"), primary_key=True)
    kind: Mapped[NicheInterest] = mapped_column(pg_enum(NicheInterest, "niche_interest"), primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), server_default="1")


class Consent(IdMixin, CreatedMixin, Base):
    """One consent decision. Append-only (INSERT/SELECT grants only); the latest row per purpose is current."""

    __tablename__ = "consents"
    __table_args__ = (USER,)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[ConsentPurpose] = mapped_column(pg_enum(ConsentPurpose, "consent_purpose"))
    granted: Mapped[bool] = mapped_column(Boolean)
    text_version: Mapped[str] = mapped_column(String(32))
    text_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    source: Mapped[str] = mapped_column(String(32))


class PhoneVerification(IdMixin, CreatedMixin, Base):
    """A D1 phone OTP (``SmsProvider``). The app inserts a row per code sent; ``app_confirm_phone_otp`` compares the
    stored hash, counts attempts and, on a match while the profile is still D0, sets ``verified_at`` and raises the
    profile to D1. ``expires_at`` is set by the database (10 minutes after the insert; a trigger replaces any value
    sent), so leave it out and read it back."""

    __tablename__ = "phone_verifications"
    __table_args__ = (CheckConstraint(r"phone_e164 ~ '^\+[1-9][0-9]{6,14}$'", name="phone_e164"), USER)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    phone_e164: Mapped[str] = mapped_column(String(16))
    # Write-only: bridge_app holds no SELECT on it (app_confirm_phone_otp compares it in SQL). Never loaded; reading the
    # attribute of a loaded row raises. HMAC-SHA-256 under SECRET_KEY (bridge.profiles.verification.otp_digest).
    otp_hash: Mapped[bytes] = mapped_column(LargeBinary, deferred=True, deferred_raiseload=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(now() + '00:10:00'::interval)")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KycReview(IdMixin, TimestampsMixin, Base):
    """A D2 KYC review (``KycProvider``; ``ManualReview`` by staff admin in Release 1). Stores only the outcome:
    reference, verified legal name, ID type, last four digits, ``is_adult`` and the result. ID images live in the
    separate ``kyc-review`` bucket under keys derived from this row's id, never in a column, a log or an audit event,
    and are purged 72 h after the decision (``purge_due_at``). Decisions go through ``app_decide_kyc`` only."""

    __tablename__ = "kyc_reviews"
    __table_args__ = (CheckConstraint("id_last4 IS NULL OR id_last4 ~ '^[0-9A-Za-z]{4}$'", name="id_last4"), USER)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[KycStatus] = mapped_column(
        pg_enum(KycStatus, "kyc_status"), server_default=KycStatus.SUBMITTED.value
    )
    reference: Mapped[str | None] = mapped_column(String(120))
    verified_legal_name: Mapped[str | None] = mapped_column(String(200))
    id_type: Mapped[str | None] = mapped_column(String(24))
    id_last4: Mapped[str | None] = mapped_column(String(4))
    is_adult: Mapped[bool | None] = mapped_column(Boolean)
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    images_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
