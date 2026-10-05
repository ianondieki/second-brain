"""REQ-NOT-06, P21 track C: the notification settings API offers each person only the kinds that concern them. The
saved-search digest (a developer's saved Discover searches) is developer-only: a developer sees it off by default and
turns it on and off; an organisation's member without a developer profile neither sees nor sets it (422
``unknown_preference``, as for a kind nobody may set)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import Developers, rows, user_of
from tests.integration.proposals.pitch_helpers import Members, PitchOrgs

URL = "/api/me/notification-preferences"
DIGEST = {"kind": "saved_search_digest", "channel": "email"}


def kinds(body: dict[str, Any]) -> set[str]:
    return {item["kind"] for item in body["items"]}


async def test_the_digest_is_offered_to_developers_only(
    developers: Developers, pitch_orgs: PitchOrgs, member_client: Members, owner_engine: AsyncEngine
) -> None:
    developer = await developers()
    offered = (await developer.get(URL)).json()
    [digest] = [item for item in offered["items"] if item["kind"] == "saved_search_digest"]
    assert digest == {**DIGEST, "label": digest["label"], "default": False, "enabled": False}
    on = await developer.put(URL, json={**DIGEST, "enabled": True})
    assert on.status_code == 200, on.text
    assert next(item for item in on.json()["items"] if item["kind"] == "saved_search_digest")["enabled"] is True
    off = await developer.put(URL, json={**DIGEST, "enabled": False})
    assert next(item for item in off.json()["items"] if item["kind"] == "saved_search_digest")["enabled"] is False
    stored = await rows(
        owner_engine, "SELECT enabled FROM notification_preferences WHERE user_id = :u", u=user_of(developer)
    )
    assert [row.enabled for row in stored] == [False]  # one row, changed in place

    member = await member_client(pitch_orgs.safaricom.member)  # type: ignore[arg-type]
    listed = await member.get(URL)
    assert listed.status_code == 200
    assert "saved_search_digest" not in kinds(listed.json())
    refused = await member.put(URL, json={**DIGEST, "enabled": True})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "unknown_preference")
    assert (
        await rows(
            owner_engine, "SELECT 1 FROM notification_preferences WHERE user_id = :u", u=pitch_orgs.safaricom.member
        )
        == []
    )
