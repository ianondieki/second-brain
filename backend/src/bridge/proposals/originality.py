"""The originality check (REQ-PROP-04; docs/spec/06 6.3; docs/spec/09). Informational, never blocking.

What it compares: the submitter's saved Tier-1 teaser text (``TIER1_FIELDS`` through ``sanitise.plain_text``; every
other field, Tier 2 above all, is ignored by construction: ``submission_text`` picks those four names) against
**other owners'** published teasers that are clear of moderation, and nothing else. Two signals, plain code:

- **MinHash LSH** in plain Python (no dependency, D-36): 5-word shingles, 128 hashes (blake2b, one fixed salt per
  hash, so signatures and buckets are the same on every run and machine), 16 bands of 8 rows. ``index_teaser`` writes
  the bands to ``proposal_lsh_bands`` at publish; a check reads the teasers sharing a bucket and computes the exact
  Jaccard of the shingle sets.
- **Teaser embeddings** through the configured ``Embedder`` (``EMBEDDER``; the fake in tests and the demo):
  ``index_teaser`` stores the vector with its model and version; a check compares only vectors of the same model and
  version (cosine).

The answer is a coarse band (``band_for``; the thresholds are ``policy.yaml`` ``originality``) and ``compared``, how
many teasers were in the pool (never which). Numbers, matched ids and other owners' text never leave this module
except toward the explainer (``bridge.proposals.originality_explainer``), which sees Tier 1 only.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any, Final, Protocol
from uuid import UUID

from pgvector.sqlalchemy import Vector as PgVector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.engagements.calendar import NAIROBI, local_date
from bridge.errors import ApiError
from bridge.ids import uuid7
from bridge.llm.embeddings import EMBED_DIM, Embedder, EmbedderUnavailable, Vector
from bridge.logging import get_logger
from bridge.models.enums import OriginalityBand
from bridge.proposals.assistant import Owned, owned
from bridge.proposals.originality_policy import OriginalityPolicy
from bridge.proposals.sanitise import TIER1_FIELDS, plain_text

SHINGLE_WORDS: Final = 5
NUM_HASHES: Final = 128
BANDS: Final = 16
ROWS: Final = 8
# One 16-byte blake2b salt per hash function: the index format. Changing any of these four constants changes every
# stored bucket, so it needs a re-index of proposal_lsh_bands (never a silent edit).
_SALTS: Final = tuple(i.to_bytes(4, "big") + b"bridge-mh-v1" for i in range(NUM_HASHES))
_BAND_PERSON: Final = b"bridge-lsh-v1"
_WORD: Final = re.compile(r"\w+")

# [[COPY-REVIEW]] shown to the owner.
LIMIT: Final = "You have run today's originality checks. Try again tomorrow."
BUSY: Final = "The originality check for this proposal is still running. Try again in a moment."

log = get_logger(__name__)

if BANDS * ROWS != NUM_HASHES:  # pragma: no cover - a constant mistake
    raise RuntimeError("BANDS * ROWS must equal NUM_HASHES")


def submission_text(fields: Mapping[str, object]) -> str:
    """The Tier-1 teaser text a check reads and an index stores: ``TIER1_FIELDS`` in order, as plain text. Any other
    key (a Tier-2 field, a link) is ignored, whatever its value."""
    parts = [plain_text(value) for name in TIER1_FIELDS if isinstance(value := fields.get(name), str)]
    return "\n".join(part for part in parts if part)


def words(text: str) -> list[str]:
    return _WORD.findall(plain_text(text).casefold())


def shingles(text: str, size: int = SHINGLE_WORDS) -> frozenset[str]:
    """Every run of ``size`` consecutive words; a shorter, non-empty text is one shingle of all its words."""
    found = words(text)
    if not found:
        return frozenset()
    if len(found) < size:
        return frozenset({" ".join(found)})
    return frozenset(" ".join(found[i : i + size]) for i in range(len(found) - size + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def signature(items: Iterable[str]) -> tuple[int, ...]:
    """The MinHash signature: per salted hash, the smallest 64-bit value over the shingles (empty: no signature)."""
    encoded = [item.encode("utf-8") for item in items]
    if not encoded:
        return ()
    return tuple(
        min(int.from_bytes(hashlib.blake2b(item, digest_size=8, salt=salt).digest(), "big") for item in encoded)
        for salt in _SALTS
    )


def estimate(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """The Jaccard estimate of two signatures: the share of equal minimums."""
    if not a or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def lsh_bands(sig: tuple[int, ...]) -> list[tuple[int, int]]:
    """``(band, bucket)`` per band of ``ROWS`` minimums; the bucket is a signed 64-bit hash (a BIGINT column)."""
    if len(sig) != NUM_HASHES:
        return []
    found = []
    for band in range(BANDS):
        rows = b"".join(value.to_bytes(8, "big") for value in sig[band * ROWS : (band + 1) * ROWS])
        digest = hashlib.blake2b(rows, digest_size=8, person=_BAND_PERSON).digest()
        found.append((band, int.from_bytes(digest, "big", signed=True)))
    return found


def band_for(jaccard_value: float, cosine_value: float | None, policy: OriginalityPolicy) -> OriginalityBand:
    """The coarse band: high at or above either high threshold, some at or above the "some" cosine, else none."""
    if jaccard_value >= policy.jaccard_high or (cosine_value is not None and cosine_value >= policy.cosine_high):
        return OriginalityBand.HIGH_OVERLAP
    if cosine_value is not None and cosine_value >= policy.cosine_some:
        return OriginalityBand.SOME_OVERLAP
    return OriginalityBand.NONE


# --- the pool: other owners' published, clear teasers ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublishedTeaser:
    """Another owner's published teaser: its Tier-1 fields only. Never returned to the submitter."""

    proposal_id: UUID
    owner_id: UUID
    fields: Mapping[str, str]

    def __repr__(self) -> str:  # never print another owner's text
        return f"PublishedTeaser(proposal={self.proposal_id}, fields={sorted(self.fields)})"


