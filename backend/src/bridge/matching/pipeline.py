"""The scout's rules: SQL hard filters, then a deterministic score (REQ-SCOUT-02; docs/spec/06 6.8).

Plain code decides what matches; the model only explains (``bridge.matching.rationale``). Tier 1 and metadata only
(D-43 (a)): every column read here is a registered version's Tier-1 teaser, reached through
``proposals.current_version_id`` (never an older version, P2 review MINOR), plus niche names, the organisation's own
delivered tags and whether the version links a published problem. Nothing here reads Tier 2 or switches roles.

1. ``candidates``: published, clear proposals whose current registered version passes the hard filters, under the
   caller's RLS (the scan job binds the scout's acting member and organisation; Preview the signed-in admin): the
   niche is one the scout chose or a child of a parent niche it chose; the county and maturity are among the scout's
   (when it lists any); no exclude keyword appears in the teaser (case-insensitive substring, AC-SCOUT-5); the owner is
   not a member of the organisation; a saved scout's earlier matches are left out; the publication falls in the
   window (or is the one ``on_new`` proposal). Ordered by (published_at, id), at most ``limits.scan_per_run``.
2. ``score``: points from ``config/matching/weights_v1.yaml``: include keywords found in the teaser (the prototype's
   stand-in for the fake embedder's meaningless cosine, simulated), the niche (exact or through its parent), a
   delivered tag to this organisation and Tier-1 evidence (impact claims, a linked published problem).
3. ``select``: scores at or above ``min_fit``, highest first (ties: earlier publication, then id), at most ``limit``.

The budget band is recorded on the scout but not applied: proposals carry no budget yet.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.directory.service import niche_label
from bridge.matching.config import Weights
from bridge.models.enums import ProposalAsk, ProposalMaturity

# The teaser columns (docs/spec/06 6.1 Tier 1) the rules and the model may read, all from the current version.
TEXT_COLUMNS: Final = ("title", "problem_statement", "summary", "impact_claims")
_TEXT: Final = "concat_ws(' ', v.title, v.problem_statement, v.summary, v.impact_claims)"
_SELECT: Final = (
    "SELECT p.id AS proposal_id, p.current_version_id AS version_id, p.owner_id, p.published_at,"
    " v.title, v.problem_statement, v.summary, v.impact_claims, v.niche_id, v.county_code, v.maturity, v.ask,"
    " n.name_en AS niche_name, pn.name_en AS parent_name, r.name AS county_name,"
    " (v.niche_id = ANY(:niches)) AS niche_exact,"
    " EXISTS (SELECT 1 FROM tags t WHERE t.proposal_id = p.id AND t.org_id = :org AND t.status = 'delivered')"
    " AS tagged,"
    " EXISTS (SELECT 1 FROM proposal_problems pp JOIN problems pr ON pr.id = pp.problem_id"
    " WHERE pp.proposal_version_id = p.current_version_id AND pr.status = 'published'"
    " AND pr.moderation_state = 'clear') AS has_problem"
    " FROM proposals p"
    " JOIN proposal_versions v ON v.id = p.current_version_id AND v.proposal_id = p.id"
    " LEFT JOIN niches n ON n.id = v.niche_id LEFT JOIN niches pn ON pn.id = n.parent_id"
    " LEFT JOIN regions r ON r.code = v.county_code"
)
_HARD_FILTERS: Final = (
    "p.status = 'published'",
    "p.moderation_state = 'clear'",
    "p.published_at IS NOT NULL",
    "v.status = 'registered'",
    "(v.niche_id = ANY(:niches) OR n.parent_id = ANY(:niches))",
    "(cardinality(CAST(:counties AS text[])) = 0 OR v.county_code = ANY(CAST(:counties AS text[])))",
    "(cardinality(CAST(:maturity AS proposal_maturity[])) = 0"
    " OR v.maturity = ANY(CAST(:maturity AS proposal_maturity[])))",
    # _TEXT is a constant (no input); the keywords are bound parameters.
    f"NOT EXISTS (SELECT 1 FROM unnest(CAST(:exclude AS text[])) AS k(word) WHERE strpos(lower({_TEXT}),"  # noqa: S608
    " lower(k.word)) > 0)",
    "NOT EXISTS (SELECT 1 FROM memberships m WHERE m.org_id = :org AND m.user_id = p.owner_id AND m.status = 'active')",
)
_NOT_MATCHED: Final = "NOT EXISTS (SELECT 1 FROM agent_matches am WHERE am.scout_id = :scout AND am.proposal_id = p.id)"


@dataclass(frozen=True, slots=True)
class Filters:
    """A scout's form as the rules read it: a saved scout (``scout_id``: its earlier matches are left out) or
    Preview's unsaved form. Keywords are compared lower-cased."""

    org_id: UUID
    niches: tuple[UUID, ...]
    counties: tuple[str, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    maturity: tuple[ProposalMaturity, ...] = ()
    min_fit: int = 60
    scout_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Window:
    """Publications in (``since``, ``until``], or strictly after ``after`` (a truncated run's last proposal) up to
    ``until``; ``proposal_id`` alone for an ``on_new`` run (the window is then ignored)."""

    until: datetime
    since: datetime | None = None
    after: tuple[datetime, UUID] | None = None
    proposal_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """A proposal that passed the hard filters: its current version's Tier-1 teaser and metadata."""

    proposal_id: UUID
    version_id: UUID
    owner_id: UUID
    published_at: datetime
    title: str | None
    problem_statement: str | None
    summary: str | None
    impact_claims: str | None
    niche_id: UUID | None
    niche_name: str | None
    parent_name: str | None
    county_code: str | None
    county_name: str | None
    maturity: ProposalMaturity | None
    ask: ProposalAsk | None
    niche_exact: bool
    tagged: bool
    has_problem: bool

    @property
    def text(self) -> str:
        return " ".join(
            value for value in (self.title, self.problem_statement, self.summary, self.impact_claims) if value
        )

    @property
    def niche_label(self) -> str | None:
        return niche_label(self.niche_name, self.parent_name) if self.niche_name else None


@dataclass(frozen=True, slots=True)
class Scored:
    """A candidate with its deterministic score (0-100), the include keywords found and the points per rule."""

    candidate: Candidate
    score: int
    keywords_found: tuple[str, ...]
    points: dict[str, float] = field(default_factory=dict)

    def breakdown(self) -> dict[str, Any]:
        """The rules that fired, for ``agent_matches.rule_breakdown`` (codes and numbers; keywords are the
        organisation's own)."""
        return {
            "deterministic": self.score,
            "points": {name: round(value, 2) for name, value in self.points.items()},
            "keywords": list(self.keywords_found),
            "niche_exact": self.candidate.niche_exact,
            "tagged": self.candidate.tagged,
        }


def _row(row: Any) -> Candidate:
    return Candidate(
        proposal_id=row.proposal_id,
        version_id=row.version_id,
        owner_id=row.owner_id,
        published_at=row.published_at,
        title=row.title,
        problem_statement=row.problem_statement,
        summary=row.summary,
        impact_claims=row.impact_claims,
        niche_id=row.niche_id,
        niche_name=row.niche_name,
        parent_name=row.parent_name,
        county_code=row.county_code,
        county_name=row.county_name,
        maturity=ProposalMaturity(row.maturity) if row.maturity else None,
        ask=ProposalAsk(row.ask) if row.ask else None,
        niche_exact=bool(row.niche_exact),
        tagged=bool(row.tagged),
        has_problem=bool(row.has_problem),
    )


def excluded(text_value: str, exclude_keywords: Sequence[str]) -> bool:
    """An exclude keyword appears in the teaser (the SQL filter's rule, checked again in code)."""
    lowered = text_value.lower()
    return any(word.lower() in lowered for word in exclude_keywords)


async def candidates(db: AsyncSession, filters: Filters, window: Window, *, limit: int) -> list[Candidate]:
    """The proposals that pass the hard filters, oldest publication first, at most ``limit``."""
    conditions = list(_HARD_FILTERS)
    params: dict[str, Any] = {
        "org": filters.org_id,
        "niches": list(filters.niches),
        "counties": list(filters.counties),
        "maturity": [m.value for m in filters.maturity],
        "exclude": list(filters.exclude_keywords),
        "limit": limit,
    }
    if filters.scout_id is not None:
        conditions.append(_NOT_MATCHED)
        params["scout"] = filters.scout_id
    if window.proposal_id is not None:
        conditions.append("p.id = :proposal")
        params["proposal"] = window.proposal_id
    else:
        conditions.append("p.published_at <= :until")
        params["until"] = window.until
        if window.after is not None:
            conditions.append("(p.published_at, p.id) > (:after_at, :after_id)")
            params["after_at"], params["after_id"] = window.after
        elif window.since is not None:
            conditions.append("p.published_at > :since")
            params["since"] = window.since
    sql = f"{_SELECT} WHERE {' AND '.join(conditions)} ORDER BY p.published_at, p.id LIMIT :limit"
    rows = (await db.execute(text(sql), params)).all()
    found = [_row(row) for row in rows]
    return [c for c in found if not excluded(c.text, filters.exclude_keywords)]


def _round(value: float) -> int:
    return max(0, min(100, math.floor(value + 0.5)))


def score(candidate: Candidate, filters: Filters, weights: Weights) -> Scored:
    """The deterministic score (docs/spec/06 6.8, weights_v1.yaml)."""
    lowered = candidate.text.lower()
    found = tuple(word for word in filters.include_keywords if word.lower() in lowered)
    if filters.include_keywords:
        keyword_share = min(1.0, len(found) / min(weights.keyword_saturation, len(filters.include_keywords)))
    else:
        keyword_share = weights.keywords_none_listed
    niche_share = weights.niche_exact if candidate.niche_exact else weights.niche_via_parent
    evidence_share = 0.5 * bool((candidate.impact_claims or "").strip()) + 0.5 * candidate.has_problem
    points = {
        "keywords": weights.keywords * keyword_share,
        "niche": weights.niche * niche_share,
        "tagged": weights.tagged * float(candidate.tagged),
        "evidence": weights.evidence * evidence_share,
    }
    return Scored(candidate, _round(math.fsum(points.values())), found, points)


def select(scored: Sequence[Scored], min_fit: int, limit: int) -> list[Scored]:
    """The matches: at or above ``min_fit``, highest first (ties: earlier publication, then id), at most ``limit``."""
    kept = [s for s in scored if s.score >= min_fit]
    kept.sort(key=lambda s: (-s.score, s.candidate.published_at, s.candidate.proposal_id))
    return kept[:limit]


def final_score(deterministic: int, model: int | None, weights: Weights) -> int:
    """final = model_weight·model + (1 - model_weight)·deterministic when the model answered, else deterministic."""
    if model is None:
        return deterministic
    return _round(weights.model_weight * model + (1 - weights.model_weight) * deterministic)


def matched_on(s: Scored) -> str:
    """The code's "why this matches" line: the rules that fired, from the teaser's metadata. [[COPY-REVIEW]]"""
    c = s.candidate
    parts = [f"niche {c.niche_label}" if c.niche_label else "your niches"]
    if s.keywords_found:
        parts.append("keywords " + ", ".join(f'"{word}"' for word in s.keywords_found))
    if c.county_name or c.county_code:
        parts.append(f"county {c.county_name or c.county_code}")
    if c.maturity is not None:
        parts.append(f"maturity {c.maturity.value}")
    if c.tagged:
        parts.append("the developer tagged your organisation")
    return ("Matched on " + "; ".join(parts) + ".")[:600]
