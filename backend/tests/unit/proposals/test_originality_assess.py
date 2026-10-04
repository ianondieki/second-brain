"""REQ-PROP-04: the band of a draft against the pool, without a database (``originality.assess``)."""

from __future__ import annotations

from bridge.llm.embeddings import FakeEmbedder, vector_with_similarity
from bridge.models.enums import OriginalityBand
from bridge.proposals import originality as o
from bridge.proposals.originality_policy import load_originality_policy
from tests.unit.proposals.originality_fixtures import (
    COPY_ID,
    DRAFT_ID,
    HELD_ID,
    OTHER,
    OWN_PUBLISHED_ID,
    SUBMITTER,
    TEASER,
    THIRD,
    UNRELATED,
    UNRELATED_ID,
    InMemoryPool,
    Record,
)

POLICY = load_originality_policy()


async def check(pool: InMemoryPool, fields: dict[str, str] | None = None) -> o.Assessment:
    return await o.assess(
        pool, pool.embedder, fields or TEASER, owner_id=SUBMITTER, proposal_id=DRAFT_ID, policy=POLICY
    )


async def test_an_empty_pool_is_none_with_nothing_compared() -> None:
    got = await check(InMemoryPool([]))
    assert (got.band, got.compared, got.matches) == (OriginalityBand.NONE, 0, ())


async def test_the_submitters_own_teasers_are_never_candidates() -> None:
    """The draft itself and a published teaser of the same owner, word for word, are not in the pool."""
    pool = InMemoryPool([Record(DRAFT_ID, SUBMITTER, TEASER), Record(OWN_PUBLISHED_ID, SUBMITTER, TEASER)])
    got = await check(pool)
    assert (got.band, got.compared, got.matches) == (OriginalityBand.NONE, 0, ())


async def test_a_copy_by_another_owner_is_high_and_unrelated_is_none() -> None:
    pool = InMemoryPool([Record(COPY_ID, OTHER, TEASER), Record(UNRELATED_ID, THIRD, UNRELATED)])
    got = await check(pool)
    assert (got.band, got.compared) == (OriginalityBand.HIGH_OVERLAP, 2)
    assert [m.proposal_id for m in got.matches] == [COPY_ID]
    assert (await check(InMemoryPool([Record(UNRELATED_ID, THIRD, UNRELATED)]))).band is OriginalityBand.NONE


async def test_held_or_unpublished_teasers_are_not_compared() -> None:
    pool = InMemoryPool([Record(HELD_ID, OTHER, TEASER, clear=False), Record(COPY_ID, OTHER, TEASER, published=False)])
    assert (await check(pool)).compared == 0


async def test_the_embedding_bands_use_the_policy_thresholds() -> None:
    """A paraphrase with no shared shingle: the band comes from the cosine alone."""
    embedder = FakeEmbedder()
    mine = embedder.vector_for(o.submission_text(TEASER))
    for similarity, band in [
        (0.9, OriginalityBand.HIGH_OVERLAP),
        (0.8, OriginalityBand.SOME_OVERLAP),
        (0.7, OriginalityBand.NONE),
    ]:
        pinned = FakeEmbedder({o.submission_text(UNRELATED): vector_with_similarity(mine, similarity)})
        pool = InMemoryPool([Record(UNRELATED_ID, THIRD, UNRELATED)], embedder=pinned)
        got = await check(pool)
        assert got.band is band, similarity
        assert len(got.matches) == (0 if band is OriginalityBand.NONE else 1)


async def test_a_near_copy_counts_on_the_shingles_alone() -> None:
    """Two words changed at the end of a long teaser: Jaccard stays at or above 0.8 though the fake vectors differ."""
    fields = {**TEASER, "summary": TEASER["summary"].replace("on the way", "on the road")}
    value = o.jaccard(o.shingles(o.submission_text(TEASER)), o.shingles(o.submission_text(fields)))
    assert POLICY.jaccard_high <= value < 1.0
    got = await check(InMemoryPool([Record(COPY_ID, OTHER, fields)]))
    assert got.band is OriginalityBand.HIGH_OVERLAP