class TeaserPool(Protocol):
    """Published, clear teasers of owners other than ``owner_id``, never ``proposal_id`` itself."""

    async def size(self, *, owner_id: UUID, proposal_id: UUID) -> int: ...

    async def by_buckets(
        self, buckets: Sequence[tuple[int, int]], *, owner_id: UUID, proposal_id: UUID, limit: int
    ) -> list[PublishedTeaser]:
        """Teasers sharing at least one ``(band, bucket)``, most shared buckets first."""
        ...

    async def nearest(
        self, vector: Vector, *, model: str, version: str, owner_id: UUID, proposal_id: UUID, limit: int
    ) -> list[tuple[PublishedTeaser, float]]:
        """The closest teaser embeddings of the same model and version, with their cosine similarity."""
        ...


# The pool predicate, the same in each query: published, clear of moderation, another owner's, never this proposal.
_SIZE = text(
    "SELECT count(*) FROM proposals p WHERE p.status = 'published' AND p.moderation_state = 'clear'"
    " AND p.published_at IS NOT NULL AND p.owner_id <> :owner AND p.id <> :self"
)
_BY_BUCKETS = text(
    "SELECT p.id, p.owner_id, p.title, p.problem_statement, p.impact_claims, p.summary FROM proposals p"
    " JOIN (SELECT b.proposal_id, count(*) AS hits FROM proposal_lsh_bands b"
    " JOIN unnest(CAST(:bands AS smallint[]), CAST(:buckets AS bigint[])) AS q(band, bucket)"
    " ON b.band = q.band AND b.bucket = q.bucket GROUP BY b.proposal_id) h ON h.proposal_id = p.id"
    " WHERE p.status = 'published' AND p.moderation_state = 'clear'"
    " AND p.published_at IS NOT NULL AND p.owner_id <> :owner AND p.id <> :self"
    " ORDER BY h.hits DESC, p.id LIMIT :limit"
)
_NEAREST = text(
    "SELECT p.id, p.owner_id, p.title, p.problem_statement, p.impact_claims, p.summary,"
    " 1 - (p.teaser_embedding <=> :vector) AS similarity FROM proposals p"
    " WHERE p.status = 'published' AND p.moderation_state = 'clear'"
    " AND p.published_at IS NOT NULL AND p.owner_id <> :owner AND p.id <> :self"
    " AND p.teaser_embedding IS NOT NULL AND p.embed_model = :model AND p.embed_version = :version"
    " ORDER BY p.teaser_embedding <=> :vector, p.id LIMIT :limit"
).bindparams(bindparam("vector", type_=PgVector(EMBED_DIM)))


def _teaser(row: Any) -> PublishedTeaser:
    fields = {name: str(value) for name in TIER1_FIELDS if (value := getattr(row, name))}
    return PublishedTeaser(row.id, row.owner_id, fields)


