"""REQ-UX-01 (P25-B, D-67): ``GET /api/me/search`` against the database, as each person of the scene
(``tests.integration.me.scene``).

- A developer finds their own ideas (drafts included) and engagement, the readable problems and the listed companies;
  never another developer's draft, a held or pending problem, an organisation's draft or invited-only Brief, another
  party's engagement, or a company that is not listed (not verified, delisted).
- An organisation member finds their organisation's Inbox (a held proposal's pitch left out), engagement and Briefs
  (every state) and the problems everyone reads (not their own Briefs again), and no companies (the Companies
  screen is the developer portal's); a member of several organisations gets ``?org=`` on their organisation's links,
  and an organisation whose role needs a second factor this session has not given is left out, as its routes would
  refuse it. A developer who is a member of an unlisted organisation never finds it among the companies.
- Staff find what every developer finds among problems (no companies), though RLS shows them more.
- ``%``, ``_`` and ``\\`` match themselves; past 30 searches in 10 seconds it is 429 with ``Retry-After``; each read
  is read-only with a 2 s statement timeout; the answer says ``Cache-Control: private, no-store`` and has the OpenAPI
  document's shape.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.me import search
from bridge.me.caller import Caller
from bridge.me.schemas import SearchResults
from tests.integration.api import make_client
from tests.integration.engagements import tracker as t
from tests.integration.me.conftest import SignedIn
from tests.integration.me.scene import Scene, idea, niche, person
from tests.unit.public.openapi_shape import conforms

PATH = "/api/me/search"


async def found(client: httpx.AsyncClient, q: str) -> dict[str, list[dict[str, Any]]]:
    """One search: 200, ``private, no-store``, the OpenAPI shape; the items by group."""
    response = await client.get(PATH, params={"q": q})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    document = client.app.openapi()  # type: ignore[attr-defined]
    schema = document["paths"][PATH]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    conforms(body, schema, document["components"]["schemas"])
    assert body["q"] == q.strip()
    return {group["kind"]: group["items"] for group in body["groups"]}


def ids(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items}


def everything(groups: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {item["id"] for items in groups.values() for item in items}


def private_ids(scene: Scene) -> set[str]:
    """What no search of anybody's may find outside its owner's own groups: held, pending, draft and invited."""
    return {str(scene.problems[label]) for label in ("held", "pending", "brief_a_draft", "brief_a_invited")} | {
        str(scene.gamma),
        str(scene.delta),
    }


async def test_a_developer_finds_their_own_ideas_and_engagement_and_what_everyone_reads(
    scene: Scene, signed_in: SignedIn
) -> None:
    async with signed_in(scene.amina) as client:
        groups = await found(client, f"  {scene.word}  ")
    assert list(groups) == ["ideas", "engagements", "problems", "companies"]
    assert ids(groups["ideas"]) == {str(scene.ideas["amina_pub"]), str(scene.ideas["amina_draft"])}
    draft = next(item for item in groups["ideas"] if item["id"] == str(scene.ideas["amina_draft"]))
    assert draft == {
        "id": str(scene.ideas["amina_draft"]),
        "title": scene.title("amina_draft"),
        "subtitle": scene.niche_label,
        "href": f"/dev/ideas/{scene.ideas['amina_draft']}",
    }
    assert groups["engagements"] == [
        {
            "id": str(scene.engagements["amina_alpha"]),
            "title": scene.title("amina_pub"),
            "subtitle": f"{scene.word} Alpha Sacco Ltd · Proposal submitted",
            "href": f"/dev/engagements/{scene.engagements['amina_alpha']}",
        }
    ]
    assert ids(groups["problems"]) == {str(scene.problems[label]) for label in ("public", "brief_a", "brief_b")}
    assert {item["href"] for item in groups["problems"]} == {
        f"/problems/{scene.problems[label]}" for label in ("public", "brief_a", "brief_b")
    }
    assert groups["companies"] == [
        {
            "id": str(scene.alpha),
            "title": f"{scene.word} Alpha Sacco Ltd",
            "subtitle": "SACCO/MFI",
            "href": f"/dev/companies/{scene.alpha}",
        },
        {
            "id": str(scene.beta),
            "title": f"{scene.word} Beta Telco Ltd",
            "subtitle": "SACCO/MFI",
            "href": f"/dev/companies/{scene.beta}",
        },
    ]
    others = {str(scene.ideas[label]) for label in ("brian_pub", "brian_held", "brian_draft")}
    assert everything(groups) & (private_ids(scene) | others | {str(scene.engagements["brian_beta"])}) == set()


async def test_another_developer_never_finds_amina_s_draft_or_engagement(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.brian) as client:
        groups = await found(client, scene.word)
        by_counterpart = await found(client, "Beta Telco")
    assert ids(groups["ideas"]) == {str(scene.ideas[label]) for label in ("brian_pub", "brian_held", "brian_draft")}
    assert ids(groups["engagements"]) == {str(scene.engagements["brian_beta"])}
    assert str(scene.ideas["amina_draft"]) not in everything(groups)
    assert str(scene.engagements["amina_alpha"]) not in everything(groups)
    assert everything(groups) & private_ids(scene) == set()
    assert scene.title("amina_draft") not in str(groups)
    # The counterpart organisation's name finds the developer's own engagement with it.
    assert str(scene.engagements["brian_beta"]) in ids(by_counterpart.get("engagements", []))


async def test_a_member_finds_their_organisation_s_inbox_engagement_and_briefs(
    scene: Scene, signed_in: SignedIn
) -> None:
    async with signed_in(scene.member_a) as client:
        groups = await found(client, scene.word)
    assert list(groups) == ["inbox", "engagements", "briefs", "problems"]  # no companies outside the developer portal
    assert groups["inbox"] == [
        {
            "id": str(scene.tags["amina_alpha"]),
            "title": scene.title("amina_pub"),
            "subtitle": scene.niche_label,
            "href": f"/org/inbox/{scene.ideas['amina_pub']}",
        }
    ]  # Brian's held proposal, pitched to Alpha too, is not in the Inbox
    assert groups["engagements"] == [
        {
            "id": str(scene.engagements["amina_alpha"]),
            "title": scene.title("amina_pub"),
            "subtitle": "Proposal submitted",
            "href": f"/org/engagements/{scene.engagements['amina_alpha']}",
        }
    ]
    briefs = {str(scene.problems[label]) for label in ("brief_a", "brief_a_draft", "brief_a_invited")}
    assert ids(groups["briefs"]) == briefs
    assert {item["href"] for item in groups["briefs"]} == {f"/org/problems/{problem}" for problem in briefs}
    assert ids(groups["problems"]) == {str(scene.problems[label]) for label in ("public", "brief_b")}
    assert str(scene.engagements["brian_beta"]) not in everything(groups)
    assert {str(scene.ideas["brian_held"]), str(scene.tags["brian_held_alpha"])} & everything(groups) == set()


async def test_a_member_of_several_keeps_the_organisation_and_never_sees_another_s_private_brief(
    scene: Scene, signed_in: SignedIn
) -> None:
    async with signed_in(scene.member_b) as client:
        groups = await found(client, scene.word)
    org = f"?org={scene.beta}"
    assert groups["inbox"] == [
        {
            "id": str(scene.tags["brian_beta"]),
            "title": scene.title("brian_pub"),
            "subtitle": scene.niche_label,
            "href": f"/org/inbox/{scene.ideas['brian_pub']}{org}",
        }
    ]
    assert [item["href"] for item in groups["engagements"]] == [
        f"/org/engagements/{scene.engagements['brian_beta']}{org}"
    ]
    assert [item["href"] for item in groups["briefs"]] == [f"/org/problems/{scene.problems['brief_b']}{org}"]
    assert ids(groups["problems"]) == {str(scene.problems[label]) for label in ("public", "brief_a")}
    assert list(groups) == ["inbox", "engagements", "briefs", "problems"]
    assert everything(groups) & private_ids(scene) == set()
    assert str(scene.engagements["amina_alpha"]) not in everything(groups)


async def test_an_organisation_whose_role_needs_a_second_factor_not_given_is_left_out(
    scene: Scene, signed_in: SignedIn
) -> None:
    async with signed_in(scene.member_b, mfa_verified=False) as client:
        groups = await found(client, scene.word)
    assert list(groups) == ["problems"]  # Beta's Inbox, engagement and Brief need the second factor
    assert ids(groups["problems"]) == {str(scene.problems[label]) for label in ("public", "brief_a", "brief_b")}


async def test_staff_find_only_what_every_developer_finds(scene: Scene, signed_in: SignedIn) -> None:
    async with signed_in(scene.staff) as client:
        groups = await found(client, scene.word)
    assert list(groups) == ["problems"]
    assert ids(groups["problems"]) == {str(scene.problems[label]) for label in ("public", "brief_a", "brief_b")}


async def test_a_developer_never_finds_their_own_unlisted_organisation_among_the_companies(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    """Gamma (not verified) is this developer's own organisation, which RLS lets them read: still not listed."""
    async with owner_engine.begin() as conn:
        insider = await person(conn, "insider", developer=True)
        await t.member(conn, scene.gamma, insider, "{viewer}")
        await t.member(conn, scene.delta, insider, "{viewer}")
    async with signed_in(insider) as client:
        groups = await found(client, scene.word)
    assert list(groups) == ["problems", "companies"]
    assert ids(groups["companies"]) == {str(scene.alpha), str(scene.beta)}


