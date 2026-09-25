"""Developer profiles, niche interests and consents (REQ-CON-01). Tenancy USER: RLS by ``app.user_id``."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import ConsentPurpose, DevVerification, NicheInterest
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
