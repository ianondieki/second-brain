"""Problems API (REQ-PROP-01, REQ-RES-01, REQ-RES-02; docs/spec/06 6.3, 6.5). Signed-in users only.

- ``GET /api/problems``: the editor's linked-Problem picker and the problem list: published problems clear of
  moderation, newest first, filtered by niche (a parent niche includes its children), country, county (AC-RES-4) and
  text in the title or statement; paged with ``limit``, ``cursor`` and ``next_cursor`` (``bridge.pagination``).
- ``GET /api/problems/{problem_id}``: one published, clear problem card with its cited sources (URL, publisher, source
  type, dates, verbatim quote) and its label: "AI-drafted, human-reviewed on <date>" for a research card
  (``[[COPY-REVIEW]]``; a card the demo seed made says so instead), "Developer-reported" for a developer's, "Posted
  by <organisation>" for a Problem Brief, which also carries ``brief`` (the organisation, budget band and deadline,
  whether it is open and, when not, why: ``ended``, decided on the platform's day; REQ-DIR-05). Anything else, a
  research ``candidate`` or a Brief under review included (AC-RES-2), is 404.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from bridge import pagination
from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, not_found
from bridge.models.enums import BriefStatus
from bridge.problems import brief_rules, briefs, service
from bridge.problems.brief_schemas import BriefFacts
from bridge.proposals.schemas import ProblemRef

router = APIRouter(prefix="/api/problems", tags=["problems"], responses=ERROR_RESPONSES)
NO_NUL = r"^[^\x00]*$"
COUNTRY = r"^[A-Z]{2}$"
COUNTY = r"^[A-Z]{2}-[A-Z0-9]{1,5}$"


class ProblemCard(ProblemRef):
    statement: str


class ProblemPage(BaseModel):
    items: list[ProblemCard]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")


class CitationOut(BaseModel):
    url: str
    publisher: str | None
    source_type: str | None
    published_date: date | None
    retrieved_at: datetime
    quote: str | None


class ProblemDetail(ProblemCard):
    affected_group: str | None
    country: str
    county_code: str | None
    ai_generated: bool = Field(description="A model drafted the card (false for a demo seed card, written in code)")
    confidence: Decimal | None
    named_orgs: list[str]
    citations: list[CitationOut]
    brief: BriefFacts | None = Field(
        default=None, description="A Problem Brief's organisation, budget band and deadline; null for other problems"
    )


@router.get("")
async def list_problems(
    live: CurrentSession,
    db: Db,
    niche: Annotated[str | None, Query(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)] = None,
    country: Annotated[str | None, Query(pattern=COUNTRY)] = None,
    county: Annotated[str | None, Query(pattern=COUNTY)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100, pattern=NO_NUL)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: pagination.Cursor = None,
) -> ProblemPage:
    rows = await service.list_published(
        db,
        niche=niche,
        q=(q.strip() or None) if q else None,
        limit=limit + 1,
        after=pagination.decode(cursor),
        country=country,
        county=county,
    )
    last = rows[limit - 1] if len(rows) > limit else None
    return ProblemPage(
        items=[ProblemCard(**ref.model_dump(), statement=statement) for ref, statement, _ in rows[:limit]],
        next_cursor=None if last is None else pagination.encode(last[2], last[0].id),
    )


@router.get("/{problem_id}")
async def get_problem(problem_id: UUID, live: CurrentSession, db: Db) -> ProblemDetail:
    found = await service.get_published(db, problem_id)
    if found is None:
        raise not_found("No such problem.")
    ref, row, citations = found
    brief = None
    if row.brief_status is not None:
        status, today = BriefStatus(row.brief_status), await briefs.today(db)
        brief = brief_rules.facts(ref.org, row.budget_band, row.deadline, status=status, today=today)
    return ProblemDetail(
        **ref.model_dump(),
        statement=row.statement,
        affected_group=row.affected_group,
        country=row.country,
        county_code=row.county_code,
        ai_generated=row.ai_generated and not row.seeded_example,  # a seeded card was written by hand
        confidence=row.confidence,
        named_orgs=list(row.named_orgs or ()),
        citations=[
            CitationOut(
                url=c.url,
                publisher=c.publisher,
                source_type=c.source_type,
                published_date=c.published_date,
                retrieved_at=c.retrieved_at,
                quote=c.quote,
            )
            for c in citations
        ],
        brief=brief,
    )
