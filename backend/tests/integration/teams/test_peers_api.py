"""REQ-DEV-03 (D-58; P22 card C, C1 and C2): ``GET /api/me/peers`` and the switch on ``/api/me/profile``.

C1 opt-in only: a developer who has not turned Peers on gets an empty page (200, ``opted_in: false``) and never appears
to anyone; the switch is a PATCH of the profile. C2 county or niche: peers share the caller's county or a liked niche,
ordered by the number of shared niches, then the caller's county first, then the newest opt-in; the payload holds the
card's fields only (no email, phone, name, bio or verification level); the page is one statement. And the 0011 security
review's MINOR 5: the pages and the changes of county and liked niches are limited (429)."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from uuid import UUID

import pytest

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.teams import limits
from tests.integration.query_counts import show, statements
from tests.integration.teams.api_world import (
    PEERS,
    Clients,
    TeamsDb,
    code,
    developer,
    handle_of,
    niche,
    owner_rows,
    owner_run,
)

CARD_KEYS = {"user_id", "handle", "headline", "county_name", "shared_niches", "same_county"}
_COUNTIES: Iterator[int] = itertools.count(1)


def county() -> str:
    """A county no other test of the module uses (KE-01 to KE-47), so its peers are the test's own."""
    number = next(_COUNTIES)
    assert number <= 47, "the module ran out of counties"
    return f"KE-{number:02d}"


async def county_name(db: TeamsDb, code_: str) -> str:
    [row] = await owner_rows(db, "SELECT name FROM regions WHERE code = :c", c=code_)
    return str(row[0])


async def ids(client: object, page: int = 1) -> list[UUID]:
    response = await client.get(PEERS, params={"page": page})  # type: ignore[attr-defined]
    assert response.status_code == 200, response.text
    return [UUID(peer["user_id"]) for peer in response.json()["peers"]]


async def test_c1_peers_is_opt_in_and_the_switch_is_on_the_profile(teams: TeamsDb, as_user: Clients) -> None:
    here = county()
    shared, _ = await niche(teams, "shared")
    caller = await developer(teams, "caller", county=here, liked=(shared,), peers=False)
    listed = await developer(teams, "listed", county=here, liked=(shared,))
    hidden = await developer(teams, "hidden", county=here, liked=(shared,), peers=False)
    client = await as_user(caller)

    off = await client.get(PEERS)
    assert off.status_code == 200
    assert off.json() == {"peers": [], "next": None, "opted_in": False}

    profile = (await client.get("/api/me/profile")).json()
    assert (profile["peers_visible"], profile["county_code"]) == (False, here)
    assert profile["county_name"] == await county_name(teams, here)
    turned = await client.patch("/api/me/profile", json={"peers_visible": True})
    assert turned.status_code == 200, turned.text
    assert turned.json()["peers_visible"] is True
    assert "peers_opted_in_at" not in turned.json()
    [stored] = await owner_rows(teams, "SELECT peers_opted_in_at FROM developer_profiles WHERE user_id = :u", u=caller)
    assert stored[0] is not None  # the database's time, never shown

    on = (await client.get(PEERS)).json()
    assert on["opted_in"] is True
    assert [UUID(p["user_id"]) for p in on["peers"]] == [listed]  # the developer who stayed off never appears
    assert hidden not in await ids(await as_user(listed))
    assert caller in await ids(await as_user(listed))

    # null leaves the switch as it is; false turns it off again, and the caller leaves everyone's list
    assert (await client.patch("/api/me/profile", json={"peers_visible": None})).json()["peers_visible"] is True
    assert (await client.patch("/api/me/profile", json={"peers_visible": False})).json()["peers_visible"] is False
    assert caller not in await ids(await as_user(listed))
    assert (await client.get(PEERS)).json()["opted_in"] is False


async def test_c2_county_or_niche_in_order_with_the_card_only(teams: TeamsDb, as_user: Clients) -> None:
    here, there = county(), county()
    one, _ = await niche(teams, "alpha")
    two, _ = await niche(teams, "beta")
    caller = await developer(teams, "caller", county=here, liked=(one, two))
    both = await developer(teams, "both", county=there, liked=(one, two))  # two shared niches
    local = await developer(teams, "local", county=here, liked=(one,))  # one shared, same county
    older = await developer(teams, "older", county=there, liked=(two,))  # one shared, opted in first
    newer = await developer(teams, "newer", county=there, liked=(one,))  # one shared, opted in last
    neighbour = await developer(teams, "neighbour", county=here)  # same county, no shared niche
    await developer(teams, "stranger", county=there)  # neither: never listed
    await developer(teams, "off", county=here, liked=(one, two), peers=False)
    await developer(teams, "demo", county=here, liked=(one, two), demo=True)  # demo accounts list demo accounts
    client = await as_user(caller)

    with statements(teams.app) as seen:
        response = await client.get(PEERS)
    assert response.status_code == 200, response.text
    assert len([s for s in seen if "app_peers" in s]) == 1, show(seen)
    body = response.json()
    assert [UUID(p["user_id"]) for p in body["peers"]] == [both, local, newer, older, neighbour]
    assert body["next"] is None
    for peer in body["peers"]:
        assert set(peer) == CARD_KEYS
    first = body["peers"][0]
    assert first["handle"] == await handle_of(teams, both)
    assert first["county_name"] == await county_name(teams, there)
    assert first["same_county"] is False
    assert len(first["shared_niches"]) == 2
    assert first["shared_niches"] == sorted(first["shared_niches"])
    assert body["peers"][1]["same_county"] is True
    assert body["peers"][4]["shared_niches"] == []
    raw = response.text
    for secret in ("A private bio", "@developers.example.test", "verification", "email", "phone"):
        assert secret not in raw