async def test_the_best_match_comes_first_and_a_group_holds_at_most_five(
    scene: Scene, signed_in: SignedIn, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        many = await person(conn, "many", developer=True)
        topic = await niche(conn, f"{scene.word} Many")
        for n in range(6):
            await idea(conn, many, f"Old {scene.word} idea {n}", niche_id=topic, problem_id=scene.problems["public"])
        best = await idea(
            conn,
            many,
            f"{scene.word} starts here",
            niche_id=topic,
            problem_id=scene.problems["public"],
            registered=False,
        )
    async with signed_in(many) as client:
        groups = await found(client, scene.word)
    assert len(groups["ideas"]) == search.GROUP_SIZE
    assert groups["ideas"][0]["id"] == str(best[0])  # starts with the words, though not the newest change
    assert [item["title"] for item in groups["ideas"][1:]] == [f"Old {scene.word} idea {n}" for n in (5, 4, 3, 2)]


async def test_an_emoji_sequence_and_a_soft_hyphen_are_searched_as_typed(scene: Scene, signed_in: SignedIn) -> None:
    """Format characters (a zero-width joiner, a soft hyphen) are text: searched, never a 422."""
    family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
    async with signed_in(scene.amina) as client:
        assert await found(client, f" {family} co\u00adop ") == {}
        assert await found(client, f"{scene.word}\u00ad") == {}


@pytest.mark.parametrize("suffix", ["%", "_", "\\", "%%", " _"])
async def test_like_wildcards_and_the_escape_match_only_themselves(
    scene: Scene, signed_in: SignedIn, suffix: str
) -> None:
    async with signed_in(scene.amina) as client:
        assert await found(client, scene.word + suffix) == {}
        trailing = await found(client, scene.word[:-1] + "_")  # an unescaped _ would match the last character
    assert trailing == {}


async def test_past_thirty_searches_in_ten_seconds_it_is_429_with_retry_after(
    owner_engine: AsyncEngine, signed_in: SignedIn
) -> None:
    async with owner_engine.begin() as conn:
        quick = await person(conn, "quick", developer=True)
    async with signed_in(quick) as client:
        for n in range(30):
            response = await client.get(PATH, params={"q": f"zz{n}"})
            assert response.status_code == 200, (n, response.text)
        refused = await client.get(PATH, params={"q": "zz-more"})
        assert refused.status_code == 429
        assert refused.json()["detail"]["code"] == "rate_limited"
        assert 1 <= int(refused.headers["retry-after"]) <= 10
        assert refused.headers["cache-control"] == "no-store"
        assert (await client.get(PATH, params={"q": "z"})).status_code == 422  # validation comes first


async def test_each_search_reads_read_only_with_a_two_second_timeout_as_the_caller(
    scene: Scene, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def run(db: AsyncSession, caller: Caller, term: str) -> SearchResults:
        settings = text(
            "SELECT current_setting('transaction_read_only') AS ro, current_setting('statement_timeout') AS timeout,"
            " current_setting('app.user_id') AS who"
        )
        seen.update((await db.execute(settings)).one()._asdict())
        seen["caller"] = caller
        return SearchResults(q=term, groups=[])

    monkeypatch.setattr(search, "run", run)
    async with signed_in(scene.member_b) as client:
        assert (await client.get(PATH, params={"q": "anything"})).status_code == 200
    assert (seen["ro"], seen["timeout"], seen["who"]) == ("on", "2s", str(scene.member_b))
    assert seen["caller"] == Caller(scene.member_b, "org", (scene.beta, scene.gamma), several=True)  # by name


async def test_signed_out_is_401(app_engine: AsyncEngine) -> None:
    async with make_client(app_engine) as client:
        response = await client.get(PATH, params={"q": "sacco"})
    assert response.status_code == 401
