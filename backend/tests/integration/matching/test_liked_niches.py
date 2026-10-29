"""REQ-PERS-03 (docs/spec/05, 06 6.7): ``GET|PUT /api/me/niches``, the developer's liked niches. PUT sets all of them
(3 to 5 active niches, duplicates once); followed niches are never touched; each user reads and writes only their own
rows (Row-Level Security)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.matching.scout_world import run
from tests.integration.matching.trend_world import build
from tests.integration.proposals.helpers import Developers, rows, user_of


async def test_liked_niches_are_set_whole_and_validated(owner_engine: AsyncEngine, developers: Developers) -> None:
    world = await build(owner_engine)
    developer, other = await developers(), await developers()
    me = user_of(developer)
    retired = uuid7()
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO niches (id, slug, name_en, active) VALUES (:id, :slug, 'Retired', false)",
            id=retired,
            slug=f"p12-retired-{world.tag}",
        )
        await run(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'followed')",
            u=me,
            n=world.elsewhere,
        )
    empty = await developer.get("/api/me/niches")
    assert empty.json() == {"liked": [], "min": 3, "max": 5}

    three = [str(world.niche), str(world.sibling), str(world.parent)]
    for liked, code in (
        (three[:2], "liked_niches_count"),
        ([*three, str(world.elsewhere), str(uuid7()), str(uuid7())], "liked_niches_count"),
        ([*three[:2], three[0]], "liked_niches_count"),  # a duplicate counts once
        ([*three[:2], str(uuid7())], "unknown_niche"),
        ([*three[:2], str(retired)], "unknown_niche"),
    ):
        refused = await developer.put("/api/me/niches", json={"liked": liked})
        assert refused.status_code == 422, liked
        assert refused.json()["detail"]["code"] == code
    set_ = await developer.put("/api/me/niches", json={"liked": three})
    assert set_.status_code == 200
    assert {n["id"] for n in set_.json()["liked"]} == set(three)
    assert world.label("niche") in {n["label"] for n in set_.json()["liked"]}
    changed = await developer.put("/api/me/niches", json={"liked": [*three[1:], str(world.elsewhere)]})
    assert {n["id"] for n in changed.json()["liked"]} == {*three[1:], str(world.elsewhere)}
    assert (await other.put("/api/me/niches", json={"liked": three})).status_code == 200

    stored = await rows(
        owner_engine, "SELECT niche_id, kind::text AS kind FROM developer_niches WHERE user_id = :u", u=me
    )
    assert sorted((str(r.niche_id), r.kind) for r in stored) == sorted(
        [(n, "liked") for n in [*three[1:], str(world.elsewhere)]] + [(str(world.elsewhere), "followed")]
    )
    assert {n["id"] for n in (await other.get("/api/me/niches")).json()["liked"]} == set(three)
    assert (await developer.put("/api/me/niches", json={"liked": three, "extra": 1})).status_code == 422
