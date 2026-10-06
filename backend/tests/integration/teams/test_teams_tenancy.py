"""REQ-DEV-03 (D-58 "no organisation route ever returns peers, teams or threads"; P22 card C, C6): an
organisation-only account and staff get 404 on every peers, teams, blocks and contributors route, as for a path that
does not exist; a developer who is not a party gets 404 on another pair's invitation and thread."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from bridge.ids import uuid7
from tests.integration.api import make_client
from tests.integration.teams.api_world import (
    BLOCKS,
    INVITATIONS,
    PEERS,
    TEAMS,
    Clients,
    TeamsDb,
    code,
    developer,
    invite,
    niche,
    org_only,
    post,
    problem,
    staff,
    team,
)


def routes(thread: str, invitation: str, message: str, proposal: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every peers and teams route, with a body where one is needed."""
    some = str(uuid7())
    return [
        ("GET", PEERS, None),
        ("GET", TEAMS, None),
        ("GET", f"{TEAMS}/unread-count", None),
        ("GET", INVITATIONS, None),
        ("POST", INVITATIONS, {"to_user_id": some, "problem_id": some}),
        ("POST", f"{INVITATIONS}/{invitation}/accept", None),
        ("POST", f"{INVITATIONS}/{invitation}/decline", None),
        ("POST", f"{INVITATIONS}/{invitation}/withdraw", None),
        ("GET", f"{TEAMS}/{thread}", None),
        ("POST", f"{TEAMS}/{thread}/messages", {"body": "Hello"}),
        ("POST", f"{TEAMS}/{thread}/read", {}),
        ("POST", f"{TEAMS}/{thread}/leave", None),
        ("POST", f"{TEAMS}/{thread}/messages/{message}/report", {"reasons": ["spam"]}),
        ("GET", BLOCKS, None),
        ("POST", BLOCKS, {"user_id": some}),
        ("DELETE", f"{BLOCKS}/{some}", None),
        ("GET", f"/api/me/ideas/{proposal}/contributors", None),
        ("POST", f"/api/me/ideas/{proposal}/contributors", {"user_id": some}),
        ("DELETE", f"/api/me/ideas/{proposal}/contributors/{some}", None),
        ("GET", "/api/me/contributions", None),
        ("DELETE", f"/api/me/contributions/{proposal}", None),
    ]


async def call(client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any] | None) -> httpx.Response:
    return await client.request(method, path, json=body) if body is not None else await client.request(method, path)


@pytest.mark.parametrize("who", ["org_only", "staff_admin", "staff_moderator"])
async def test_c6_organisations_and_staff_get_404_everywhere(teams: TeamsDb, as_user: Clients, who: str) -> None:
    shared, _ = await niche(teams, f"c6{who}")
    a = await as_user(await developer(teams, "c6a", liked=(shared,)))
    b = await as_user(await developer(teams, "c6b", liked=(shared,)))
    thread = await team(a, b, await problem(teams))
    message = (await post(a, thread)).json()["id"]
    invitation = (await invite(a, b.user_id, await problem(teams)))["id"]  # type: ignore[attr-defined]
    if who == "org_only":
        outsider = await as_user((await org_only(teams)).owner, fresh=True)
    else:
        outsider = await as_user(await staff(teams, who.removeprefix("staff_")), fresh=True)
    for method, path, body in routes(thread, invitation, message, str(uuid7())):
        response = await call(outsider, method, path, body)
        assert code(response) == (404, "not_found"), (method, path, response.text)
        assert response.json()["detail"]["message"] == "Not found."  # the same body as a path that does not exist


async def test_c6_a_third_developer_gets_404_on_another_pairs_invitation_and_thread(
    teams: TeamsDb, as_user: Clients
) -> None:
    shared, _ = await niche(teams, "c6third")
    a = await as_user(await developer(teams, "c6ta", liked=(shared,)))
    b = await as_user(await developer(teams, "c6tb", liked=(shared,)))
    third = await as_user(await developer(teams, "c6tc", liked=(shared,)))
    thread = await team(a, b, await problem(teams))
    message = (await post(a, thread)).json()["id"]
    invitation = (await invite(a, b.user_id, await problem(teams)))["id"]  # type: ignore[attr-defined]
    for method, path, body in routes(thread, invitation, message, str(uuid7()))[5:13]:
        response = await call(third, method, path, body)
        assert response.status_code == 404, (method, path, response.text)
    assert (await third.get(TEAMS)).json() == {"threads": []}
    assert (await third.get(INVITATIONS)).json() == {"received": [], "sent": []}
    assert (await third.get(f"{TEAMS}/unread-count")).json() == {"unread": 0}
    # signed out: 401 as on every /api/me route
    async with make_client(teams.app) as anonymous:
        assert (await anonymous.get(PEERS)).status_code == 401
