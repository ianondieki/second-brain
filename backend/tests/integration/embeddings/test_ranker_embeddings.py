"""Recommended for you with embeddings (P23-1; REQ-PERS-01, REQ-PERS-02, AC-PERS-2): with the profiling consent, a
card's f1 is the cosine of the developer's profile embedding and its own when both exist with the configured model and
version and a set hash; a card without such a vector keeps the keyword share. The vectors are pinned in the fake
embedder and written through the worker's tables, so the order is deterministic. The route sends as many statements
for 20 cards with vectors as for 2."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import create_session_factory
from bridge.embeddings.tables import FunctionTable, ProblemEmbeddingTable, ProfileEmbeddingTable
from bridge.jobs.reembed import StaleRow
from bridge.llm.embeddings import FAKE_MODEL, FAKE_VERSION, FakeEmbedder, hashed_vector, vector_with_similarity
from bridge.matching.ranker import SIMILAR_WORDS
from tests.integration.embeddings.schema_world import sha
from tests.integration.matching.trend_world import TrendWorld, build, research_card
from tests.integration.proposals.helpers import Developers, rows, user_of
from tests.integration.query_counts import LARGE, SMALL, counted

HEADLINE = "I build solar irrigation pumps for smallholder farmers"


@pytest.fixture
async def made(owner_engine: AsyncEngine) -> AsyncIterator[list[UUID]]:
    """The cards a test makes, archived when it ends: fresh cards left published in the shared database would crowd
    the recommendations other tests read (their top ten is drawn from every recommendable card)."""
    cards: list[UUID] = []
    yield cards
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE problems SET status = 'archived' WHERE id = ANY(:ids)"), {"ids": cards})


async def personalised(developer: httpx.AsyncClient, world: TrendWorld) -> None:
    """Liked niches, a county, a headline and the profiling consent, through the API."""
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
    assert (await developer.put("/api/me/niches", json=liked)).status_code == 200
    profile = {"county_code": "KE-30", "headline": HEADLINE}
    assert (await developer.patch("/api/me/profile", json=profile)).status_code == 200
    version = (await developer.get("/api/consents")).json()["version"]
    decision = {"profiling": {"granted": True, "version": version}}
    assert (await developer.put("/api/me/consents", json=decision)).status_code == 200


async def profile_text(owner: AsyncEngine, user: UUID) -> str:
    [row] = await rows(owner, "SELECT profile_embedding_text(:u) AS text", u=user)
    return str(row.text)


async def problem_text(owner: AsyncEngine, problem: UUID) -> str:
    sql = "SELECT problem_embedding_text(title, statement) AS text FROM problems WHERE id = :p"
    [row] = await rows(owner, sql, p=problem)
    return str(row.text)


async def embed(app: AsyncEngine, owner: AsyncEngine, fake: FakeEmbedder, user: UUID, *problems: UUID) -> None:
    """As the worker: the profile's and the problems' vectors from ``fake``, each with its text's hash."""
    factory = create_session_factory(app)
    profiles, cards = ProfileEmbeddingTable(factory), ProblemEmbeddingTable(factory)
    rows_to_write: list[tuple[FunctionTable, UUID, str]] = [(profiles, user, await profile_text(owner, user))]
    rows_to_write += [(cards, problem, await problem_text(owner, problem)) for problem in problems]
    for table, row_id, content in rows_to_write:
        row = StaleRow(row_id, content, sha(content))
        assert await table.save(row, fake.vector_for(content), model=FAKE_MODEL, version=FAKE_VERSION)


