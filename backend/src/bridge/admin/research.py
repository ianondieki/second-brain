"""The research admin API (REQ-RES-01, REQ-ADM-01; docs/spec/06 6.5; PLAN §8 P11): ``/api/admin/research/*``.

Every route needs a staff admin whose TOTP is enrolled and whose second factor is fresh (``bridge.admin.deps``: 404
for everyone else, 403 for staff without the admin role, 403 ``step_up_required`` for an old second factor); the
database repeats the rule (``research_runs`` and ``app_create_research_candidate`` are staff admin only, candidates are
readable by staff only).

- ``GET /sources``: the saved excerpts (URL, publisher, type, dates, verbatim quote) with their freshness today and
  the source allowlists. Nothing is fetched: the excerpts were fetched once at build time (D-38).
- ``POST /runs`` ``{niche, country}``: 202, a running run started by the caller and a queued ``research.run`` job
  (the transactional outbox: the job exists if and only if the run does). 422 ``no_saved_excerpts`` or
  ``unknown_niche``; 409 ``run_in_progress`` while a run of that niche is running.
- ``GET /runs`` (newest first) and ``GET /runs/{run_id}``: status, counts, cost, stop reason, demo-fallback flag.
- ``GET /candidates``: research cards awaiting review, with sources, named organisations and the D-45 checklist
  placeholder.
- ``POST /candidates/{problem_id}/decision`` ``{decision, checklist_confirmed}``: the publish checks in code, then
  ``app_moderate_problem`` (``bridge.problems.research.review``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.admin.deps import StaffAdmin
from bridge.auth.deps import Db
from bridge.directory.models import Niche
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.models.enums import ModerationState, ProblemStatus, ResearchRunStatus
from bridge.problems.models import ResearchRun
from bridge.problems.research import review
from bridge.problems.research.pipeline import RunRefused, clock_now, nairobi_date, start_run
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import Excerpt, Freshness, freshness, get_catalogue
from bridge.problems.research.tasks import defer_run

router = APIRouter(prefix="/api/admin/research", tags=["admin"], responses=ERROR_RESPONSES)

NicheSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)]
_RUN_REFUSALS = {
    "no_saved_excerpts": (422, "There are no saved excerpts for this niche and country."),
    "unknown_niche": (422, "There is no niche with this slug."),
    "run_in_progress": (409, "A research run of this niche is already running."),
}


class AllowedDomainOut(BaseModel):
    country: str
    domain: str
    publisher: str
    official: bool


class ExcerptOut(BaseModel):
    id: str
    niche: str
    country: str
    url: str
    publisher: str
    source_type: str
    official: bool = Field(description="An allowlisted government or regulator domain")
    published_date: date
    retrieved_at: date
    quote: str
    topic: str
    freshness: Freshness = Field(description="Archived excerpts are never sent or counted")


class SourcesOut(BaseModel):
    as_of: date
    allowlist: list[AllowedDomainOut]
    excerpts: list[ExcerptOut]


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    niche: NicheSlug
    country: Literal["KE"] = "KE"


class RunOut(BaseModel):
    id: UUID
    niche: str | None
    country: str
    county_code: str | None
    status: ResearchRunStatus
    started_by: UUID
    created_at: datetime
    finished_at: datetime | None
    searches: int
    fetches: int
    input_tokens: int
    candidates: int
    discarded: int
    cost_usd: Decimal
    stop_reason: str | None
    demo_fallback: bool


class RunList(BaseModel):
    items: list[RunOut]


class SourceOut(BaseModel):
    url: str
    publisher: str | None
    source_type: str | None
    published_date: date | None
    retrieved_at: datetime
    quote: str | None
    excerpt_ref: str | None


class CandidateOut(BaseModel):
    id: UUID
    title: str
    statement: str
    affected_group: str
    niche: str | None
    country: str
    county_code: str | None
    confidence: Decimal | None
    research_run_id: UUID | None
    created_at: datetime
    seeded_example: bool
    named_orgs: list[str]
    checklist: list[str] = Field(description="D-45 checklist placeholder, shown when the card names organisations")
    sources: list[SourceOut]


class CandidateList(BaseModel):
    items: list[CandidateOut]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    checklist_confirmed: bool = Field(default=False, description="Required to approve a card naming organisations")


class DecisionOut(BaseModel):
    id: UUID
    status: ProblemStatus
    moderation_state: ModerationState


def _excerpt_out(excerpt: Excerpt, as_of: date) -> ExcerptOut:
    return ExcerptOut(
        id=excerpt.id,
        niche=excerpt.niche,
        country=excerpt.country,
        url=excerpt.url,
        publisher=excerpt.publisher,
        source_type=excerpt.source_type,
        official=excerpt.official,
        published_date=excerpt.published_date,
        retrieved_at=excerpt.retrieved_at,
        quote=excerpt.quote,
        topic=excerpt.topic,
        freshness=freshness(excerpt, as_of, get_research_policy()),
    )


@router.get("/sources")
async def research_sources(staff: StaffAdmin, db: Db) -> SourcesOut:
    catalogue = get_catalogue()
    as_of = nairobi_date(await clock_now(db))
    return SourcesOut(
        as_of=as_of,
        allowlist=[
            AllowedDomainOut(country=a.country, domain=d.domain, publisher=d.publisher, official=d.official)
            for a in catalogue.allowlists.values()
            for d in a.domains
        ],
        excerpts=[_excerpt_out(e, as_of) for e in catalogue.excerpts],
    )


async def _runs(db: AsyncSession, run_id: UUID | None = None) -> list[RunOut]:
    stmt = select(ResearchRun, Niche.slug).outerjoin(Niche, Niche.id == ResearchRun.niche_id)
    if run_id is not None:
        stmt = stmt.where(ResearchRun.id == run_id)
    stmt = stmt.order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc()).limit(100)
    return [
        RunOut(
            id=run.id,
            niche=slug,
            country=run.country,
            county_code=run.county_code,
            status=run.status,
            started_by=run.started_by,
            created_at=run.created_at,
            finished_at=run.finished_at,
            searches=run.searches,
            fetches=run.fetches,
            input_tokens=run.input_tokens,
            candidates=run.candidates,
            discarded=run.discarded,
            cost_usd=run.cost_usd,
            stop_reason=run.stop_reason,
            demo_fallback=run.demo_fallback,
        )
        for run, slug in (await db.execute(stmt)).all()
    ]


@router.post("/runs", status_code=202)
async def start_research_run(body: RunIn, staff: StaffAdmin, db: Db) -> RunOut:
    user_id = staff.live.user.id
    try:
        run = await start_run(
            db, user_id=user_id, niche_slug=body.niche, country=body.country, catalogue=get_catalogue()
        )
    except RunRefused as refused:
        await db.rollback()
        status, message = _RUN_REFUSALS[refused.code]
        raise ApiError(status, refused.code, message) from None
    await defer_run(db, run_id=run.id, user_id=user_id)
    await db.commit()
    [out] = await _runs(db, run.id)
    return out


@router.get("/runs")
async def list_research_runs(staff: StaffAdmin, db: Db) -> RunList:
    return RunList(items=await _runs(db))


@router.get("/runs/{run_id}")
async def get_research_run(run_id: UUID, staff: StaffAdmin, db: Db) -> RunOut:
    found = await _runs(db, run_id)
    if not found:
        raise not_found("No such research run.")
    return found[0]


@router.get("/candidates")
async def research_candidates(
    staff: StaffAdmin, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 200
) -> CandidateList:
    return CandidateList(
        items=[
            CandidateOut(
                id=c.id,
                title=c.title,
                statement=c.statement,
                affected_group=c.affected_group,
                niche=c.niche,
                country=c.country,
                county_code=c.county_code,
                confidence=c.confidence,
                research_run_id=c.research_run_id,
                created_at=c.created_at,
                seeded_example=c.seeded_example,
                named_orgs=list(c.named_orgs),
                checklist=list(c.checklist),
                sources=[
                    SourceOut(
                        url=s.url,
                        publisher=s.publisher,
                        source_type=s.source_type,
                        published_date=s.published_date,
                        retrieved_at=s.retrieved_at,
                        quote=s.quote,
                        excerpt_ref=s.excerpt_ref,
                    )
                    for s in c.sources
                ],
            )
            for c in (await review.list_candidates(db))[:limit]
        ]
    )


@router.post("/candidates/{problem_id}/decision")
async def decide_research_candidate(problem_id: UUID, body: DecisionIn, staff: StaffAdmin, db: Db) -> DecisionOut:
    result = await review.decide(
        db,
        staff_id=staff.live.user.id,
        problem_id=problem_id,
        decision=body.decision,
        checklist_confirmed=body.checklist_confirmed,
        catalogue=get_catalogue(),
        policy=get_research_policy(),
    )
    return DecisionOut(id=result.id, status=result.status, moderation_state=result.moderation_state)
