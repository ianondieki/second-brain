"""Recommended for you (REQ-PERS-01, REQ-PERS-03; docs/spec/06 6.7): the signed-in developer's context, the
recommendable cards with their trends (``bridge.matching.trend_facts``), the ranker (``bridge.matching.ranker``) and
the response. Computed on read; nothing is stored (revision 0005 has no recommendations table), so each row returns
its feature vector instead.

The developer's context, all read as the developer under Row-Level Security:

- always: the liked niches (``developer_niches``) and the county they gave (``developer_profiles``), the stated
  preferences of onboarding;
- only with the ``profiling`` consent (default off; DPA s.35, AC-PERS-3): the keywords of their profile and of their
  last published proposals (the Tier-1 teaser columns of ``proposals``, never a Tier-2 table) for f1, and their track
  record per niche (published proposals started, proposals with a CLOSED engagement done) for f9. Without it, neither
  is read.
- only with the ``profiling`` consent too, and only when the route names the configured embedder (``Embedding``): the
  cosine of their profile embedding (their own row) and each recommendable card's (P23-1; revision 0012), computed in
  the database in one statement for all the cards, where both vectors exist with that model and version and a set
  hash (a vector without its hash or of another model is never used). The card's ``similarity`` is f1 then; a card
  without it keeps the keyword share.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.errors import not_found
from bridge.matching.discover import niches, problem_out, trend_out
from bridge.matching.discover_schemas import FeatureOut, FeaturesOut, PursuitOut, Recommendation, RecommendationsOut
from bridge.matching.ranker import DECISION_LABELS, RECOMMENDABLE, Card, Developer, keywords, rank
from bridge.matching.ranking_config import RankingConfig
from bridge.matching.trend_facts import board, load
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents
from bridge.profiles.niches import liked

_PROFILE = text("SELECT county_code, headline, bio FROM developer_profiles WHERE user_id = :user")
_PARENTS = text("SELECT parent_id FROM niches WHERE id = ANY(:ids) AND parent_id IS NOT NULL")
_RECENT = text(
    "SELECT title, problem_statement, summary FROM proposals WHERE owner_id = :user AND published_at IS NOT NULL"
    " ORDER BY published_at DESC, id DESC LIMIT :n"
)
_STARTED = text(
    "SELECT niche_id, count(*) AS n FROM proposals WHERE owner_id = :user AND published_at IS NOT NULL"
    " AND niche_id IS NOT NULL GROUP BY niche_id"
)
_DONE = text(
    "SELECT p.niche_id, count(DISTINCT p.id) AS n FROM engagements e JOIN proposals p ON p.id = e.proposal_id"
    " WHERE e.developer_id = :user AND e.state = 'CLOSED' AND p.niche_id IS NOT NULL GROUP BY p.niche_id"
)
# Cosine distance (pgvector ``<=>``) of the own profile's vector and each card's, both of the given model and version
# and each with its text hash set: revision 0012's rule for a vector the ranker may use.
_SIMILARITY = text(
    "SELECT p.id, 1 - (p.embedding <=> d.profile_embedding) AS similarity"
    " FROM developer_profiles d JOIN problems p ON p.id = ANY(:ids)"
    " WHERE d.user_id = :user AND d.profile_embedding IS NOT NULL AND d.profile_embedding_hash IS NOT NULL"
    " AND d.embed_model = :model AND d.embed_version = :version"
    " AND p.embedding IS NOT NULL AND p.embedding_hash IS NOT NULL"
    " AND p.embed_model = :model AND p.embed_version = :version"
)


@dataclass(frozen=True, slots=True)
class Embedding:
    """The configured embedder's model and version: only vectors of these are compared."""

    model: str
    version: str


async def developer(db: AsyncSession, user_id: UUID, cfg: RankingConfig) -> Developer:
    profile = (await db.execute(_PROFILE, {"user": user_id})).one_or_none()
    if profile is None:
        raise not_found("No developer profile.")
    liked_ids = frozenset(await liked(db, user_id))
    parents = frozenset((await db.execute(_PARENTS, {"ids": list(liked_ids)})).scalars().all())
    personalised = (await consents.current(db, user_id))[ConsentPurpose.PROFILING]
    base = Developer(liked_ids, parents, profile.county_code, personalised)
    if not personalised:
        return base
    r = cfg.ranker
    texts = [profile.headline or "", profile.bio or ""]
    proposal_texts = []
    for row in (await db.execute(_RECENT, {"user": user_id, "n": r.recent_proposals})).all():
        proposal_texts += [row.title or "", row.problem_statement or "", row.summary or ""]
    started = {row.niche_id: int(row.n) for row in (await db.execute(_STARTED, {"user": user_id})).all()}
    done = {row.niche_id: int(row.n) for row in (await db.execute(_DONE, {"user": user_id})).all()}
    track = {niche: (count, min(done.get(niche, 0), count)) for niche, count in started.items()}
    from_proposals = frozenset(keywords(" ".join(proposal_texts), r.min_keyword_length))
    words = frozenset(keywords(" ".join(texts), r.min_keyword_length)) | from_proposals
    return Developer(liked_ids, parents, profile.county_code, True, words, track, from_proposals)


async def similarities(
    db: AsyncSession, user_id: UUID, problem_ids: Sequence[UUID], embedding: Embedding
) -> dict[UUID, float]:
    """Each card's cosine similarity with the developer's profile, where both vectors may be used (one statement). A
    similarity that is not a number (a zero vector, which revision 0012's writers refuse) is left out: keywords then."""
    params = {"user": user_id, "ids": list(problem_ids), "model": embedding.model, "version": embedding.version}
    found = {row.id: row.similarity for row in (await db.execute(_SIMILARITY, params)).all()}
    return {pid: float(value) for pid, value in found.items() if value is not None and math.isfinite(value)}


async def recommendations(
    db: AsyncSession, cfg: RankingConfig, user_id: UUID, *, embedding: Embedding | None = None
) -> RecommendationsOut:
    dev = await developer(db, user_id, cfg)
    b = board(await load(db, cfg), cfg)
    tree = await niches(db)
    ids = [pid for pid, fact in b.facts.problems.items() if fact.source in RECOMMENDABLE]
    near = await similarities(db, user_id, ids, embedding) if dev.personalised and embedding is not None else {}
    cards = [Card(b.facts.problems[pid], b.problems[pid], b.signals[pid], near.get(pid)) for pid in ids]
    rows = rank(cards, dev, cfg.ranker, cfg.trending, b.facts.now)
    items = [
        Recommendation(
            problem=problem_out(r.card.fact, tree),
            position=position,
            score=r.score,
            label=r.label,
            exploring=r.exploring,
            pursuit=PursuitOut(decision=r.decision, label=DECISION_LABELS[r.decision], reasons=list(r.reasons)),
            why=list(r.why),
            why_not=r.why_not,
            trend=trend_out(r.card.fact, r.card.signals, r.card.trend, tree),
            features=FeaturesOut(
                **{
                    name: FeatureOut(raw=f.raw, value=f.value, weight=f.weight, applies=f.applies, source=f.source)
                    for name, f in r.features.items()
                }
            ),
        )
        for position, r in enumerate(rows, start=1)
    ]
    liked_out = [n for n in (tree.out(i) for i in sorted(dev.liked, key=str)) if n is not None]
    return RecommendationsOut(
        generated_at=b.facts.now,
        ranker_version=cfg.ranker.version,
        personalised=dev.personalised,
        liked_niches=liked_out,
        items=items,
    )
