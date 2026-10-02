"""Problem Brief API shapes (REQ-DIR-05; docs/spec/06 6.2, 6.5).

A Brief is a ProblemCard an organisation posts (``source = org_brief``): title, statement, affected group, niche and
county, plus the Brief's own optional budget band (a code from ``config/matching/weights_v1.yaml``) and deadline.
What developers read names the organisation (``OrgRef``: id, slug, directory name) and never a person: no author, no
member, no contact. The organisation's own shapes add the moderation facts and the plan's count.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bridge.matching.schemas import BudgetBandOut
from bridge.models.enums import BriefStatus, BriefVisibility, ModerationState, ProblemStatus
from bridge.proposals.schemas import NicheOut, OrgRef

# The request models refuse only absurd sizes; the Brief's own limits (90, 1,200 and 200 characters after cleaning)
# answer 422 ``invalid_brief`` with a code per field (``bridge.problems.briefs``).
RAW_CAP = 2_000
RAW_CAP_STATEMENT = 10_000
BriefState = Literal["in_review", "published", "rejected", "closed"]


class BriefFacts(BaseModel):
    """What a developer reads about a Brief beside its problem card."""

    org: OrgRef | None = Field(description="The organisation that posted it; null when it is not in the directory")
    budget_band: BudgetBandOut | None = Field(description="The organisation's budget band; null when it gave none")
    deadline: date | None = Field(description="Proposals wanted by this day (Africa/Nairobi); null when none")


class BriefIn(BaseModel):
    """A new Brief. Plain text only (markup is removed) and no contact details: a Brief is public once approved."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=RAW_CAP, description="At most 90 characters")
    statement: str = Field(
        min_length=1, max_length=RAW_CAP_STATEMENT, description="At most 120 words and 1,200 characters"
    )
    affected_group: str | None = Field(default=None, max_length=RAW_CAP, description="Who has the problem (<= 200)")
    niche_id: UUID
    county_code: str | None = Field(default=None, pattern=r"^KE-\d{2}$", description="Null: nationwide")
    budget_band: str | None = Field(default=None, max_length=32, description="A code from the list's budget_bands")
    deadline: date | None = Field(default=None, description="Today or later (Africa/Nairobi)")
    visibility: BriefVisibility = Field(
        default=BriefVisibility.PUBLIC,
        description="public only for now: invited answers 422 visibility_not_available",
    )


class BriefPatch(BaseModel):
    """Change the budget band or the deadline of a Brief that is not closed (``null`` clears it). The moderated text
    does not change after posting."""

    model_config = ConfigDict(extra="forbid")

    budget_band: str | None = Field(default=None, max_length=32)
    deadline: date | None = None


class BriefOut(BaseModel):
    """One of the organisation's Briefs, as its members see it."""

    id: UUID = Field(description="The Brief's problem id (its page is GET /api/problems/{id} once published)")
    title: str
    statement: str
    affected_group: str | None
    niche: NicheOut | None
    country: str
    county_code: str | None
    visibility: BriefVisibility
    budget_band: BudgetBandOut | None
    deadline: date | None
    status: BriefStatus = Field(description="The Brief's own status: closed once the organisation closes it")
    problem_status: ProblemStatus = Field(description="pending_review until staff decide; published or rejected")
    moderation_state: ModerationState
    state: BriefState = Field(
        description="What to show: in_review (waiting for staff, or held), published (on Discover), rejected, closed"
    )
    proposal_count: int = Field(description="Published proposals that link this Brief")
    created_at: datetime
    published_at: datetime | None = Field(description="When staff approved it (null until then)")


class BriefPlanOut(BaseModel):
    plan: str
    problem_briefs: int | None = Field(description="Open Briefs the plan allows; null means unlimited")
    used: int = Field(description="Open Briefs now: not closed, deadline not passed, not rejected")


class BriefList(BaseModel):
    items: list[BriefOut] = Field(description="Newest first, every status")
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")
    plan: BriefPlanOut
    budget_bands: list[BudgetBandOut] = Field(description="The budget band codes a Brief may carry")
