"""REQ-PROP-01 linked-Problem picker (``GET /api/problems``): published problems clear of moderation, filtered by niche
(a parent niche includes its children) and by text; held, unpublished and candidate problems never appear."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration import world as w
from tests.integration.proposals.helpers import Developers, ProposalWorld


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
