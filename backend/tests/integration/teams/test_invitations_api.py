"""REQ-DEV-03 (D-58; P22 card C, C3): team-up invitations tied to a published, clear problem or a public, published
Brief; accept opens a thread and notifies (N29), decline and withdraw by the right party; N28 to the invited developer;
10 a day per sender; a block ends pending invitations, closes threads and hides both from each other's peers, and an
unblock keeps the threads closed. Every refusal about another developer is the same 404 (a stranger, someone who
turned Peers off, a blocked developer, an unknown id)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.teams import limits
from tests.integration.teams.api_world import (
    BLOCKS,
    INVITATIONS,
    PEERS,
    TEAMS,
    Clients,
    TeamsDb,
    accept,
    audits,
    brief,
    code,
    developer,
    forward,
    handle_of,
    invite,
    niche,
    notices,
    org_only,
    owner_rows,
    owner_run,
    post,
    problem,
    problem_title,
    team,
)


async def pair(teams: TeamsDb, label: str = "pair") -> tuple[UUID, UUID, UUID]:
    """Two developers who are each other's peers (a shared niche of their own), and a third one in it too."""
    shared, _ = await niche(teams, label)
    return (
        await developer(teams, f"{label}a", liked=(shared,)),
        await developer(teams, f"{label}b", liked=(shared,)),
        await developer(teams, f"{label}c", liked=(shared,)),
    )


