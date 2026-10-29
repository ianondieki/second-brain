"""REQ-PERS-03 (R27) with REQ-TREND-02 (R18), P21 track C, D-57 (7): saved Discover searches through the API as
``bridge_app`` (revision 0008's ``saved_searches``).

- P21-C1: a developer saves Discover's view and filters under a name (alerts on by default), lists, renames, turns
  alerts off and deletes them; the niche must be a niche and the county a county (422); at most 10: the 11th is 409.
- P21-C2: a saved search is its owner's only: another developer neither lists, changes nor deletes it (404 like an
  unknown id); someone without a developer profile has none (404).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.seed.reference import load_reference, seed_regions
from tests.integration.proposals.helpers import Developers, ProposalWorld
from tests.integration.proposals.pitch_helpers import Members, PitchOrgs

URL = "/api/me/saved-searches"
KEYS = {"id", "name", "view", "niche", "county", "words", "alerts", "last_alerted_at", "created_at"}


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


async def regions(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_regions(conn, load_reference()["regions"])  # the 47 counties (idempotent)


async def test_p21_c1_save_list_rename_switch_off_delete_and_the_cap_of_ten(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine
) -> None:
    await regions(owner_engine)
    me = await developers()
    assert await ok(await me.get(URL)) == {"items": [], "max": 10}
    body = {
        "name": "  Solar in Nakuru  ",
        "view": "briefs",
        "niche": proposal_world.parent_slug,
        "county": "KE-32",
        "words": " cold chain ",
    }
    saved = await ok(await me.post(URL, json=body), 201)
    assert set(saved) == KEYS
    assert (saved["name"], saved["view"], saved["niche"], saved["county"], saved["words"]) == (
        "Solar in Nakuru",
        "briefs",
        proposal_world.parent_slug,
        "KE-32",
        "cold chain",
    )
    assert (saved["alerts"], saved["last_alerted_at"]) == (True, None)
    plain = await ok(await me.post(URL, json={"name": "Everything", "view": "problems", "words": "   "}), 201)
    assert (plain["niche"], plain["county"], plain["words"]) == (None, None, None)

    listed = await ok(await me.get(URL))
    assert [item["id"] for item in listed["items"]] == [plain["id"], saved["id"]]  # newest first
    renamed = await ok(await me.patch(f"{URL}/{saved['id']}", json={"name": "Solar, Nakuru"}))
    assert (renamed["name"], renamed["alerts"]) == ("Solar, Nakuru", True)
    quiet = await ok(await me.patch(f"{URL}/{saved['id']}", json={"alerts": False}))
    assert (quiet["name"], quiet["alerts"], quiet["niche"]) == ("Solar, Nakuru", False, proposal_world.parent_slug)
    assert (await me.patch(f"{URL}/{saved['id']}", json={"niche": "other"})).status_code == 422  # name, alerts only
    assert (await me.patch(f"{URL}/{saved['id']}", json={"name": " "})).status_code == 422

    refused = [
        ({"name": "x", "view": "problems", "niche": f"no-such-niche-{uuid4().hex[:6]}"}, "unknown_niche"),
        ({"name": "x", "view": "problems", "county": "KE-99"}, "unknown_county"),
        ({"name": "x", "view": "problems", "county": "KE"}, None),  # not a county code at all
        ({"name": "", "view": "problems"}, None),
        ({"name": "n" * 61, "view": "problems"}, None),
        ({"name": "x", "view": "projects"}, None),  # only the problems and Briefs views are saved
        ({"name": "x", "view": "problems", "words": "w" * 101}, None),
    ]
    for request, expected in refused:
        response = await me.post(URL, json=request)
        assert response.status_code == 422, (request, response.text)
        if expected is not None:
            assert code(response) == (422, expected)

    assert await ok(await me.delete(f"{URL}/{plain['id']}"), 204) is None
    assert code(await me.delete(f"{URL}/{plain['id']}")) == (404, "not_found")
    for n in range(9):
        await ok(await me.post(URL, json={"name": f"Search {n}", "view": "problems"}), 201)
    assert len((await ok(await me.get(URL)))["items"]) == 10
    eleventh = await me.post(URL, json={"name": "One too many", "view": "problems"})
    assert code(eleventh) == (409, "saved_searches_limit")
    assert eleventh.json()["detail"]["max"] == 10
    assert len((await ok(await me.get(URL)))["items"]) == 10


async def test_p21_c2_a_saved_search_is_its_owners_only(
    developers: Developers, pitch_orgs: PitchOrgs, member_client: Members, owner_engine: AsyncEngine
) -> None:
    await regions(owner_engine)
    mine, theirs = await developers(), await developers()
    saved = await ok(await mine.post(URL, json={"name": "Mine", "view": "problems", "county": "KE-01"}), 201)
    assert (await ok(await theirs.get(URL)))["items"] == []
    for response in (
        await theirs.patch(f"{URL}/{saved['id']}", json={"name": "Taken"}),
        await theirs.delete(f"{URL}/{saved['id']}"),
        await mine.patch(f"{URL}/{uuid4()}", json={"alerts": False}),
    ):
        assert code(response) == (404, "not_found")
    assert [item["name"] for item in (await ok(await mine.get(URL)))["items"]] == ["Mine"]
    member = await member_client(pitch_orgs.safaricom.member)  # type: ignore[arg-type]
    for response in (await member.get(URL), await member.post(URL, json={"name": "Org", "view": "problems"})):
        assert code(response) == (404, "not_found")
