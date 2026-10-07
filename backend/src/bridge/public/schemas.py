"""The public activity feed and the Explore summary as the API returns them (REQ-UX-03, P24-B).

Anonymised by construction: no field can carry a person, a handle, an organisation or private text. ``title`` is a
published problem's or Brief's title, or a published proposal's teaser title; places and niches are the reference
tables' names.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ActivityKind = Literal["problem_posted", "version_registered", "brief_opened"]
SEEDED_DOC = "True when the demo seed wrote it (a demo deployment, or a seeded example card): label it so"


class ActivityItem(BaseModel):
    id: str = Field(description="An opaque key for this event, stable between reads (not a record id)")
    kind: ActivityKind
    at: datetime
    county: str | None = Field(description="The county's name, when the problem or proposal names one")
    niche: str | None = Field(description='The niche label, e.g. "ICT › Networks & Telecommunications"')
    title: str | None = Field(description="Only a title that is already public: a published problem, Brief or teaser")
    stage: str | None = Field(description="Always null for now: engagement stage events are deferred")
    seeded: bool = Field(description=SEEDED_DOC)


class ActivityFeed(BaseModel):
    generated_at: datetime = Field(description="The platform clock when this feed was read (it is cached for 60 s)")
    items: list[ActivityItem] = Field(description="The 20 latest public events, newest first")
    seeded: bool = Field(description="True when there are events and every one of them is seeded")


class ExploreTeaser(BaseModel):
    id: UUID = Field(description="The problem's id")
    title: str
    niche: str | None = Field(description="The problem's niche label")
    posted_at: datetime | None = Field(description="When it was published")


class ExploreTotals(BaseModel):
    problems: int = Field(description="Published problems anyone may read")
    counties: int = Field(description="Counties with at least one of them")
    niches: int = Field(description="Top-level niches with at least one of them")


class ExploreCounty(BaseModel):
    code: str = Field(description="ISO 3166-2 code")
    name: str
    count: int
    newest: list[ExploreTeaser] = Field(description="Its three newest problems")


class ExploreNiche(BaseModel):
    id: UUID = Field(description="The top-level niche's id")
    name: str
    count: int = Field(description="Problems in the niche or any niche under it")
    newest: list[ExploreTeaser] = Field(description="Its three newest problems")


class Explore(BaseModel):
    totals: ExploreTotals
    counties: list[ExploreCounty] = Field(description="Counties with problems, most first (then by name)")
    niches: list[ExploreNiche] = Field(description="Top-level niches with problems, most first (then by name)")
    seeded: bool = Field(description="True when there are problems and every one of them is seeded")
