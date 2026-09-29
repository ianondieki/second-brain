"""Problems API (REQ-PROP-01; docs/spec/06 6.3): ``GET /api/problems``, the editor's linked-Problem picker.
Signed-in users only; published problems clear of moderation, newest first, filtered by niche (a parent niche includes
its children) and by text in the title or statement."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES
from bridge.problems import service
from bridge.proposals.schemas import ProblemRef

router = APIRouter(prefix="/api/problems", tags=["problems"], responses=ERROR_RESPONSES)
NO_NUL = r"^[^\x00]*$"


class ProblemCard(ProblemRef):
    statement: str
    published_at: datetime | None


class ProblemPage(BaseModel):
    items: list[ProblemCard]


@router.get("")
async def list_problems(
    live: CurrentSession,
    db: Db,
    niche: Annotated[str | None, Query(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100, pattern=NO_NUL)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> ProblemPage:
    rows = await service.list_published(
        db, niche=niche, q=(q.strip() or None) if q else None, limit=limit, offset=offset
    )
    return ProblemPage(
        items=[
            ProblemCard(**ref.model_dump(), statement=statement, published_at=published_at)
            for ref, statement, published_at in rows
        ]
    )
