"""REQ-DEV-03 (D-58; P22 card C, C4): a team thread on the P21 message rules between two developers: append-only,
60 messages an hour per sender (429 with Retry-After), a closed thread is read-only (409), the contact-details rule does
NOT apply (a phone number posts), a message is reported once (409 after) and 10 a day (429), staff read a reported one
through the moderation queue only, and N29 reaches the other party at most once per 30 minutes. The read marker, the
unread count and leaving."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import httpx

from bridge.ids import uuid7
from bridge.teams.notices import BUCKET_SECONDS
from tests.integration.teams.api_world import (
    TEAMS,
    Clients,
    TeamsDb,
    audits,
    code,
    developer,
    forward,
    handle_of,
    niche,
    notices,
    owner_rows,
    owner_run,
    post,
    problem,
    problem_title,
    staff,
    team,
)


async def thread_of(teams: TeamsDb, as_user: Clients, label: str) -> tuple[httpx.AsyncClient, httpx.AsyncClient, str]:
    """Two developers who team up on a problem: (the sender's client, the recipient's client, the thread)."""
    shared, _ = await niche(teams, label)
    a = await as_user(await developer(teams, f"{label}a", liked=(shared,)))
    b = await as_user(await developer(teams, f"{label}b", liked=(shared,)))
    return a, b, await team(a, b, await problem(teams))


def uid(client: httpx.AsyncClient) -> UUID:
    found: UUID = client.user_id  # type: ignore[attr-defined]
    return found


async def test_c4_post_read_and_page_a_thread(teams: TeamsDb, as_user: Clients) -> None:
    a, b, thread = await thread_of(teams, as_user, "post")
    phone = "Call me on +254 712 345 678 or see https://example.com/plan"
    sent = await post(a, thread, phone)
    assert sent.status_code == 201, sent.text  # no contact-details rule between developers
    message = sent.json()
    assert (message["body"], message["mine"], message["redacted"]) == (phone, True, False)
    assert (await post(b, thread, "\uff26ull width\r\nsecond line")).json()["body"] == "Full width\nsecond line"
    for bad in ("", "   ", "bell\x07", "x" * 4001):
        assert (await post(a, thread, bad)).status_code == 422
    seen = (await b.get(f"{TEAMS}/{thread}")).json()
    assert [(m["body"], m["mine"]) for m in seen["items"]] == [(phone, False), ("Full width\nsecond line", True)]
    assert (seen["can_post"], seen["next_cursor"], seen["last_read_at"]) == (True, None, None)
    assert seen["thread"]["unread"] == 1
    assert seen["thread"]["counterpart"]["handle"] == await handle_of(teams, uid(a))
    assert (await b.get(f"{TEAMS}/unread-count")).json() == {"unread": 1}
    marked = (await b.post(f"{TEAMS}/{thread}/read", json={})).json()
    assert marked["unread"] == 0
    assert marked["last_read_at"] is not None
    assert (await b.get(f"{TEAMS}/unread-count")).json() == {"unread": 0}
    assert code(await b.post(f"{TEAMS}/{thread}/read", json={"up_to": str(uuid7())})) == (404, "not_found")
    # append-only: no route edits or deletes a message
    assert (await a.delete(f"{TEAMS}/{thread}/messages/{message['id']}")).status_code == 404
    assert (await a.patch(f"{TEAMS}/{thread}/messages/{message['id']}", json={"body": "x"})).status_code == 404
    # pages: the newest first page, a cursor for the older ones
    for n in range(3):
        assert (await post(a, thread, f"Message {n}")).status_code == 201
    first = (await a.get(f"{TEAMS}/{thread}", params={"limit": 2})).json()
    assert [m["body"] for m in first["items"]] == ["Message 1", "Message 2"]
    older = (await a.get(f"{TEAMS}/{thread}", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert [m["body"] for m in older["items"]] == ["Full width\nsecond line", "Message 0"]
    assert await audits(teams, "team.message_posted", uid(a)) == []  # no audit event for a message


async def test_c4_sixty_messages_an_hour_per_sender(teams: TeamsDb, as_user: Clients) -> None:
    a, b, thread = await thread_of(teams, as_user, "rate")
    for n in range(60):  # as the owner, as the app writes them (the database's clock, its triggers)
        await owner_run(
            teams,
            "INSERT INTO team_messages (id, thread_id, sender_user_id, body) VALUES (:id, :t, :s, :b)",
            id=uuid7(),
            t=thread,
            s=uid(a),
            b=f"Earlier {n}",
        )
    refused = await post(a, thread)
    assert code(refused) == (429, "too_many_messages")
    assert 3500 <= int(refused.headers["Retry-After"]) <= 3600
    [count] = await owner_rows(teams, "SELECT count(*) FROM team_messages WHERE thread_id = :t", t=thread)
    assert count[0] == 60  # the refused post was not kept
    assert (await post(b, thread)).status_code == 201  # the limit is the sender's
    await forward(teams, timedelta(minutes=61))
    assert (await post(a, thread)).status_code == 201


async def test_c4_leaving_closes_the_thread_for_both(teams: TeamsDb, as_user: Clients) -> None:
    a, b, thread = await thread_of(teams, as_user, "leave")
    assert (await post(a, thread)).status_code == 201
    assert (await b.post(f"{TEAMS}/{thread}/leave")).status_code == 204
    assert code(await b.post(f"{TEAMS}/{thread}/leave")) == (409, "thread_closed")
    for client in (a, b):
        page = (await client.get(f"{TEAMS}/{thread}")).json()
        assert (page["can_post"], page["thread"]["open"], page["thread"]["closed_reason"]) == (False, False, "left")
        assert len(page["items"]) == 1  # still readable
        assert code(await post(client, thread)) == (409, "thread_closed")
    [event] = await audits(teams, "team.left", uid(b))
    assert event.subject_id == UUID(thread)


async def test_the_thread_list_puts_open_threads_first(teams: TeamsDb, as_user: Clients) -> None:
    shared, _ = await niche(teams, "list")
    a = await as_user(await developer(teams, "lista", liked=(shared,)))
    b = await as_user(await developer(teams, "listb", liked=(shared,)))
    c = await as_user(await developer(teams, "listc", liked=(shared,)))
    first, second, third = await problem(teams), await problem(teams), await problem(teams)
    closed = await team(a, b, first)
    quiet = await team(a, c, second)
    busy = await team(c, a, third)
    assert (await a.post(f"{TEAMS}/{closed}/leave")).status_code == 204
    assert (await post(c, busy, "Newest activity")).status_code == 201
    listed = (await a.get(TEAMS)).json()["threads"]
    assert [t["id"] for t in listed] == [busy, quiet, closed]
    assert [t["unread"] for t in listed] == [1, 0, 0]
    assert listed[0]["problem"] == {"id": str(third), "title": await problem_title(teams, third)}
    assert listed[0]["last_message_at"] is not None
    assert listed[1]["last_message_at"] is None
    assert (listed[2]["open"], listed[2]["closed_reason"]) == (False, "left")


async def _start_of_a_window(teams: TeamsDb) -> None:
    """Move the shared clock to a minute into the next 30-minute window, so two posts a moment apart share one."""
    [now] = await owner_rows(teams, "SELECT extract(epoch FROM app_clock_now())")
    into = float(now[0]) % BUCKET_SECONDS
    await forward(teams, timedelta(seconds=BUCKET_SECONDS - into + 60))


async def test_c4_n29_once_per_thirty_minutes(teams: TeamsDb, as_user: Clients) -> None:
    a, b, thread = await thread_of(teams, as_user, "notice")
    await _start_of_a_window(teams)
    assert (await post(a, thread, "First, with a secret plan")).status_code == 201
    assert (await post(a, thread, "Second")).status_code == 201
    [first] = await notices(teams, uid(b), "team.n29")
    assert first.title == f"New team message from {await handle_of(teams, uid(a))}"
    assert first.link == f"/dev/teams/{thread}"
    assert "secret plan" not in f"{first.title} {first.body}"  # never the text
    assert await notices(teams, uid(a), "team.n29") != []  # the accept notice is a's own; b wrote nothing yet
    await forward(teams, timedelta(minutes=30))
    assert (await post(a, thread, "Third")).status_code == 201
    assert len(await notices(teams, uid(b), "team.n29")) == 2


async def test_c4_report_once_ten_a_day_and_staff_read_it_in_the_queue(teams: TeamsDb, as_user: Clients) -> None:
    a, b, thread = await thread_of(teams, as_user, "report")
    ids = [(await post(a, thread, f"Spam number {n}")).json()["id"] for n in range(11)]
    own = (await post(b, thread, "My own")).json()["id"]
    path = f"{TEAMS}/{thread}/messages"
    reported = await b.post(f"{path}/{ids[0]}/report", json={"reasons": ["spam", "abuse", "spam"]})
    assert reported.status_code == 201, reported.text
    case_id = reported.json()["case_id"]
    assert code(await b.post(f"{path}/{ids[0]}/report", json={"reasons": ["spam"]})) == (409, "already_reported")
    assert code(await b.post(f"{path}/{own}/report", json={"reasons": ["spam"]})) == (409, "own_message")
    assert code(await b.post(f"{path}/{uuid7()}/report", json={"reasons": ["spam"]})) == (404, "not_found")
    assert (await b.post(f"{path}/{ids[1]}/report", json={"reasons": ["gossip"]})).status_code == 422
    for message in ids[1:10]:
        assert (await b.post(f"{path}/{message}/report", json={"reasons": ["other"]})).status_code == 201
    assert code(await b.post(f"{path}/{ids[10]}/report", json={"reasons": ["spam"]})) == (429, "too_many_reports")
    [event, *_] = await audits(teams, "team.message_reported", uid(b))
    assert event.payload == {"message_id": ids[0], "case_id": case_id, "reasons": ["abuse", "spam"]}
    assert "Spam number" not in str(event.payload)

    moderator = await as_user(await staff(teams, "moderator"), fresh=True)
    queue = (await moderator.get("/api/admin/moderation/cases")).json()["items"]
    [listed] = [c for c in queue if c["id"] == case_id]
    assert (listed["subject_type"], listed["reasons"]) == ("team_message", ["spam", "abuse"])
    assert listed["preview"] == {"title": "Reported team message", "text": None}
    assert listed["team_message"] is None
    assert listed["actions"] == ["dismiss", "uphold"]
    assert "Spam number" not in str(queue)
    case = (await moderator.get(f"/api/admin/moderation/cases/{case_id}")).json()
    assert case["team_message"]["body"] == "Spam number 0"
    assert case["team_message"]["sender_handle"] == await handle_of(teams, uid(a))
    assert (case["team_message"]["thread_id"], case["team_message"]["message_id"]) == (thread, ids[0])
    reads = await audits(teams, "moderation.reported_team_message_read", uid(moderator))
    assert reads[0].payload == {"message_id": ids[0], "thread_id": thread}
    decided = await moderator.post(
        f"/api/admin/moderation/cases/{case_id}/decision", json={"decision": "uphold", "subject_version_id": None}
    )
    assert decided.status_code == 200, decided.text
    assert decided.json() == {"id": case_id, "status": "rejected", "subject_state": None}
    [kept] = await owner_rows(teams, "SELECT body, redacted_at FROM team_messages WHERE id = :m", m=ids[0])
    assert (kept.body, kept.redacted_at) == ("Spam number 0", None)  # no redaction function: the outcome only
    # staff read no thread otherwise
    assert (await moderator.get(f"{TEAMS}/{thread}")).status_code == 404
