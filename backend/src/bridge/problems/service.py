"""Problems for the proposal editor (REQ-PROP-01; docs/spec/06 6.3): the linked-Problem picker (published problems
clear of moderation, filtered by niche and text) and "Describe a new problem", which the publish flow turns into a
Problem with ``source=developer``, published at once, labelled "Developer-reported" and queued for moderation
(``app_open_moderation_case``) without blocking the publication. Row-Level Security already limits reads to what
the signed-in user may see; the queries repeat the published-and-clear rule so a creator's own held problem is not
offered as a link or shown on a public teaser.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge.directory.models import Niche
from bridge.directory.service import niche_label
from bridge.ids import uuid7
from bridge.models.enums import ModerationState, ProblemSource, ProblemStatus
from bridge.problems.models import Problem
from bridge.proposals.models import ProposalProblem
from bridge.proposals.schemas import NicheOut, ProblemRef

LABELS: Final = {ProblemSource.DEVELOPER: "Developer-reported"}  # [[COPY-REVIEW]] docs/spec/06 6.3 wording
_Parent = aliased(Niche)


def niche_out(niche_id: UUID | None, slug: str | None, name: str | None, parent_name: str | None) -> NicheOut | None:
    if niche_id is None or slug is None or name is None:
        return None
    return NicheOut(id=niche_id, slug=slug, label=niche_label(name, parent_name))


def _published_and_clear() -> ColumnElement[bool]:
    return and_(Problem.status == ProblemStatus.PUBLISHED, Problem.moderation_state == ModerationState.CLEAR)


def _with_niche(stmt: Select[Any]) -> Select[Any]:
    return stmt.outerjoin(Niche, Niche.id == Problem.niche_id).outerjoin(_Parent, _Parent.id == Niche.parent_id)


_COLUMNS = (Problem.id, Problem.title, Problem.source, Niche.id, Niche.slug, Niche.name_en, _Parent.name_en)


def _ref(row: Any) -> ProblemRef:
    problem_id, title, source, niche_id, slug, name, parent_name = row
    return ProblemRef(
        id=problem_id,
        title=title,
        source=source,
        label=LABELS.get(source),
        niche=niche_out(niche_id, slug, name, parent_name),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_published(
    db: AsyncSession, *, niche: str | None, q: str | None, limit: int, offset: int
) -> list[tuple[ProblemRef, str, datetime | None]]:
    """Published, clear problems (picker), newest first: (reference, statement, published_at)."""
    stmt = _with_niche(select(*_COLUMNS, Problem.statement, Problem.published_at)).where(_published_and_clear())
    if niche is not None:
        stmt = stmt.where(or_(Niche.slug == niche, _Parent.slug == niche))
    if q is not None:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(or_(Problem.title.ilike(pattern, escape="\\"), Problem.statement.ilike(pattern, escape="\\")))
    stmt = stmt.order_by(Problem.published_at.desc().nulls_last(), Problem.id.desc()).limit(limit).offset(offset)
    return [(_ref(row[:7]), row[7], row[8]) for row in (await db.execute(stmt)).all()]


async def linkable(db: AsyncSession, problem_ids: Iterable[UUID]) -> set[UUID]:
    """Which of these problems may be linked: published and clear."""
    ids = list(problem_ids)
    if not ids:
        return set()
    stmt = select(Problem.id).where(Problem.id.in_(ids), _published_and_clear())
    return set((await db.execute(stmt)).scalars().all())


async def refs_for_version(db: AsyncSession, version_id: UUID, *, public: bool) -> list[ProblemRef]:
    """A version's linked problems; ``public`` keeps only published, clear ones (what every reader may see)."""
    stmt = _with_niche(select(*_COLUMNS).join(ProposalProblem, ProposalProblem.problem_id == Problem.id)).where(
        ProposalProblem.proposal_version_id == version_id
    )
    if public:
        stmt = stmt.where(_published_and_clear())
    return [_ref(row) for row in (await db.execute(stmt.order_by(Problem.title, Problem.id))).all()]


_INSERT_DEVELOPER_PROBLEM = text(
    "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, moderation_state, published_at)"
    " VALUES (:id, 'developer', :niche, :title, :statement, 'published', :user, CAST(:moderation AS moderation_state),"
    " now())"
)
_OPEN_CASE = text(
    "SELECT app_open_moderation_case(:subject_type, :subject_id, CAST(:reasons AS text[]),"
    " CAST(:source AS moderation_source), CAST(:classifier AS jsonb))"
)


async def create_developer_problem(
    db: AsyncSession, *, user_id: UUID, niche_id: UUID | None, title: str, statement: str, held: bool
) -> UUID:
    """A developer's new Problem, published at once (held instead when the pre-screen holds it)."""
    problem_id = uuid7()
    moderation = ModerationState.HELD if held else ModerationState.CLEAR
    params = {"id": problem_id, "niche": niche_id, "title": title, "statement": statement, "user": user_id}
    await db.execute(_INSERT_DEVELOPER_PROBLEM, params | {"moderation": moderation.value})
    return problem_id


async def open_case(
    db: AsyncSession, subject_type: str, subject_id: UUID, reasons: Sequence[str], classifier: str | None
) -> UUID:
    """File a rules (``regex``) moderation case about a proposal or problem; the database checks the caller."""
    params = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reasons": list(reasons),
        "source": "regex",
        "classifier": classifier,
    }
    case_id: UUID = (await db.execute(_OPEN_CASE, params)).scalar_one()
    return case_id