async def test_c3_an_invitation_is_tied_to_an_open_problem(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, _ = await pair(teams, "open")
    client = await as_user(amina)
    org = await org_only(teams)
    for closed in (
        await problem(teams, status="candidate"),
        await problem(teams, moderation_state="held"),
        await problem(teams, status="archived"),
        await brief(teams, org, visibility="invited"),
        await brief(teams, org, visibility="public", status="closed"),
        uuid7(),
    ):
        refused = await client.post(INVITATIONS, json={"to_user_id": str(brian), "problem_id": str(closed)})
        assert code(refused) == (404, "problem_unavailable"), closed
    public_brief = await brief(teams, org, visibility="public")
    made = await invite(client, brian, public_brief, note="  \uff33hall we team up?\r\nCall me on 0712 345 678.  ")
    assert made["note"] == "Shall we team up?\nCall me on 0712 345 678."  # NFKC; the contact rule does not apply
    assert (made["status"], made["direction"], made["decided_at"]) == ("pending", "sent", None)
    assert made["counterpart"] == {
        "user_id": str(brian),
        "handle": await handle_of(teams, brian),
        "headline": "Openb builds things",
    }
    assert made["problem"] == {"id": str(public_brief), "title": await problem_title(teams, public_brief)}
    [event] = await audits(teams, "team.invited", amina)
    assert event.payload == {"to_user_id": str(brian), "problem_id": str(public_brief)}  # never the note
    [n28] = await notices(teams, brian, "team.n28")
    assert n28.title == f"Team-up invitation from {await handle_of(teams, amina)}"
    assert (n28.body, n28.link) == (await problem_title(teams, public_brief), "/dev/teams")
    assert "Call me" not in str(n28)


async def test_a_note_is_plain_text_of_300_characters(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, _ = await pair(teams, "note")
    client = await as_user(amina)
    problem_id = await problem(teams)
    for bad in ("a" * 301, "bell\x07", "right‮left", "zero​width", "x" * 2001):
        refused = await client.post(
            INVITATIONS, json={"to_user_id": str(brian), "problem_id": str(problem_id), "note": bad}
        )
        assert refused.status_code == 422, bad
        assert bad not in refused.text
    made = await invite(client, brian, problem_id, note="   ")
    assert made["note"] is None
    assert code(await client.post(INVITATIONS, json={"to_user_id": str(amina), "problem_id": str(problem_id)})) == (
        422,
        "cannot_invite_yourself",
    )


async def test_c3_only_peers_and_counterparts_and_one_pending_per_pair(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, _ = await pair(teams, "who")
    stranger = await developer(teams, "stranger")  # no shared county or niche
    off = await developer(teams, "off", liked=())
    problem_id = await problem(teams)
    client = await as_user(amina)
    for nobody in (stranger, off, uuid7()):
        refused = await client.post(INVITATIONS, json={"to_user_id": str(nobody), "problem_id": str(problem_id)})
        assert code(refused) == (404, "peer_unavailable")
    await invite(client, brian, problem_id)
    again = await client.post(INVITATIONS, json={"to_user_id": str(brian), "problem_id": str(problem_id)})
    assert code(again) == (409, "already_invited")
    back = await (await as_user(brian)).post(
        INVITATIONS, json={"to_user_id": str(amina), "problem_id": str(problem_id)}
    )
    assert code(back) == (409, "already_invited")  # either way round
    hidden = await developer(teams, "hidden", peers=False)
    refused = await (await as_user(hidden)).post(
        INVITATIONS, json={"to_user_id": str(amina), "problem_id": str(problem_id)}
    )
    assert code(refused) == (403, "peers_off")


async def test_c3_accept_decline_and_withdraw_by_the_right_party(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, carol = await pair(teams, "decide")
    sender, recipient, third = await as_user(amina), await as_user(brian), await as_user(carol)
    first, second, third_problem = await problem(teams), await problem(teams), await problem(teams)
    one = await invite(sender, brian, first)
    two = await invite(sender, brian, second)
    three = await invite(sender, brian, third_problem)

    listed = (await recipient.get(INVITATIONS)).json()
    assert {i["id"] for i in listed["received"]} == {one["id"], two["id"], three["id"]}
    assert listed["sent"] == []
    assert listed["received"][0]["counterpart"]["handle"] == await handle_of(teams, amina)
    assert {i["id"] for i in (await sender.get(INVITATIONS)).json()["sent"]} == {one["id"], two["id"], three["id"]}

    assert code(await third.post(f"{INVITATIONS}/{one['id']}/accept")) == (404, "not_found")  # not a party
    assert code(await sender.post(f"{INVITATIONS}/{one['id']}/accept")) == (403, "wrong_party")
    assert code(await recipient.post(f"{INVITATIONS}/{one['id']}/withdraw")) == (403, "wrong_party")
    thread = await accept(recipient, one["id"])
    assert code(await recipient.post(f"{INVITATIONS}/{one['id']}/accept")) == (409, "already_decided")
    assert (await recipient.post(f"{INVITATIONS}/{two['id']}/decline")).status_code == 204
    assert (await sender.post(f"{INVITATIONS}/{three['id']}/withdraw")).status_code == 204
    assert code(await sender.post(f"{INVITATIONS}/{three['id']}/withdraw")) == (409, "already_decided")
    statuses = await owner_rows(
        teams, "SELECT id, status FROM team_invitations WHERE from_user_id = :u ORDER BY created_at", u=amina
    )
    assert [r.status for r in statuses] == ["accepted", "declined", "withdrawn"]
    assert (await recipient.get(INVITATIONS)).json() == {"received": [], "sent": []}

    [n29] = await notices(teams, amina, "team.n29")
    assert n29.title == f"{await handle_of(teams, brian)} accepted: team up on {await problem_title(teams, first)}"
    assert n29.link == f"/dev/teams/{thread}"
    threads = (await sender.get(TEAMS)).json()["threads"]
    assert [t["id"] for t in threads] == [thread]
    assert threads[0]["open"] is True
    assert threads[0]["counterpart"]["user_id"] == str(brian)
    decided = await audits(teams, "team.invitation_decided", brian)
    assert [e.payload["decision"] for e in decided] == ["accept", "decline"]
    assert decided[0].payload["thread_id"] == thread


async def test_c3_ten_invitations_a_day(teams: TeamsDb, as_user: Clients) -> None:
    shared, _ = await niche(teams, "daily")
    sender = await developer(teams, "busy", liked=(shared,))
    others = [await developer(teams, f"to{n}", liked=(shared,)) for n in range(11)]
    problem_id = await problem(teams)
    client = await as_user(sender)
    for n, other in enumerate(others[:10]):
        made = await invite(client, other, problem_id)
        if n == 0:
            assert (await client.post(f"{INVITATIONS}/{made['id']}/withdraw")).status_code == 204  # still counts
    refused = await client.post(INVITATIONS, json={"to_user_id": str(others[10]), "problem_id": str(problem_id)})
    assert code(refused) == (429, "too_many_invitations")
    assert 86000 < int(refused.headers["Retry-After"]) <= 86400
    # a day later (the ledger's attempts leave the 24-hour window), the sender may invite again
    await _age_attempts(teams, sender, timedelta(hours=25))
    await invite(client, others[10], problem_id)


async def _age_attempts(teams: TeamsDb, user: UUID, by: timedelta) -> None:
    """Move ``user``'s recorded invitation attempts ``by`` into the past (the ledger is on the wall clock)."""
    keys = limits.ledger_keys(get_settings().secret_key.get_secret_value(), limits.INVITATION, user)
    await owner_run(
        teams, "UPDATE login_attempts SET created_at = created_at - :by WHERE email_digest = :e", by=by, e=keys.email
    )


async def test_c3_refused_attempts_count_toward_the_daily_cap(teams: TeamsDb, as_user: Clients) -> None:
    """Every attempt counts, whatever the database answers: probing whom one may invite is not free."""
    amina, brian, _ = await pair(teams, "probe")
    closed = await problem(teams, status="archived")
    client = await as_user(amina)
    for nobody in [uuid7() for _ in range(5)]:
        refused = await client.post(INVITATIONS, json={"to_user_id": str(nobody), "problem_id": str(closed)})
        assert code(refused) == (404, "problem_unavailable")
    open_problem = await problem(teams)
    for nobody in [uuid7() for _ in range(5)]:
        refused = await client.post(INVITATIONS, json={"to_user_id": str(nobody), "problem_id": str(open_problem)})
        assert code(refused) == (404, "peer_unavailable")
    capped = await client.post(INVITATIONS, json={"to_user_id": str(brian), "problem_id": str(open_problem)})
    assert code(capped) == (429, "too_many_invitations")
    assert await owner_rows(teams, "SELECT 1 FROM team_invitations WHERE from_user_id = :u", u=amina) == []


async def test_c3_no_reinvite_within_thirty_days_of_a_decline_or_withdrawal(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, _ = await pair(teams, "again")
    a, b = await as_user(amina), await as_user(brian)
    declined_on, withdrawn_on, other = await problem(teams), await problem(teams), await problem(teams)
    first = await invite(a, brian, declined_on)
    assert (await b.post(f"{INVITATIONS}/{first['id']}/decline")).status_code == 204
    second = await invite(a, brian, withdrawn_on)
    assert (await a.post(f"{INVITATIONS}/{second['id']}/withdraw")).status_code == 204
    for client, to, problem_id in ((a, brian, declined_on), (b, amina, declined_on), (b, amina, withdrawn_on)):
        refused = await client.post(INVITATIONS, json={"to_user_id": str(to), "problem_id": str(problem_id)})
        assert code(refused) == (409, "already_invited")  # the same pair and problem, either way round
    await invite(a, brian, other)  # another problem is another invitation
    await forward(teams, timedelta(days=31))
    await invite(a, brian, declined_on)  # thirty days on, the pair may try again


async def test_c3_a_block_ends_everything_and_an_unblock_reopens_nothing(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, _ = await pair(teams, "block")
    first, second = await problem(teams), await problem(teams)
    a, b = await as_user(amina), await as_user(brian)
    thread = await team(a, b, first)
    pending = await invite(b, amina, second)
    assert brian in [UUID(p["user_id"]) for p in (await a.get(PEERS)).json()["peers"]]

    assert (await a.post(BLOCKS, json={"user_id": str(brian)})).status_code == 204
    [row] = await owner_rows(teams, "SELECT status FROM team_invitations WHERE id = :i", i=pending["id"])
    assert row.status == "ended"
    mine = (await a.get(f"{TEAMS}/{thread}")).json()
    theirs = (await b.get(f"{TEAMS}/{thread}")).json()
    assert (mine["thread"]["closed_reason"], mine["can_post"]) == ("blocked", False)
    assert (theirs["thread"]["closed_reason"], theirs["can_post"]) == ("ended", False)  # never told they were blocked
    assert mine["thread"]["counterpart"] is None
    assert theirs["thread"]["counterpart"] is None
    assert code(await post(b, thread)) == (409, "thread_closed")
    assert brian not in [UUID(p["user_id"]) for p in (await a.get(PEERS)).json()["peers"]]
    assert amina not in [UUID(p["user_id"]) for p in (await b.get(PEERS)).json()["peers"]]
    third = await problem(teams)
    stranger = await developer(teams, "unrelated")
    as_stranger = await b.post(INVITATIONS, json={"to_user_id": str(stranger), "problem_id": str(third)})
    blocked = await b.post(INVITATIONS, json={"to_user_id": str(amina), "problem_id": str(third)})
    assert code(blocked) == (404, "peer_unavailable")
    # the same answer as for a stranger: the status, the whole body and no Retry-After
    assert (blocked.status_code, blocked.json()) == (as_stranger.status_code, as_stranger.json())
    assert blocked.headers.get("retry-after") == as_stranger.headers.get("retry-after") is None
    assert code(await a.post(INVITATIONS, json={"to_user_id": str(brian), "problem_id": str(third)})) == (
        404,
        "peer_unavailable",
    )
    listed = (await a.get(BLOCKS)).json()["blocked"]
    assert [(x["user_id"], x["handle"]) for x in listed] == [(str(brian), await handle_of(teams, brian))]
    assert (await b.get(BLOCKS)).json() == {"blocked": []}
    [event] = await audits(teams, "team.blocked", amina)
    assert event.payload == {"changed": 3}  # the block, the invitation ended, the thread closed

    assert (await a.delete(f"{BLOCKS}/{brian}")).status_code == 204
    assert (await a.delete(f"{BLOCKS}/{brian}")).status_code == 204  # idempotent
    after = (await a.get(f"{TEAMS}/{thread}")).json()
    assert (after["thread"]["open"], after["thread"]["closed_reason"]) == (False, "ended")
    assert code(await post(a, thread)) == (409, "thread_closed")  # threads stay closed
    assert brian in [UUID(p["user_id"]) for p in (await a.get(PEERS)).json()["peers"]]


async def test_blocking_nobody_answers_like_a_block(teams: TeamsDb, as_user: Clients) -> None:
    """Only a developer the caller can see (a peer or a counterpart) is blocked; any other id answers the same 204 and
    leaves no row, so the list never confirms that an arbitrary id is a developer."""
    amina = await developer(teams, "blocker")
    stranger = await developer(teams, "optedout", peers=False)  # a developer, but not one Amina can see
    org = await org_only(teams)
    client = await as_user(amina)
    for target in (uuid7(), org.owner, stranger):
        assert (await client.post(BLOCKS, json={"user_id": str(target)})).status_code == 204
    assert (await client.get(BLOCKS)).json() == {"blocked": []}
    rows = await owner_rows(teams, "SELECT 1 FROM developer_blocks WHERE blocker_user_id = :u", u=amina)
    assert rows == []
    assert code(await client.post(BLOCKS, json={"user_id": str(amina)})) == (422, "cannot_block_yourself")
    assert await audits(teams, "team.blocked", amina) == []


async def test_c3_an_invitation_on_a_problem_that_closed_cannot_be_accepted(teams: TeamsDb, as_user: Clients) -> None:
    amina, brian, _ = await pair(teams, "late")
    problem_id = await problem(teams)
    made = await invite(await as_user(amina), brian, problem_id)
    await owner_run(teams, "UPDATE problems SET status = 'archived' WHERE id = :p", p=problem_id)
    recipient = await as_user(brian)
    assert code(await recipient.post(f"{INVITATIONS}/{made['id']}/accept")) == (409, "invitation_unavailable")
    assert (await recipient.post(f"{INVITATIONS}/{made['id']}/decline")).status_code == 204
    assert (await recipient.get(TEAMS)).json() == {"threads": []}
