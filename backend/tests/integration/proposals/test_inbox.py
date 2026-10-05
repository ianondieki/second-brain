"""The organisation Inbox (REQ-PROP-03, REQ-REPO-03; docs/spec/06 6.3): delivered tags newest first as Tier-1 teasers
with their engagement, cursor-paginated; any member may read it; the empty state carries the held count and the
verification level; a proposal hidden after it was pitched drops out; a held tag delivered on verification shows
without an engagement until one is opened (AC-PROP-1/b is P5's)."""

from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import Developers, ProposalWorld, published
from tests.integration.proposals.pitch_helpers import Members, PitchOrgs, add_member, pitch, pitchable

ITEM_KEYS = {"tag_id", "pitched_at", "engagement", "proposal", "shortlisted"}  # the star: P21 track B


async def test_newest_first_paged_and_readable_by_any_member(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    pitched: list[str] = []
    for n in range(3):
        dev, proposal_id = await pitchable(developers, proposal_world, title=f"Inbox idea {n}")
        assert (await pitch(dev, proposal_id, pitch_orgs.safaricom)).status_code == 201
        pitched.append(proposal_id)
    async with owner_engine.begin() as conn:
        viewer_id = await add_member(conn, pitch_orgs.safaricom.id, "{viewer}")
    viewer = await member_client(viewer_id)
    url = f"/api/orgs/{pitch_orgs.safaricom.id}/inbox"
    whole = (await viewer.get(url)).json()
    assert [item["proposal"]["id"] for item in whole["items"]] == pitched[::-1]
    assert whole["next_cursor"] is None
    assert (whole["held_count"], whole["verification"]) == (0, "e2")
    for item in whole["items"]:
        assert set(item) == ITEM_KEYS
        assert item["engagement"]["state"] == "SUBMITTED"
    walked: list[str] = []
    cursor: str | None = None
    while True:
        page = (await viewer.get(url, params={"limit": 1, **({"cursor": cursor} if cursor else {})})).json()
        walked.extend(item["tag_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == [item["tag_id"] for item in whole["items"]]
    bad = await viewer.get(url, params={"cursor": "nope"})
    assert (bad.status_code, bad.json()["detail"]["code"]) == (400, "invalid_cursor")


async def test_the_empty_state_and_a_hidden_proposal(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, member_client: Members
) -> None:
    reviewer = await member_client(pitch_orgs.airtel.member)  # type: ignore[arg-type]
    url = f"/api/orgs/{pitch_orgs.airtel.id}/inbox"
    empty = (await reviewer.get(url)).json()
    assert empty == {"items": [], "next_cursor": None, "held_count": 0, "verification": "e2"}
    dev, proposal_id = await pitchable(developers, proposal_world)
    assert (await pitch(dev, proposal_id, pitch_orgs.airtel)).status_code == 201
    assert len((await reviewer.get(url)).json()["items"]) == 1
    assert (await dev.delete(f"/api/me/proposals/{proposal_id}")).status_code == 200
    assert (await reviewer.get(url)).json()["items"] == []


async def test_a_held_tag_delivered_on_verification_shows_without_an_engagement(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    assert (await pitch(dev, proposal_id, pitch_orgs.claimed)).status_code == 201
    async with owner_engine.begin() as conn:  # E2 approval delivers held tags (app_decide_claim; staff's path)
        await conn.execute(
            text("UPDATE organizations SET verification = 'e2' WHERE id = :o"), {"o": pitch_orgs.claimed.id}
        )
        await conn.execute(
            text("UPDATE tags SET status = 'delivered' WHERE org_id = :o AND closed_at IS NULL"),
            {"o": pitch_orgs.claimed.id},
        )
    owner = await member_client(pitch_orgs.claimed.member)  # type: ignore[arg-type]
    inbox = (await owner.get(f"/api/orgs/{pitch_orgs.claimed.id}/inbox")).json()
    [item] = inbox["items"]
    assert (item["proposal"]["id"], item["engagement"], inbox["held_count"]) == (proposal_id, None, 0)
    await published(dev, proposal_world, title="Unrelated")  # the developer's other proposals do not appear
    assert len((await owner.get(f"/api/orgs/{pitch_orgs.claimed.id}/inbox")).json()["items"]) == 1


@pytest.mark.parametrize(
    "value",
    [
        [True, "x"],
        ["2026-09-29T10:00:00", "01920000-0000-7000-8000-000000000000"],  # no time zone
        [5, "01920000-0000-7000-8000-000000000000"],
        ["2026-09-29T10:00:00+00:00", ["x"]],
    ],
)
async def test_a_forged_inbox_cursor_answers_400(
    pitch_orgs: PitchOrgs, member_client: Members, value: list[object]
) -> None:
    reviewer = await member_client(pitch_orgs.airtel.member)  # type: ignore[arg-type]
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    response = await reviewer.get(f"/api/orgs/{pitch_orgs.airtel.id}/inbox", params={"cursor": cursor})
    assert (response.status_code, response.json()["detail"]["code"]) == (400, "invalid_cursor")
