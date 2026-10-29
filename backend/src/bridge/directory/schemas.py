"""Directory API shapes (REQ-DIR-01, REQ-DIR-02; docs/spec/06 6.2).

A card carries the name, niches, org type, county and verification badge, and the responsiveness score only when its
rules hold. Never a logo, a website, a domain or any contact (AC-DIR-3): the models below are the whole card.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from bridge.models.enums import OrgKind

BadgeLevel = Literal["e0", "e1", "e2"]


class NicheRef(BaseModel):
    id: UUID
    slug: str
    label: str = Field(description="Two-level label, e.g. 'ICT › Networks & Telecommunications'")


class CountyRef(BaseModel):
    code: str = Field(description="ISO 3166-2:KE code, e.g. KE-30")
    name: str


class Badge(BaseModel):
    level: BadgeLevel
    text: str = Field(description="Approved badge copy, shown verbatim")


class Responsiveness(BaseModel):
    """E2 only, once there are at least 10 eligible tags and 60 days have passed since E2 verification."""

    median_days: int
    answered_pct: int
    text: str


class OrgCard(BaseModel):
    id: UUID
    slug: str
    name: str
    kind: OrgKind
    niches: list[NicheRef]
    county: CountyRef | None
    badge: Badge
    responsiveness: Responsiveness | None


class DirectoryGroup(BaseModel):
    niche: NicheRef | None = Field(description="The heading; null groups organisations without a niche (last)")
    orgs: list[OrgCard]


class DirectoryPage(BaseModel):
    groups: list[DirectoryGroup]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")


class NicheChild(BaseModel):
    id: UUID
    slug: str
    name: str
    label: str
    isic_code: str | None


class NicheNode(NicheChild):
    children: list[NicheChild]


class OrgTypeOption(BaseModel):
    value: OrgKind
    label: str


class FilterOptions(BaseModel):
    org_types: list[OrgTypeOption]
    counties: list[CountyRef]