async def recommended(developer: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    response = await developer.get("/api/me/recommendations")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["personalised"] is True
    return {item["problem"]["id"]: item for item in body["items"]}


async def test_a_card_close_to_the_profile_ranks_above_a_far_one_and_says_why(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers, made: list[UUID]
) -> None:
    """Given a consented developer and five otherwise alike cards in liked niches: one whose vector is close to the
    profile's (cosine 0.9) and one far (0.1) in the same niche, one with another model's vector, one whose vector lost
    its hash and one whose vector the owner zeroed (no cosine), When recommendations are requested, Then the close card
    ranks above the far one with "Similar to your profile" and both record f1 from the embeddings; the other three fall
    back to the keyword share."""
    world = await build(owner_engine)
    # at most three cards of one niche in the top ten: the close and far ones in one, the fallbacks in another
    niches = {
        "Near": world.niche,
        "Far": world.niche,
        "Other model": world.sibling,
        "Unhashed": world.sibling,
        "Zeroed": world.sibling,
    }
    near, far, other_model, unhashed, zeroed = [
        await research_card(owner_engine, niche, county="KE-30", title=f"{label} solar irrigation pumps")
        for label, niche in niches.items()
    ]
    made.extend((near, far, other_model, unhashed, zeroed))
    developer = await developers()
    me = user_of(developer)
    await personalised(developer, world)

    base = hashed_vector("the developer's profile")
    fake = FakeEmbedder({await profile_text(owner_engine, me): base})
    fake.pin(await problem_text(owner_engine, near), vector_with_similarity(base, 0.9, seed="near"))
    fake.pin(await problem_text(owner_engine, far), vector_with_similarity(base, 0.1, seed="far"))
    await embed(app_engine, owner_engine, fake, me, near, far, other_model, unhashed, zeroed)
    zero = "[" + ",".join(["0"] * 1024) + "]"
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE problems SET embed_model = 'another-model' WHERE id = :p"), {"p": other_model})
        await conn.execute(text("UPDATE problems SET embedding_hash = NULL WHERE id = :p"), {"p": unhashed})
        await conn.execute(
            text("UPDATE problems SET embedding = CAST(:z AS vector) WHERE id = :p"), {"z": zero, "p": zeroed}
        )

    items = await recommended(developer)
    close, distant = items[str(near)], items[str(far)]
    assert close["position"] < distant["position"]
    assert close["score"] > distant["score"]
    for item, cosine in ((close, 0.9), (distant, 0.1)):
        fit = item["features"]["semantic_fit"]
        assert (fit["applies"], fit["source"]) == (True, "embedding")
        assert fit["raw"] == pytest.approx(cosine, abs=1e-4)  # float32 vectors
        assert fit["value"] == pytest.approx(cosine, abs=1e-4)
    assert SIMILAR_WORDS in close["why"]
    assert "Close to your profile" not in close["why"]
    for fallback in (other_model, unhashed, zeroed):
        fit = items[str(fallback)]["features"]["semantic_fit"]
        assert (fit["applies"], fit["source"], fit["raw"]) == (True, "keywords", 4)  # solar, irrigation, pumps, farmers
        assert SIMILAR_WORDS not in items[str(fallback)]["why"]
    assert all(item["why"] and item["pursuit"]["reasons"] for item in items.values())  # AC-PERS-1, AC-PERS-2


async def test_the_vector_path_sends_as_many_statements_for_20_cards_as_for_2(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers, made: list[UUID]
) -> None:
    world = await build(owner_engine)
    developer = await developers()
    me = user_of(developer)
    await personalised(developer, world)
    fake = FakeEmbedder()
    mine: set[str] = set()
    liked = (world.niche, world.sibling, world.elsewhere)

    async def add(count: int) -> None:
        cards = [await research_card(owner_engine, liked[n % 3], county="KE-30", age_days=n + 1) for n in range(count)]
        made.extend(cards)
        await embed(app_engine, owner_engine, fake, me, *cards)
        mine.update(str(card) for card in cards)

    await add(SMALL)
    small, body = await counted(developer, app_engine, "/api/me/recommendations")
    sources = {i["features"]["semantic_fit"]["source"] for i in body["items"] if i["problem"]["id"] in mine}
    assert sources == {"embedding"}
    await add(LARGE - SMALL)
    large, body = await counted(developer, app_engine, "/api/me/recommendations")
    assert len(body["items"]) >= 9  # three a liked niche at most, and the exploration slot when a card is outside them
    assert large == small