class SqlTeaserPool:
    """The pool read with the caller's session: RLS shows other owners' proposals only when published and clear, and
    their buckets only then (the explicit predicate says the same, in case a staff session ever calls this)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def size(self, *, owner_id: UUID, proposal_id: UUID) -> int:
        return int((await self._db.execute(_SIZE, {"owner": owner_id, "self": proposal_id})).scalar_one())

    async def by_buckets(
        self, buckets: Sequence[tuple[int, int]], *, owner_id: UUID, proposal_id: UUID, limit: int
    ) -> list[PublishedTeaser]:
        if not buckets:
            return []
        params = {
            "bands": [band for band, _ in buckets],
            "buckets": [bucket for _, bucket in buckets],
            "owner": owner_id,
            "self": proposal_id,
            "limit": limit,
        }
        return [_teaser(row) for row in (await self._db.execute(_BY_BUCKETS, params)).all()]

    async def nearest(
        self, vector: Vector, *, model: str, version: str, owner_id: UUID, proposal_id: UUID, limit: int
    ) -> list[tuple[PublishedTeaser, float]]:
        params = {
            "vector": vector,
            "model": model,
            "version": version,
            "owner": owner_id,
            "self": proposal_id,
            "limit": limit,
        }
        return [(_teaser(row), float(row.similarity)) for row in (await self._db.execute(_NEAREST, params)).all()]


# --- the check ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Assessment:
    """The band and the pool's size; ``matches`` (at most ``max_explained``) go to the explainer only."""

    band: OriginalityBand
    compared: int
    matches: tuple[PublishedTeaser, ...] = ()

    def __repr__(self) -> str:
        return f"Assessment(band={self.band.value}, compared={self.compared}, matches={len(self.matches)})"


async def embed_one(embedder: Embedder, value: str) -> Vector | None:
    """The text's vector, or None when there is no text or the configured embedder cannot run here."""
    if not value:
        return None
    try:
        [vector] = await embedder.embed([value])
    except EmbedderUnavailable as exc:
        log.warning("proposals.originality.embedder_unavailable", reason=str(exc))
        return None
    return vector


async def assess(
    pool: TeaserPool,
    embedder: Embedder,
    fields: Mapping[str, object],
    *,
    owner_id: UUID,
    proposal_id: UUID,
    policy: OriginalityPolicy,
) -> Assessment:
    """The band of the submitter's Tier-1 text against the pool. Plain code; no model."""
    text_ = submission_text(fields)
    compared = await pool.size(owner_id=owner_id, proposal_id=proposal_id)
    mine = shingles(text_)
    if compared == 0 or not mine:
        return Assessment(OriginalityBand.NONE, compared)
    ranked: dict[UUID, tuple[float, PublishedTeaser]] = {}

    def keep(teaser: PublishedTeaser, rank: float) -> None:
        if rank > ranked.get(teaser.proposal_id, (-1.0, teaser))[0]:
            ranked[teaser.proposal_id] = (rank, teaser)

    def theirs(teaser: PublishedTeaser) -> bool:  # defence in depth: the pool already excludes the submitter's own
        return teaser.owner_id != owner_id and teaser.proposal_id != proposal_id

    best_jaccard = 0.0
    found = await pool.by_buckets(
        lsh_bands(signature(mine)), owner_id=owner_id, proposal_id=proposal_id, limit=policy.max_candidates
    )
    for teaser in filter(theirs, found):
        value = jaccard(mine, shingles(submission_text(teaser.fields)))
        best_jaccard = max(best_jaccard, value)
        if value >= policy.jaccard_high:
            keep(teaser, 1.0 + value)  # a near-copy ranks above any embedding match
    best_cosine: float | None = None
    vector = await embed_one(embedder, text_)
    if vector is not None:
        near = await pool.nearest(
            vector,
            model=embedder.model,
            version=embedder.version,
            owner_id=owner_id,
            proposal_id=proposal_id,
            limit=policy.max_explained,
        )
        for teaser, similarity in near:
            if not theirs(teaser):
                continue
            best_cosine = similarity if best_cosine is None else max(best_cosine, similarity)
            if similarity >= policy.cosine_some:
                keep(teaser, similarity)
    band = band_for(best_jaccard, best_cosine, policy)
    ordered = sorted(ranked.values(), key=lambda item: (-item[0], str(item[1].proposal_id)))
    matches = tuple(teaser for _, teaser in ordered[: policy.max_explained]) if band is not OriginalityBand.NONE else ()
    return Assessment(band, compared, matches)


