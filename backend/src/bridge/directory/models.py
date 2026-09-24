"""Niche taxonomy, regions and organisation niches (docs/spec/03 Organisation axes; docs/spec/08 core tables)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy
from bridge.models.enums import RegionKind
from bridge.models.types import pg_enum

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
