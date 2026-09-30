"""Response bodies of Discover and "Recommended for you" (REQ-TREND-02, REQ-PERS-01, REQ-PERS-03). Tier 1 and
public facts only: no Tier-2 field, no organisation name or id, and no organisation count on a project."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bridge.proposals.schemas import NicheOut, ProblemRef
from bridge.proposals.serializers import TeaserItem


class DiscoverProblem(ProblemRef):
    statement: str
    country: str
    county_code: str | None
    published_at: datetime | None


class DiscoverSource(BaseModel):
    url: str
    publisher: str | None
    source_type: str | None
    published_date: date | None
    retrieved_at: datetime
    quote: str | None


class TrendOut(BaseModel):
    trending: bool
    new_this_week: bool
    z: float | None = Field(description="z-score against the niche's 90-day baseline; null while the niche has none")
    score: float = Field(description="The decayed trend score behind the z-score")
    badge: str | None = Field(description="Shown only when trending, e.g. 'Trending in ICT › Fintech · Kenya: ...'")


class ProjectTrendOut(BaseModel):
    trending: bool
    new_this_week: bool
    badge: str | None = Field(description="Shown only when trending; never an organisation count or name")


class TrendingProblem(BaseModel):
    problem: DiscoverProblem
    trend: TrendOut
    why: list[str] = Field(description="Why chips written in code, at most 3")
    sources: list[DiscoverSource] = Field(description="The newest cited sources")
    proposal_count: int = Field(description="Published proposals that link this problem")
    project_ids: list[UUID] = Field(description="Trending projects (in `projects`) that solve this problem")


class TrendingProject(BaseModel):
    proposal: TeaserItem
    problem: ProblemRef = Field(description="The problem it solves (always present)")
    trend: ProjectTrendOut
    why: list[str]


class TrendingOut(BaseModel):
    generated_at: datetime
    problems: list[TrendingProblem]
    projects: list[TrendingProject]


class OpportunityGapOut(BaseModel):
    generated_at: datetime
    items: list[TrendingProblem] = Field(description="Top-decile trending problems with fewer than 3 proposals")


class FeatureOut(BaseModel):
    raw: float | None = Field(description="The fact behind the feature (f5: the trend z-score; f6: the confidence)")
    value: float | None = Field(description="Normalised to 0-1; null when the feature does not apply")
    weight: float
    applies: bool


PursuitDecision = Literal["pursue", "consider", "not_now"]
FitLabel = Literal["Strong fit", "Good fit", "Stretch"]


class PursuitOut(BaseModel):
    decision: PursuitDecision
    label: str
    reasons: list[str] = Field(min_length=1)


class Recommendation(BaseModel):
    problem: DiscoverProblem
    position: int
    score: int = Field(ge=0, le=100)
    label: FitLabel
    exploring: bool = Field(description="The exploration slot: a card outside your liked niches")
    pursuit: PursuitOut
    why: list[str] = Field(min_length=1)
    why_not: str | None
    trend: TrendOut
    features: dict[str, FeatureOut] = Field(description="The feature vector f1-f10 behind the score")


class RecommendationsOut(BaseModel):
    generated_at: datetime
    ranker_version: str
    personalised: bool = Field(description="False without the profiling consent: liked niches and public facts only")
    liked_niches: list[NicheOut]
    items: list[Recommendation]


class LikedNichesOut(BaseModel):
    liked: list[NicheOut]
    min: int
    max: int


class LikedNichesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    liked: list[UUID] = Field(max_length=20, description="The niche ids you like (3 to 5)")
