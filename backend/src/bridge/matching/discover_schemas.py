"""Response bodies of Discover and "Recommended for you" (REQ-TREND-02, REQ-PERS-01, REQ-PERS-03, REQ-DIR-05). Tier 1
and public facts only: no Tier-2 field, no organisation count on a project, and no organisation name or id except the
one that posted a Problem Brief (its own public "Posted by", ``ProblemRef.org``)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bridge.problems.brief_schemas import BriefFacts
from bridge.proposals.schemas import NicheOut, ProblemRef
from bridge.proposals.serializers import TeaserItem


class DiscoverProblem(ProblemRef):
    statement: str
    country: str
    county_code: str | None


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


class DiscoverBrief(BaseModel):
    problem: DiscoverProblem = Field(description="The Brief's problem card ('Posted by <organisation>', with org)")
    brief: BriefFacts
    proposal_count: int = Field(description="Published proposals that link this Brief")


class DiscoverBriefsOut(BaseModel):
    items: list[DiscoverBrief] = Field(description="Published, open Briefs, newest first")
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")


class OpportunityGapOut(BaseModel):
    generated_at: datetime
    items: list[TrendingProblem] = Field(description="Top-decile trending problems with fewer than 3 proposals")


class FeatureOut(BaseModel):
    raw: float | None = Field(description="The fact behind the feature (f5: the trend z-score; f6: the confidence)")
    value: float | None = Field(description="Normalised to 0-1; null when the feature does not apply")
    weight: float
    applies: bool
    source: Literal["embedding", "keywords"] | None = Field(
        default=None, description="f1 only: how it was computed (embedding or keywords); null when it does not apply"
    )


class FeaturesOut(BaseModel):
    """The feature vector f1-f10 behind a score (docs/spec/06 6.7)."""

    semantic_fit: FeatureOut = Field(
        description="f1 (consent only): the cosine of your profile's and the card's embeddings (raw; the value is"
        " max(0, raw)), else the keywords shared with your profile and proposals (raw: their count)"
    )
    niche_match: FeatureOut = Field(description="f2: liked 1, adjacent 0.5")
    region_match: FeatureOut = Field(description="f3: your county 1, nationwide 0.5")
    skill_coverage: FeatureOut = Field(description="f4: no data in the prototype; never applies")
    trend: FeatureOut = Field(description="f5: raw is the card's trend z-score")
    evidence_confidence: FeatureOut = Field(description="f6: raw is the card's confidence (1.0 for a Brief)")
    market_pull: FeatureOut = Field(description="f7: raw is scouting organisations + Briefs")
    crowding: FeatureOut = Field(description="f8: raw is the published proposals; negative weight")
    track_record: FeatureOut = Field(description="f9: (done + 1) / (started + 2) in the niche (consent only)")
    freshness: FeatureOut = Field(description="f10: raw is the age in days")


PursuitDecision = Literal["pursue", "consider", "not_now"]
PursuitLabel = Literal["Pursue", "Consider", "Not now"]
FitLabel = Literal["Strong fit", "Good fit", "Stretch"]


class PursuitOut(BaseModel):
    decision: PursuitDecision
    label: PursuitLabel
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
    features: FeaturesOut


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