async def test_c2_pages_of_twenty(teams: TeamsDb, as_user: Clients) -> None:
    here = county()
    caller = await developer(teams, "pager", county=here)
    made = [await developer(teams, f"p{n}", county=here) for n in range(21)]
    client = await as_user(caller)
    first = (await client.get(PEERS)).json()
    assert (len(first["peers"]), first["next"]) == (20, 2)
    second = (await client.get(PEERS, params={"page": 2})).json()
    assert (len(second["peers"]), second["next"]) == (1, None)
    seen = {UUID(p["user_id"]) for p in first["peers"] + second["peers"]}
    assert seen == set(made)
    assert made[-1] == UUID(first["peers"][0]["user_id"])  # the newest opt-in first among equals
    assert (await client.get(PEERS, params={"page": 0})).status_code == 422


async def _spent(teams: TeamsDb, purpose: str, user: UUID, count: int) -> None:
    """``count`` earlier actions of ``user`` in the ledger, as the app records them (HMAC digests)."""
    keys = limits.ledger_keys(get_settings().secret_key.get_secret_value(), purpose, user)
    for _ in range(count):
        await owner_run(
            teams,
            "INSERT INTO login_attempts (id, email_digest, ip_digest, succeeded) VALUES (:id, :e, :i, true)",
            id=uuid7(),
            e=keys.email,
            i=keys.ip,
        )


async def test_the_peers_page_is_limited_per_hour(teams: TeamsDb, as_user: Clients) -> None:
    here = county()
    caller = await developer(teams, "harvester", county=here)
    off = await developer(teams, "quiet", county=here, peers=False)
    await _spent(teams, limits.PEERS_PAGE, caller, 59)
    client = await as_user(caller)
    assert (await client.get(PEERS)).status_code == 200  # the 60th page of the hour
    refused = await client.get(PEERS)
    assert code(refused) == (429, "too_many_peer_pages")
    assert 3500 <= int(refused.headers["Retry-After"]) <= 3600
    await _spent(teams, limits.PEERS_PAGE, off, 70)
    assert (await (await as_user(off)).get(PEERS)).status_code == 200  # nothing is read, nothing is counted


@pytest.mark.parametrize("via", ["county", "niches"])
async def test_county_and_niche_changes_are_limited_per_day(teams: TeamsDb, as_user: Clients, via: str) -> None:
    here, there = county(), county()
    niches = [(await niche(teams, f"n{n}"))[0] for n in range(4)]
    user = await developer(teams, "rotator", county=here, liked=tuple(niches[:3]))
    await _spent(teams, limits.PROFILE_CHANGE, user, 9)
    client = await as_user(user)
    assert (await client.patch("/api/me/profile", json={"county_code": here})).status_code == 200  # no change
    assert (await client.patch("/api/me/profile", json={"headline": "Still me"})).status_code == 200
    same = await client.put("/api/me/niches", json={"liked": [str(n) for n in niches[:3]]})
    assert same.status_code == 200  # the same set is no change
    assert (await client.patch("/api/me/profile", json={"county_code": there})).status_code == 200  # the 10th
    if via == "county":
        refused = await client.patch("/api/me/profile", json={"county_code": here})
    else:
        refused = await client.put("/api/me/niches", json={"liked": [str(n) for n in niches[1:]]})
    assert code(refused) == (429, "too_many_profile_changes")
    assert int(refused.headers["Retry-After"]) > 0
    profile = (await client.get("/api/me/profile")).json()
    assert profile["county_code"] == there  # the refused change changed nothing
    [liked] = await owner_rows(
        teams, "SELECT count(*) FROM developer_niches WHERE user_id = :u AND niche_id = :n", u=user, n=niches[3]
    )
    assert liked[0] == 0
    assert (await client.patch("/api/me/profile", json={"peers_visible": False})).status_code == 200  # not a change


async def test_a_refused_change_is_not_counted(teams: TeamsDb, as_user: Clients) -> None:
    user = await developer(teams, "typo", county=county())
    client = await as_user(user)
    assert code(await client.patch("/api/me/profile", json={"county_code": "KE-99"})) == (422, "unknown_county")
    assert code(await client.put("/api/me/niches", json={"liked": [str(uuid7())] * 3})) == (422, "liked_niches_count")
    keys = limits.ledger_keys(get_settings().secret_key.get_secret_value(), limits.PROFILE_CHANGE, user)
    [count] = await owner_rows(teams, "SELECT count(*) FROM login_attempts WHERE email_digest = :e", e=keys.email)
    assert count[0] == 0