# --- the index, written at publish ----------------------------------------------------------------------------------

_DROP_BANDS = text("DELETE FROM proposal_lsh_bands WHERE proposal_id = :id")
_ADD_BAND = text("INSERT INTO proposal_lsh_bands (proposal_id, band, bucket) VALUES (:id, :band, :bucket)")
_SET_EMBEDDING = text(
    "UPDATE proposals SET teaser_embedding = :vector, embed_model = :model, embed_version = :version WHERE id = :id"
).bindparams(bindparam("vector", type_=PgVector(EMBED_DIM)))


async def index_teaser(
    db: AsyncSession, embedder: Embedder, *, proposal_id: UUID, fields: Mapping[str, object]
) -> None:
    """Replace the proposal's LSH buckets and teaser embedding with those of its published Tier-1 text (the owner's
    transaction, at publish). With no embedder here the stale vector is cleared, never kept for new text."""
    value = submission_text(fields)
    await db.execute(_DROP_BANDS, {"id": proposal_id})
    rows = [
        {"id": proposal_id, "band": band, "bucket": bucket} for band, bucket in lsh_bands(signature(shingles(value)))
    ]
    if rows:
        await db.execute(_ADD_BAND, rows)
    vector = await embed_one(embedder, value)
    await db.execute(
        _SET_EMBEDDING,
        {
            "id": proposal_id,
            "vector": vector,
            "model": embedder.model if vector is not None else None,
            "version": embedder.version if vector is not None else None,
        },
    )


# --- the route's database steps -------------------------------------------------------------------------------------

_TEASER = text("SELECT title, problem_statement, impact_claims, summary FROM proposal_versions WHERE id = :version")
_OWNER_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_CHECKS_TODAY = text("SELECT count(*) FROM originality_checks WHERE user_id = :user AND created_at >= :since")
_RECORD = text(
    "INSERT INTO originality_checks (id, user_id, band, created_at)"
    " VALUES (:id, :user, CAST(:band AS originality_band), :at)"
)


async def owned_by(db: AsyncSession, user_id: UUID, proposal_id: UUID) -> Owned:
    """The caller's draft or published proposal (its draft version, else its current one): ``assistant.owned``. 404
    for anyone else's proposal, published or not, as for every owner-only route (AC-SEC-1/b: a route never tells a
    stranger whether a proposal is theirs to see); 409 ``proposal_hidden`` for a deleted one of theirs."""
    return await owned(db, user_id, proposal_id)


async def load_teaser(db: AsyncSession, own: Owned) -> dict[str, str]:
    """The version's four Tier-1 teaser fields with text. Nothing confidential is read: no Tier-2 key is needed."""
    row = (await db.execute(_TEASER, {"version": own.version_id})).one()
    return {name: str(value) for name in TIER1_FIELDS if (value := getattr(row, name))}


def nairobi_day_start(now: datetime) -> datetime:
    """Midnight in Nairobi of ``now``'s Nairobi date, in UTC."""
    return datetime.combine(local_date(now), time(0), tzinfo=NAIROBI).astimezone(UTC)


async def lock_teaser_checks(db: AsyncSession, user_id: UUID) -> None:
    """The per-user transaction lock of the teaser checks' daily limits (originality and over-disclosure): held until
    the caller commits, across API processes, so a count and the row it guards cannot interleave with another's."""
    await db.execute(_OWNER_LOCK, {"key": f"proposals.teaser_checks:{user_id}"})


async def check_daily_limit(db: AsyncSession, user_id: UUID, policy: OriginalityPolicy, now: datetime) -> None:
    """429 ``originality_limit`` once the user's checks since Nairobi midnight reach ``daily_limit``. Takes the
    per-user lock, so two checks at once cannot both take the last one (the caller records its row in the same
    transaction)."""
    await lock_teaser_checks(db, user_id)
    since = nairobi_day_start(now)
    count = int((await db.execute(_CHECKS_TODAY, {"user": user_id, "since": since})).scalar_one())
    if count >= policy.daily_limit:
        raise ApiError(429, "originality_limit", LIMIT)


async def record_check(db: AsyncSession, user_id: UUID, band: OriginalityBand, now: datetime) -> None:
    """One ``originality_checks`` row per check: the band only (the counter of the daily limit)."""
    await db.execute(_RECORD, {"id": uuid7(), "user": user_id, "band": band.value, "at": now})
