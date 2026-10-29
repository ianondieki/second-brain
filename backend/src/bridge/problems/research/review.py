"""Staff review of research candidates (REQ-RES-01; docs/spec/06 6.5 "mandatory moderator approval"; AC-RES-1; D-45).

``list_candidates`` shows every research card still a ``candidate`` (staff only under RLS), with its cited sources,
the organisations it names and, when it names any, the D-45 checklist placeholder (default (a): the checklist wording
comes with the G2 legal pack; the admin confirms the placeholder and sees the names).

``decide`` approves or rejects one candidate, serialised per card (a transaction-scoped advisory lock: two decisions
never both pass the ``candidate`` check). Approval first runs the publish checks in code (``publish_violation``):

- every source is a saved excerpt (``excerpt_ref``, ``example:`` prefix allowed for the demo seed's cards) whose URL
  host is on the allowlist and whose URL, publisher, type, date and quote are exactly the saved ones (the quote is
  compared verbatim, AC-RES-1);
- at least one source is not archived today (docs/spec/06 6.5 freshness), and only those count below;
- the card's numbers are inside those quotes, a named organisation has an official source, and the sources hold one
  official source or two independent publishers (``checks.rule_violation``); the stored confidence is at least
  ``discard_below``;
- a card naming organisations needs ``checklist_confirmed`` (409 ``checklist_required``).

Then ``app_moderate_problem(id, 'clear', 'published')`` (the same staff admin may approve: ``created_by`` is NULL),
whose AC-RES-1 backstop refusal is 409 too. Rejection is ``app_moderate_problem(id, 'rejected', 'rejected')``. Each
decision is audited on the staff member's chain (``research.candidate_decided``: ids, the decision, the count of
named organisations and whether the checklist was confirmed).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.errors import ApiError, not_found
from bridge.models.enums import AuditActor, ModerationState, ProblemStatus
from bridge.problems.research import checks
from bridge.problems.research.pipeline import EXAMPLE_REF_PREFIX, clock_now, nairobi_date
from bridge.problems.research.policy import ResearchPolicy
from bridge.problems.research.sources import Catalogue, Excerpt, Freshness, freshness

Decision = Literal["approve", "reject"]
# [[COPY-REVIEW]] D-45 default (a): a placeholder until the G2 legal pack supplies the checklist wording.
CHECKLIST_PLACEHOLDER: Final = (
    "Checklist placeholder (D-45): this card names an organisation. The review checklist wording comes with the legal"
    " pack; confirm you have read the named organisations and every cited quote."
)
_LOCK: Final = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_CARD: Final = text(
    "SELECT p.id, p.source::text AS source, p.status::text AS status, p.title, p.statement,"
    " coalesce(p.affected_group, '') AS affected_group, p.named_orgs, p.confidence, p.country, p.county_code,"
    " p.research_run_id, p.niche_id, p.created_at FROM problems p WHERE p.id = :id"
)
_CANDIDATES: Final = text(
    "SELECT p.id, p.title, p.statement, coalesce(p.affected_group, '') AS affected_group, p.named_orgs, p.confidence,"
    " p.country, p.county_code, p.research_run_id, n.slug::text AS niche, p.created_at FROM problems p"
    " LEFT JOIN niches n ON n.id = p.niche_id"
    " WHERE p.source = 'research_agent' AND p.status = 'candidate' ORDER BY p.created_at, p.id LIMIT 200"
)
_SOURCES: Final = text(
    "SELECT problem_id, url, publisher, source_type, published_date, retrieved_at, quote, excerpt_ref"
    " FROM problem_sources WHERE problem_id = ANY(:ids) ORDER BY published_date DESC NULLS LAST, url, id"
)
_MODERATE: Final = text(
    "SELECT app_moderate_problem(:id, CAST(:state AS moderation_state), CAST(:status AS problem_status))"
)


@dataclass(frozen=True, slots=True)
class StoredSource:
    url: str
    publisher: str | None
    source_type: str | None
    published_date: date | None
    retrieved_at: datetime
    quote: str | None
    excerpt_ref: str | None

    @property
    def excerpt_id(self) -> str | None:
        ref = self.excerpt_ref
        if ref is None:
            return None
        return ref.removeprefix(EXAMPLE_REF_PREFIX)

    @property
    def seeded_example(self) -> bool:
        return self.excerpt_ref is not None and self.excerpt_ref.startswith(EXAMPLE_REF_PREFIX)


@dataclass(frozen=True, slots=True)
class Candidate:
    id: UUID
    title: str
    statement: str
    affected_group: str
    named_orgs: tuple[str, ...]
    confidence: Decimal | None
    country: str
    county_code: str | None
    research_run_id: UUID | None
    niche: str | None
    created_at: datetime
    sources: tuple[StoredSource, ...]

    @property
    def seeded_example(self) -> bool:
        return bool(self.sources) and all(s.seeded_example for s in self.sources)

    @property
    def checklist(self) -> tuple[str, ...]:
        return (CHECKLIST_PLACEHOLDER,) if self.named_orgs else ()


@dataclass(frozen=True, slots=True)
class DecisionResult:
    id: UUID
    status: ProblemStatus
    moderation_state: ModerationState


async def sources_of(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, tuple[StoredSource, ...]]:
    found: dict[UUID, list[StoredSource]] = {i: [] for i in ids}
    if ids:
        for row in (await db.execute(_SOURCES, {"ids": list(ids)})).all():
            found[row.problem_id].append(
                StoredSource(
                    row.url,
                    row.publisher,
                    row.source_type,
                    row.published_date,
                    row.retrieved_at,
                    row.quote,
                    row.excerpt_ref,
                )
            )
    return {key: tuple(value) for key, value in found.items()}


async def list_candidates(db: AsyncSession) -> list[Candidate]:
    rows = (await db.execute(_CANDIDATES)).all()
    sources = await sources_of(db, [r.id for r in rows])
    return [
        Candidate(
            id=r.id,
            title=r.title,
            statement=r.statement,
            affected_group=r.affected_group,
            named_orgs=tuple(r.named_orgs or ()),
            confidence=r.confidence,
            country=r.country,
            county_code=r.county_code,
            research_run_id=r.research_run_id,
            niche=r.niche,
            created_at=r.created_at,
            sources=sources[r.id],
        )
        for r in rows
    ]


def _saved(source: StoredSource, catalogue: Catalogue) -> Excerpt | None:
    """The saved excerpt a stored source is, exactly (URL on the allowlist, publisher, type, date, verbatim quote)."""
    excerpt_id = source.excerpt_id
    excerpt = None if excerpt_id is None else catalogue.get(excerpt_id)
    if excerpt is None:
        return None
    allowlist = catalogue.allowlists.get(excerpt.country)
    domain = None if allowlist is None else allowlist.domain_of(source.url)
    same = (
        domain is not None
        and source.url == excerpt.url
        and source.publisher == excerpt.publisher == domain.publisher
        and source.source_type == excerpt.source_type
        and source.published_date == excerpt.published_date
        and source.quote == excerpt.quote
    )
    return excerpt if same else None


def publish_violation(
    card: Mapping[str, Any], stored: Sequence[StoredSource], catalogue: Catalogue, policy: ResearchPolicy, as_of: date
) -> tuple[str | None, tuple[str, ...]]:
    """(why the candidate may not be published or None, the organisations it names)."""
    allowlist = catalogue.allowlists.get(str(card["country"]))
    if allowlist is None:
        return "no_allowlist", ()
    cleaned = checks.clean_text(card["title"], card["statement"], card["affected_group"], card["named_orgs"] or ())
    if isinstance(cleaned, str):
        return cleaned, ()
    names = checks.named_organisations(cleaned.fields, cleaned.named_orgs, allowlist)
    if not stored:
        return "no_citation", names
    excerpts = [_saved(source, catalogue) for source in stored]
    if any(e is None for e in excerpts):
        return "source_not_saved", names
    live = [e for e in excerpts if e is not None and freshness(e, as_of, policy) is not Freshness.ARCHIVED]
    if not live:
        return "sources_archived", names
    text_now = checks.CardText(cleaned.title, cleaned.statement, cleaned.affected_group, names)
    violation = checks.rule_violation(text_now, live)
    if violation is not None:
        return violation, names
    score = card["confidence"]
    if score is None or Decimal(score) < policy.discard_below:
        return "low_confidence", names
    return None, names


def _refusal(exc: DBAPIError) -> ApiError | None:
    sqlstate = str(getattr(exc.orig, "sqlstate", None))
    if sqlstate == "23514":  # problems_research_guard: the AC-RES-1 backstop
        return ApiError(409, "publish_check_failed", "This card cannot be published: needs_official_or_two_publishers.")
    if sqlstate in ("42501", "P0002"):  # the staff check, or no such problem
        return not_found()
    return None


async def decide(
    db: AsyncSession,
    *,
    staff_id: UUID,
    problem_id: UUID,
    decision: Decision,
    checklist_confirmed: bool,
    catalogue: Catalogue,
    policy: ResearchPolicy,
) -> DecisionResult:
    """Approve or reject one research candidate (see the module docstring); commits."""
    await db.execute(_LOCK, {"key": f"research-decision:{problem_id}"})
    card = (await db.execute(_CARD, {"id": problem_id})).mappings().one_or_none()
    if card is None or card["source"] != "research_agent":
        raise not_found("No such research card.")
    if card["status"] != ProblemStatus.CANDIDATE.value:
        raise ApiError(409, "already_decided", "This card was already decided.")
    approve = decision == "approve"
    names: tuple[str, ...] = ()
    if approve:
        stored = (await sources_of(db, [problem_id]))[problem_id]
        as_of = nairobi_date(await clock_now(db))
        violation, names = publish_violation(dict(card), stored, catalogue, policy, as_of)
        if violation is not None:
            raise ApiError(409, "publish_check_failed", f"This card cannot be published: {violation}.")
        if names and not checklist_confirmed:
            raise ApiError(409, "checklist_required", "This card names an organisation: confirm the checklist first.")
    state = ModerationState.CLEAR if approve else ModerationState.REJECTED
    status = ProblemStatus.PUBLISHED if approve else ProblemStatus.REJECTED
    try:
        await db.execute(_MODERATE, {"id": problem_id, "state": state.value, "status": status.value})
    except DBAPIError as exc:
        refusal = _refusal(exc)
        if refusal is None:
            raise
        await db.rollback()
        raise refusal from None
    await audit(
        db,
        "research.candidate_decided",
        actor_user_id=staff_id,
        actor_kind=AuditActor.STAFF,
        subject_type="problem",
        subject_id=problem_id,
        payload={
            "decision": decision,
            "research_run_id": None if card["research_run_id"] is None else str(card["research_run_id"]),
            "named_orgs": len(names),
            "checklist_confirmed": bool(checklist_confirmed and names),
        },
    )
    await db.commit()
    return DecisionResult(problem_id, status, state)
