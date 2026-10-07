"""REQ-PERS-01 (docs/spec/06 6.7): ``GET /api/me/recommendations`` through the API.

- AC-PERS-1: a brand-new developer with 3 liked niches and a county gets a non-empty list, every card explained (a
  pursuit decision with a reason, at least one Why chip, a label and its feature vector).
- AC-PERS-7: only approved research cards and verified organisations' Briefs are recommended (never a candidate or a
  developer's problem); each row's f5 is the card's trend z-score (the one Discover shows) and f6 its confidence.
- AC-PERS-3: with the ``profiling`` consent the developer's own history (f1, f9) is used; turning it off removes f1
  and f9 and no profile embedding is ever computed.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.matching.ranker import Developer
from bridge.matching.ranking_config import get_ranking
from bridge.matching.recommendations import developer as developer_context
from tests.integration.engagements.api_world import clients
from tests.integration.matching.trend_world import TrendWorld, brief, build, developer_problem, proposal, research_card
from tests.integration.proposals.helpers import Developers, rows, user_of

FEATURES = {
    "semantic_fit",
    "niche_match",
    "region_match",
    "skill_coverage",
    "trend",
    "evidence_confidence",
    "market_pull",
    "crowding",
    "track_record",
    "freshness",
}


async def onboard(developer: httpx.AsyncClient, world: TrendWorld, county: str = "KE-30") -> None:
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
    assert (await developer.put("/api/me/niches", json=liked)).status_code == 200
    assert (await developer.patch("/api/me/profile", json={"county_code": county})).status_code == 200


async def recommended(developer: httpx.AsyncClient) -> dict[str, Any]:
    response = await developer.get("/api/me/recommendations")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_brand_new_developer_gets_an_explained_list(owner_engine: AsyncEngine, developers: Developers) -> None:
    """AC-PERS-1."""
    world = await build(owner_engine)
    cards = [await research_card(owner_engine, niche, county="KE-30") for niche in (world.niche, world.sibling)]
    cards.append(await brief(owner_engine, world.elsewhere))
    developer = await developers()
    await onboard(developer, world)
    body = await recommended(developer)
    assert body["personalised"] is False
    assert body["ranker_version"] == "hybrid-v1"
    assert {n["id"] for n in body["liked_niches"]} == {str(world.niche), str(world.sibling), str(world.elsewhere)}
    items = body["items"]
    assert items
    assert {str(c) for c in cards} <= {i["problem"]["id"] for i in items}
    for item in items:
        assert item["why"]
        assert item["pursuit"]["reasons"]
        assert item["pursuit"]["label"] in {"Pursue", "Consider", "Not now"}
        assert item["label"] in {"Strong fit", "Good fit", "Stretch"}
        assert set(item["features"]) == FEATURES
    mine = [i for i in items if i["problem"]["id"] in {str(c) for c in cards}]
    assert all("In a niche you like" in i["why"] for i in mine)
    assert [i["position"] for i in items] == list(range(1, len(items) + 1))


async def test_only_approved_cards_and_briefs_with_their_z_score_and_confidence(
    owner_engine: AsyncEngine, developers: Developers
) -> None:
    """AC-PERS-7."""
    world = await build(owner_engine)
    history = (0.5, 1.5, 2.5, 20.0, 34.0, 48.0, 62.0, 76.0, 90.0)
    rising = await research_card(owner_engine, world.niche, source_days=history, age_days=100, confidence="0.870")
    candidate = await research_card(owner_engine, world.niche, status="candidate", title="Candidate card")
    reported = await developer_problem(owner_engine, world.author, world.niche, age_days=1)
    # Outside rising's family (Transport, not Farming): a sibling Brief costs rising MMR overlap, and against the
    # session database's other cards (after engagements/ and problems/ ran) it then falls out of the top 10.
    posted = await brief(owner_engine, world.elsewhere)
    developer = await developers()
    await onboard(developer, world)
    body = await recommended(developer)
    ids = {i["problem"]["id"]: i for i in body["items"]}
    assert {str(rising), str(posted)} <= set(ids)
    assert str(candidate) not in ids
    assert str(reported) not in ids
    assert all(i["problem"]["source"] in {"research_agent", "org_brief"} for i in body["items"])

    card = ids[str(rising)]
    discover = (await developer.get("/api/discover/trending", params={"niche": world.slug("niche")})).json()
    [shown] = [p for p in discover["problems"] if p["problem"]["id"] == str(rising)]
    assert shown["trend"]["trending"] is True
    assert card["features"]["trend"]["raw"] == shown["trend"]["z"] == card["trend"]["z"]
    assert card["features"]["evidence_confidence"]["raw"] == 0.87
    assert ids[str(posted)]["features"]["evidence_confidence"]["raw"] == 1.0  # a verified organisation's Brief


async def test_turning_profiling_off_removes_f1_and_f9(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers
) -> None:
    """AC-PERS-3."""
    world = await build(owner_engine)
    card = await research_card(owner_engine, world.niche, title="Grain drought planning for farmers")
    developer = await developers()
    await onboard(developer, world)
    headline = {"headline": "I build drought and harvest planning tools for grain farmers"}
    assert (await developer.patch("/api/me/profile", json=headline)).status_code == 200
    version = (await developer.get("/api/consents")).json()["version"]

    async def profiling(granted: bool) -> dict[str, Any]:
        decision = {"profiling": {"granted": granted, "version": version}}
        assert (await developer.put("/api/me/consents", json=decision)).status_code == 200
        body = await recommended(developer)
        [item] = [i for i in body["items"] if i["problem"]["id"] == str(card)]
        return {"personalised": body["personalised"], **item["features"]}

    on = await profiling(True)
    assert on["personalised"] is True
    assert on["semantic_fit"]["applies"] is True
    assert on["semantic_fit"]["raw"] >= 3  # grain, drought, farmers (and more) shared with the headline
    assert on["track_record"]["applies"] is True
    off = await profiling(False)
    assert off["personalised"] is False
    for name in ("semantic_fit", "track_record"):
        assert (off[name]["applies"], off[name]["value"]) == (False, None)
    [profile] = await rows(
        owner_engine, "SELECT profile_embedding FROM developer_profiles WHERE user_id = :u", u=user_of(developer)
    )
    assert profile.profile_embedding is None  # no profile embedding is computed in the prototype


async def test_recommendations_need_a_developer_profile(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> None:
    world = await build(owner_engine)  # its author is a user without a developer profile
    async with clients(app_engine, get_settings(), world.author) as (user,):
        assert (await user.get("/api/me/recommendations")).status_code == 404
        assert (await user.get("/api/me/niches")).status_code == 404


async def test_without_the_consent_no_history_is_read(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers
) -> None:
    """AC-PERS-3: the developer context holds no keywords and no track record unless the consent is on (the history
    is not read at all, not merely left unused by the ranker)."""
    world = await build(owner_engine)
    developer = await developers()
    me = user_of(developer)
    await onboard(developer, world)
    assert (await developer.patch("/api/me/profile", json={"headline": "Grain drought tools"})).status_code == 200
    problem = await developer_problem(owner_engine, world.author, world.niche)
    await proposal(owner_engine, world.niche, problem, owner=me, age_days=2, title="Drought planning for grain")
    factory = create_session_factory(app_engine)

    async def context() -> Developer:
        async with factory() as db:
            await bind_tenant(db, user_id=me)
            return await developer_context(db, me, get_ranking())

    off = await context()
    assert (off.personalised, off.keywords, dict(off.track)) == (False, frozenset(), {})
    version = (await developer.get("/api/consents")).json()["version"]
    decision = {"profiling": {"granted": True, "version": version}}
    assert (await developer.put("/api/me/consents", json=decision)).status_code == 200
    on = await context()
    assert on.personalised
    assert {"grain", "drought", "planning", "tools"} <= on.keywords
    assert {"drought", "planning", "grain"} <= on.proposal_keywords  # the proposal's title
    assert "tools" not in on.proposal_keywords  # a headline word only
    assert dict(on.track) == {world.niche: (1, 0)}
