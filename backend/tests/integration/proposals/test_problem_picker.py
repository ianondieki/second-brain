"""REQ-PROP-01 linked-Problem picker (``GET /api/problems``): published problems clear of moderation, filtered by niche
(a parent niche includes its children) and by text; held, unpublished and candidate problems never appear."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration import world as w
from tests.integration.proposals.helpers import Developers, ProposalWorld, user_of


async def test_the_picker_lists_published_clear_problems_by_niche_and_text(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    word = f"borehole{uuid4().hex[:8]}"
    async with owner_engine.begin() as conn:
        author = await w.add_user(conn, f"picker-{uuid4().hex[:8]}@example.test", "Picker")
        ids = {
            "clear": await w.add_problem(conn, author, proposal_world.niche_id),
            "held": await w.add_problem(conn, author, proposal_world.niche_id, moderation_state="held"),
            "pending": await w.add_problem(conn, author, proposal_world.niche_id, status="pending_review"),
            "candidate": await w.add_problem(conn, author, proposal_world.niche_id, status="candidate"),
        }
        await conn.execute(
            text("UPDATE problems SET title = :t WHERE id = ANY(:ids)"), {"t": f"Dry {word}", "ids": list(ids.values())}
        )
    reader = await developers(level="d0")

    found = (await reader.get("/api/problems", params={"q": word})).json()["items"]
    assert [p["id"] for p in found] == [str(ids["clear"])]
    [card] = found
    assert card["title"] == f"Dry {word}"
    assert card["niche"]["label"] == proposal_world.niche_label
    assert card["label"] == "Developer-reported"
    assert card["statement"] == "Statement"

    by_parent = (await reader.get("/api/problems", params={"niche": proposal_world.parent_slug, "q": word})).json()
    by_child = (await reader.get("/api/problems", params={"niche": proposal_world.niche_slug, "q": word})).json()
    elsewhere = (await reader.get("/api/problems", params={"niche": "no-such-niche", "q": word})).json()
    assert [p["id"] for p in by_parent["items"]] == [p["id"] for p in by_child["items"]] == [str(ids["clear"])]
    assert elsewhere["items"] == []

    page = (await reader.get("/api/problems", params={"niche": proposal_world.parent_slug, "limit": 1})).json()
    assert len(page["items"]) == 1
    assert (await reader.get("/api/problems", params={"q": "%"})).status_code == 200
    assert (await reader.get("/api/problems", params={"niche": "Bad Slug"})).status_code == 422


async def test_the_creators_own_held_problem_is_not_offered(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """Row-Level Security lets a creator read their own held problem; the picker still offers only clear ones."""
    reader = await developers()
    word = f"cistern{uuid4().hex[:8]}"
    async with owner_engine.begin() as conn:
        own = await w.add_problem(conn, user_of(reader), proposal_world.niche_id, moderation_state="held")
        await conn.execute(text("UPDATE problems SET title = :t WHERE id = :id"), {"t": f"Leaky {word}", "id": own})
    assert (await reader.get("/api/problems", params={"q": word})).json()["items"] == []


async def test_the_list_pages_newest_first_with_a_cursor(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    """P16-E1 item 2: the list pages like every other list (``limit``, ``cursor``, ``next_cursor``), keyed on its
    order (newest publication first, an unknown day last, then the id), so a tie or a null never repeats or skips a
    problem; a cursor the server did not write is 400 ``invalid_cursor``."""
    word = f"cursor{uuid4().hex[:8]}"
    days = ["2026-01-03", "2026-01-02", "2026-01-02", None, None]
    async with owner_engine.begin() as conn:
        author = await w.add_user(conn, f"pages-{uuid4().hex[:8]}@example.test", "Pages")
        ids = [await w.add_problem(conn, author, proposal_world.niche_id) for _ in days]
        for problem_id, day in zip(ids, days, strict=True):
            await conn.execute(
                text("UPDATE problems SET title = :t, published_at = CAST(:day AS timestamptz) WHERE id = :id"),
                {"t": f"Paged {word}", "day": day, "id": problem_id},
            )
    expected = [ids[0], max(ids[1], ids[2]), min(ids[1], ids[2]), max(ids[3], ids[4]), min(ids[3], ids[4])]
    reader = await developers(level="d0")
    whole = (await reader.get("/api/problems", params={"q": word})).json()
    assert [p["id"] for p in whole["items"]] == [str(i) for i in expected]
    assert whole["next_cursor"] is None
    seen: list[str] = []
    cursor: str | None = None
    for size in (2, 2, 1):
        params = {"q": word, "limit": "2"} | ({"cursor": cursor} if cursor else {})
        page = (await reader.get("/api/problems", params=params)).json()
        assert len(page["items"]) == size
        seen += [p["id"] for p in page["items"]]
        cursor = page["next_cursor"]
    assert seen == [str(i) for i in expected]
    assert cursor is None
    for bad in ("not-a-cursor", "WyIyMDI2LTAxLTAyVDAwOjAwOjAwIiwgIngiXQ", "WzEsIDJd", "bnVsbA"):
        refused = await reader.get("/api/problems", params={"q": word, "cursor": bad})
        assert refused.status_code == 400, bad
        assert refused.json() == {"detail": {"code": "invalid_cursor", "message": "Start again from the first page."}}
    assert (await reader.get("/api/problems", params={"cursor": "x" * 2001})).status_code == 422
