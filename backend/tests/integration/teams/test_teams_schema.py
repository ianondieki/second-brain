"""Revision 0011 (REQ-DEV-03; P22 track C, D-58, D-62): team-up invitations, threads, messages, blocks, reports and
contributors at the database, each test in one rolled-back transaction.

- C3 at the database: an invitation names a problem open to teams (published, clear, readable by every signed-in
  user) and a visible peer, with no block either way; one pending per pair and problem in either direction; accept
  (creating the thread), decline and withdraw by the right party, once; a block ends pending invitations and closes
  threads, unblocking reopens nothing.
- C4 at the database: only the two parties read a thread and its messages (a third developer, an organisation-only
  account and staff read nothing); a party posts while the thread is open; append-only (the owner's one redaction
  only); a closed thread refuses a message; reports once per reporter and message, 10 a day, staff read the reported
  message through the function only.
- C5/D-62 at the database: the owner credits a thread counterpart (never a stranger or themselves); the owner or the
  contributor removes the credit once; anyone who reads the proposal reads the handles of those not removed through
  ``app_contributor_handles``, organisations and staff included, and nobody but developers reads the rows.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import (
    BLOCK,
    CLOSE,
    CONTRIBUTE,
    DECIDE,
    DENIED,
    HANDLES,
    INVITE,
    POST,
    REPORT,
    REPORTED,
    RLS,
    UNBLOCK,
    brief,
    count,
    county,
    decide,
    developer,
    handle,
    invitation_params,
    invite,
    niche,
    org_only,
    organisation,
    peer,
    post,
    problem,
    refused,
    team,
)

NO_INVITATION = "no invitation of the caller's with that id"
NOT_REACHABLE = "the recipient is neither a peer nor a counterpart of the sender"
NO_THREAD = "team_messages: no thread of the caller's with that id"
STATUS = "SELECT status, decided_at IS NOT NULL FROM team_invitations WHERE id = :id"
THREAD = "SELECT closed_reason, closed_at IS NOT NULL FROM team_threads WHERE id = :id"


async def _status(conn: AsyncConnection, invitation: UUID) -> tuple[str, bool]:
    await t.as_owner(conn)
    row = (await conn.execute(sa.text(STATUS), {"id": invitation})).one()
    return row[0], row[1]


async def _thread(conn: AsyncConnection, thread: UUID) -> tuple[str | None, bool]:
    await t.as_owner(conn)
    row = (await conn.execute(sa.text(THREAD), {"id": thread})).one()
    return row[0], row[1]


async def test_an_invitation_names_an_open_problem_and_a_visible_peer(owner_engine: AsyncEngine) -> None:
    """Given two developers who opted in, When one invites the other, Then the invitation is pending with the
    database's times, for a published, clear problem that every signed-in user reads (a developer's, or a public
    published Brief); the sender hears why otherwise: a held, unpublished or archived problem, an invited or closed
    Brief (no_data_found), a recipient who is no peer: did not opt in, is staff or has no developer profile
    (no_data_found); a
    sender who did not opt in, who is no developer, or who names another sender is refused by the policy; the note is
    1 to 300 characters (line breaks allowed) or none; nobody names the status or its time."""
    async with t.as_app(owner_engine) as conn:
        sender, to = await peer(conn, "sender"), await peer(conn, "to")
        hidden, staff = await peer(conn, "hidden", peers=False), await peer(conn, "staff", staff="admin")
        member = await org_only(conn)
        org = await organisation(conn, "briefs")
        open_problem = await problem(conn, sender)
        public = await brief(conn, org, member, visibility="public")
        invitation = await invite(conn, sender, to, open_problem, "Two\nlines are fine")
        assert await _status(conn, invitation) == ("pending", False)
        assert (await invite(conn, sender, to, public)) is not None
        closed_problems = [
            await problem(conn, sender, moderation_state="held"),
            await problem(conn, sender, status="pending_review"),
            await problem(conn, sender, status="archived"),
            await brief(conn, org, member, visibility="invited"),
            await brief(conn, org, member, visibility="public", status="closed"),
            uuid7(),
        ]
        await t.act(conn, sender)
        for closed in closed_problems:
            params = invitation_params(sender, to, closed)
            await refused(conn, INVITE, "team_invitations: no published problem with that id", "P0002", **params)
        for recipient in (hidden, staff, member, uuid7()):
            params = invitation_params(sender, recipient, open_problem)
            await refused(conn, INVITE, NOT_REACHABLE, "P0002", **params)
        for caller in (hidden, member, staff):  # the policy refuses, and nothing is said about the recipient
            await t.act(conn, caller)
            for recipient in (to, hidden):
                await refused(conn, INVITE, RLS, "42501", **invitation_params(caller, recipient, open_problem))
        await t.act(conn, sender)
        await refused(conn, INVITE, RLS, "42501", **invitation_params(to, sender, open_problem))  # another's name
        for note in ("x" * 301, "   ", "A bell\x07"):
            await refused(conn, INVITE, "note_valid", "23514", **invitation_params(sender, to, open_problem, note))
        await refused(conn, INVITE, "not_self", "23514", **invitation_params(sender, sender, open_problem))
        await refused(
            conn,
            "INSERT INTO team_invitations (id, from_user_id, to_user_id, problem_id, status) VALUES (:id, :sender,"
            " :to, :problem, 'accepted')",
            DENIED,
            **invitation_params(sender, to, open_problem),
        )


async def test_an_invitation_reaches_a_peer_or_a_counterpart_only(owner_engine: AsyncEngine) -> None:
    """Given developers who opted in, When one invites another, Then a peer (the sender's county, or a shared liked
    niche) is reached, and an opted-in developer in another county with no shared niche and no history is refused
    (P0002 from the trigger; the policy alone refuses it too); an existing counterpart is reached even once no peer
    (their niche dropped, then their switch off), but not once suspended or across a block; ``app_is_visible_peer``
    answers the same to the sender."""
    async with t.as_app(owner_engine) as conn:
        kisumu, nakuru = await county(conn, "Kisumu"), await county(conn, "Nakuru")
        agri, health = await niche(conn, "agri"), await niche(conn, "health")
        sender = await developer(conn, "sender", county_code=kisumu, liked=(agri,))
        neighbour = await developer(conn, "neighbour", county_code=kisumu)
        colleague = await developer(conn, "colleague", county_code=nakuru, liked=(agri,))
        outsider = await developer(conn, "outsider", county_code=nakuru, liked=(health,))
        issues = [await problem(conn, sender) for _ in range(6)]
        visible = "SELECT app_is_visible_peer(:u)"
        await t.act(conn, sender)
        assert [await t.run(conn, visible, u=u) for u in (sender, neighbour, colleague, outsider)] == [
            True,
            True,
            True,
            False,
        ]
        await refused(conn, INVITE, NOT_REACHABLE, "P0002", **invitation_params(sender, outsider, issues[0]))
        await invite(conn, sender, neighbour, issues[0])  # the same county
        await invite(conn, sender, colleague, issues[0])  # a shared liked niche
        await t.as_owner(conn)  # the policy alone, without the trigger's precise refusal
        await t.run(conn, "ALTER TABLE team_invitations DISABLE TRIGGER team_invitations_open")
        await t.act(conn, sender)
        await refused(conn, INVITE, RLS, "42501", **invitation_params(sender, outsider, issues[0]))
        await t.as_owner(conn)
        await t.run(conn, "ALTER TABLE team_invitations ENABLE TRIGGER team_invitations_open")
        await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=colleague)  # no peer any more
        await t.act(conn, sender)
        assert await t.run(conn, visible, u=colleague) is True  # a counterpart
        await invite(conn, sender, colleague, issues[1])
        await invite(conn, colleague, sender, issues[2])
        await t.as_owner(conn)
        await t.run(conn, "UPDATE developer_profiles SET peers_visible = false WHERE user_id = :u", u=colleague)
        await invite(conn, sender, colleague, issues[3])  # a counterpart who turned the switch off
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=colleague)
        await t.act(conn, sender)
        assert await t.run(conn, visible, u=colleague) is False
        await refused(conn, INVITE, NOT_REACHABLE, "P0002", **invitation_params(sender, colleague, issues[4]))
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'active' WHERE id = :u", u=colleague)
        await t.act(conn, neighbour)
        assert await t.run(conn, BLOCK, blocked=sender) == 2  # the block and the pending invitation it ended
        await t.act(conn, sender)
        assert await t.run(conn, visible, u=neighbour) is False
        await refused(
            conn, INVITE, "a block stands between", "42501", **invitation_params(sender, neighbour, issues[5])
        )
        await t.as_owner(conn)
        await t.run(
            conn,
            "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:a, :b)",
            a=colleague,
            b=sender,
        )
        await t.act(conn, sender)
        assert await t.run(conn, visible, u=colleague) is False  # a counterpart across a block
        assert await t.run(conn, visible, u=outsider) is False
        await t.as_owner(conn)  # the other way round: the sender's own block
        await t.run(conn, "DELETE FROM developer_blocks WHERE blocker_user_id = :a", a=colleague)
        await t.act(conn, sender)
        assert await t.run(conn, visible, u=colleague) is True
        await t.run(
            conn,
            "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:a, :b)",
            a=sender,
            b=colleague,
        )
        assert await t.run(conn, visible, u=colleague) is False


async def test_one_pending_invitation_per_pair_and_problem_either_way(owner_engine: AsyncEngine) -> None:
    """Given a pending invitation, When either party invites the other on the same problem, Then the partial unique
    index refuses it; another problem is fine, and once the first is decided the pair may invite again."""
    async with t.as_app(owner_engine) as conn:
        amina, brian = await peer(conn, "amina"), await peer(conn, "brian")
        first, second = await problem(conn, amina), await problem(conn, amina)
        invitation = await invite(conn, amina, brian, first)
        await t.act(conn, amina)
        await refused(
            conn, INVITE, "uq_team_invitations_pending_pair", "23505", **invitation_params(amina, brian, first)
        )
        await t.act(conn, brian)
        await refused(
            conn, INVITE, "uq_team_invitations_pending_pair", "23505", **invitation_params(brian, amina, first)
        )
        await invite(conn, brian, amina, second)
        await decide(conn, brian, invitation, "decline")
        await invite(conn, brian, amina, first)


async def test_decisions_are_the_right_partys_and_once(owner_engine: AsyncEngine) -> None:
    """Given pending invitations, When a party decides, Then the recipient accepts (the thread is created on the
    invitation's problem between the canonical pair, and its id returned) or declines, the sender withdraws, each once,
    at the database's time; the wrong party is refused, a non-party, a caller who is no developer and an unknown id get
    one refusal, a decided invitation never changes (for every role), and bridge_app updates nothing directly."""
    async with t.as_app(owner_engine) as conn:
        sender, to, third = await peer(conn, "sender"), await peer(conn, "to"), await peer(conn, "third")
        member = await org_only(conn)
        issue = await problem(conn, sender)
        invitation = await invite(conn, sender, to, issue)
        await t.act(conn, sender)
        await refused(
            conn, DECIDE, "only the recipient accepts or declines", "42501", invitation=invitation, decision="accept"
        )
        await refused(
            conn, DECIDE, "only the recipient accepts or declines", "42501", invitation=invitation, decision="decline"
        )
        await refused(
            conn,
            DECIDE,
            "the decision is accept, decline or withdraw",
            "22023",
            invitation=invitation,
            decision="maybe",
        )
        await t.act(conn, to)
        await refused(conn, DECIDE, "only the sender withdraws", "42501", invitation=invitation, decision="withdraw")
        for caller, target in ((third, invitation), (member, invitation), (None, invitation), (to, uuid7())):
            await t.act(conn, caller)
            await refused(conn, DECIDE, NO_INVITATION, "42501", invitation=target, decision="accept")
        thread = await decide(conn, to, invitation, "accept")
        assert await _status(conn, invitation) == ("accepted", True)
        found = (await conn.execute(sa.text("SELECT * FROM team_threads WHERE id = :id"), {"id": thread})).one()
        assert (found.invitation_id, found.problem_id) == (invitation, issue)
        assert (found.a_user_id, found.b_user_id) == (min(sender, to), max(sender, to))
        assert (found.closed_at, found.closed_reason) == (None, None)
        for by, decision in ((to, "decline"), (sender, "withdraw"), (to, "accept")):
            await t.act(conn, by)
            await refused(
                conn, DECIDE, r"already decided \(accepted\)", "55000", invitation=invitation, decision=decision
            )
        declined, withdrawn = (
            await invite(conn, to, sender, issue),
            await invite(conn, sender, to, await problem(conn, to)),
        )
        assert await decide(conn, sender, declined, "decline") is None
        assert await decide(conn, sender, withdrawn, "withdraw") is None
        assert await _status(conn, declined) == ("declined", True)
        assert await _status(conn, withdrawn) == ("withdrawn", True)
        await t.act(conn, sender)
        await refused(conn, "UPDATE team_invitations SET status = 'pending' WHERE id = :id", DENIED, id=declined)
        await t.as_owner(conn)  # every role: the guard
        await refused(
            conn, "UPDATE team_invitations SET note = 'Edited' WHERE id = :id", "never change", "23514", id=declined
        )
        for status in ("pending", "accepted"):
            await refused(
                conn,
                "UPDATE team_invitations SET status = :s WHERE id = :id",
                "changes only by its one decision",
                "55000",
                s=status,
                id=declined,
            )
        pending = await invite(conn, sender, third, issue)
        await t.as_owner(conn)
        await refused(
            conn,
            "UPDATE team_invitations SET decided_at = now() WHERE id = :id",
            "changes only by its one decision",
            "55000",
            id=pending,
        )


async def test_accept_needs_an_active_sender_and_a_problem_still_open(owner_engine: AsyncEngine) -> None:
    """Given pending invitations, When the sender was suspended or the problem was held since, Then accepting is refused
    (object_not_in_prerequisite_state) and the invitation stays pending; declining is still possible."""
    async with t.as_app(owner_engine) as conn:
        sender, to = await peer(conn, "sender"), await peer(conn, "to")
        held, other = await problem(conn, sender), await problem(conn, sender)
        first, second = await invite(conn, sender, to, held), await invite(conn, sender, to, other)
        await t.as_owner(conn)
        await t.run(conn, "UPDATE problems SET moderation_state = 'held' WHERE id = :id", id=held)
        await t.act(conn, to)
        await refused(
            conn, DECIDE, "the problem is no longer open to teams", "55000", invitation=first, decision="accept"
        )
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=sender)
        await t.act(conn, to)
        await refused(
            conn, DECIDE, "the sender is no longer an active developer", "55000", invitation=second, decision="accept"
        )
        assert await _status(conn, second) == ("pending", False)
        assert await decide(conn, to, second, "decline") is None


async def test_only_the_parties_read_a_thread_and_post_while_it_is_open(owner_engine: AsyncEngine) -> None:
    """Given a team's thread with a message from each party, When others look, Then a third developer, an
    organisation-only account, staff (even a party who became staff) and an unbound session read none of the
    invitation, thread, messages or read markers, and cannot post (one refusal, the same as for an unknown thread);
    a party never posts as the other; the owner never writes a message from a non-party."""
    async with t.as_app(owner_engine) as conn:
        amina, brian, third = (
            await peer(conn, "amina"),
            await peer(conn, "brian"),
            await peer(conn, "third"),
        )
        member, admin = await org_only(conn), await peer(conn, "admin", staff="admin")
        invitation, thread = await team(conn, amina, brian, await problem(conn, amina))
        await post(conn, amina, thread)
        await post(conn, brian, thread, "Yes")
        await t.act(conn, amina)
        await t.run(conn, "INSERT INTO team_thread_reads (thread_id, user_id) VALUES (:t, :u)", t=thread, u=amina)
        reads = {
            "team_invitations": "SELECT count(*) FROM team_invitations",
            "team_threads": "SELECT count(*) FROM team_threads",
            "team_messages": "SELECT count(*) FROM team_messages",
            "team_thread_reads": "SELECT count(*) FROM team_thread_reads",
        }
        assert [await count(conn, amina, sql) for sql in reads.values()] == [1, 1, 2, 1]
        assert [await count(conn, brian, sql) for sql in reads.values()] == [1, 1, 2, 0]
        for caller in (third, member, admin, None):
            assert [await count(conn, caller, sql) for sql in reads.values()] == [0, 0, 0, 0], caller
        for caller in (third, member, admin):
            await t.act(conn, caller)
            for target in (thread, uuid7()):
                params = {"id": uuid7(), "thread": target, "sender": caller, "body": "Hi"}
                await refused(conn, POST, NO_THREAD, "42501", **params)
        await t.act(conn, amina)
        await refused(conn, POST, RLS, "42501", id=uuid7(), thread=thread, sender=brian, body="As Brian")
        await t.as_owner(conn)
        await refused(
            conn,
            POST,
            "the sender is a party of the thread",
            "23514",
            id=uuid7(),
            thread=thread,
            sender=third,
            body="x",
        )
        await t.run(conn, "UPDATE users SET staff_role = 'moderator', totp_enabled_at = now() WHERE id = :u", u=amina)
        assert [await count(conn, amina, sql) for sql in reads.values()] == [0, 0, 0, 0]  # staff now: nothing
        await t.act(conn, amina)
        await refused(conn, POST, NO_THREAD, "42501", id=uuid7(), thread=thread, sender=amina, body="Still here")
        await t.act(conn, brian)
        await refused(
            conn, "INSERT INTO team_thread_reads (thread_id, user_id) VALUES (:t, :u)", RLS, "42501", t=thread, u=amina
        )
        assert invitation is not None


async def test_messages_are_append_only_but_for_the_owners_one_redaction(owner_engine: AsyncEngine) -> None:
    """Given a message, When anyone changes it, Then bridge_app holds no UPDATE or DELETE and names neither its time nor
    its redaction; the owner deletes and truncates nothing and only redacts it once (the body to '[redacted]' with
    who and when, nothing else); a body is 1 to 4,000 characters and never looks redacted."""
    async with t.as_app(owner_engine) as conn:
        amina, brian = await peer(conn, "amina"), await peer(conn, "brian")
        _, thread = await team(conn, amina, brian, await problem(conn, amina))
        message = await post(conn, amina, thread)
        await t.act(conn, amina)
        await refused(conn, "UPDATE team_messages SET body = 'Edited' WHERE id = :id", DENIED, id=message)
        await refused(conn, "DELETE FROM team_messages WHERE id = :id", DENIED, id=message)
        await refused(
            conn,
            "INSERT INTO team_messages (id, thread_id, sender_user_id, body, created_at)"
            " VALUES (:id, :t, :s, 'x', now())",
            DENIED,
            id=uuid7(),
            t=thread,
            s=amina,
        )
        for body in ("", "   ", "x" * 4001):
            await refused(conn, POST, "body_length", "23514", id=uuid7(), thread=thread, sender=amina, body=body)
        await refused(
            conn, POST, "redaction_complete", "23514", id=uuid7(), thread=thread, sender=amina, body="[redacted]"
        )
        await post(conn, amina, thread, "x" * 4000)
        await t.as_owner(conn)
        await refused(conn, "DELETE FROM team_messages WHERE id = :id", "append-only", "42501", id=message)
        await refused(conn, "TRUNCATE team_messages", "append-only", "42501")
        await refused(
            conn,
            "UPDATE team_messages SET body = 'Edited' WHERE id = :id",
            "only by its redaction",
            "42501",
            id=message,
        )
        redact = (
            "UPDATE team_messages SET body = '[redacted]', redacted_at = now(), redacted_by = :by{extra} WHERE id = :id"
        )
        await refused(
            conn,
            redact.format(extra=", created_at = now() - interval '1 day'"),
            "only by its redaction",
            by=amina,
            id=message,
        )
        await t.run(conn, redact.format(extra=""), by=amina, id=message)
        await refused(conn, redact.format(extra=""), "only by its redaction", "42501", by=amina, id=message)


async def test_a_closed_thread_is_read_only_and_never_reopens(owner_engine: AsyncEngine) -> None:
    """Given an open thread, When a party leaves (the only reason a party gives), Then it is closed for both with the
    reason left and the database's time; a message is refused (55000), leaving again is refused, a non-party is refused
    as for an unknown thread; for every role the thread never reopens and its parties and problem never change."""
    async with t.as_app(owner_engine) as conn:
        amina, brian, third = (
            await peer(conn, "amina"),
            await peer(conn, "brian"),
            await peer(conn, "third"),
        )
        _, thread = await team(conn, amina, brian, await problem(conn, amina))
        await t.act(conn, brian)
        await refused(conn, CLOSE, "closes a thread with the reason left", "22023", thread=thread, reason="blocked")
        await refused(conn, CLOSE, "closes a thread with the reason left", "22023", thread=thread, reason=None)
        for caller, target in ((third, thread), (await org_only(conn), thread), (brian, uuid7())):
            await t.act(conn, caller)
            await refused(conn, CLOSE, "no thread of the caller's with that id", "42501", thread=target, reason="left")
        await t.act(conn, brian)
        await t.run(conn, CLOSE, thread=thread, reason="left")
        assert await _thread(conn, thread) == ("left", True)
        for sender in (amina, brian):
            await t.act(conn, sender)
            params = {"id": uuid7(), "thread": thread, "sender": sender, "body": "Hello?"}
            await refused(conn, POST, "the thread is closed; it is read-only", "55000", **params)
        await t.act(conn, amina)
        await refused(conn, CLOSE, "the thread is already closed", "55000", thread=thread, reason="left")
        await t.as_owner(conn)
        reopen = "UPDATE team_threads SET closed_at = NULL, closed_reason = NULL WHERE id = :id"
        await refused(conn, reopen, "never changes and never reopens", "55000", id=thread)
        open_one = (await team(conn, amina, third, await problem(conn, amina)))[1]
        await t.as_owner(conn)
        await refused(
            conn,
            "UPDATE team_threads SET problem_id = :p WHERE id = :id",
            "never change",
            "23514",
            p=await problem(conn, amina),
            id=open_one,
        )
        await t.act(conn, amina)
        await refused(
            conn,
            "UPDATE team_threads SET closed_at = now(), closed_reason = 'left' WHERE id = :id",
            DENIED,
            id=open_one,
        )


async def test_a_block_ends_pending_invitations_and_closes_threads(owner_engine: AsyncEngine) -> None:
    """Given a pair with an open thread and pending invitations both ways, and another pair, When one blocks the other,
    Then every pending invitation between the two is ended and their thread closed (blocked), and the count says so;
    the other pair is untouched; a repeat changes nothing; neither invites nor posts across it; the blocked side reads
    no block. When the blocker lifts it, Then nothing reopens. A direct INSERT of a block ends everything the same
    way. Blocking oneself, nobody, a user without a developer profile, or as a caller who is no developer is refused."""
    async with t.as_app(owner_engine) as conn:
        amina, brian, carol = (
            await peer(conn, "amina"),
            await peer(conn, "brian"),
            await peer(conn, "carol"),
        )
        first, second, third = [await problem(conn, amina) for _ in range(3)]
        _, thread = await team(conn, amina, brian, first)
        towards, away = await invite(conn, brian, amina, second), await invite(conn, amina, brian, third)
        untouched = await invite(conn, amina, carol, second)
        await t.act(conn, amina)
        assert await t.run(conn, BLOCK, blocked=brian) == 4  # the block, two invitations ended, one thread closed
        assert [await _status(conn, i) for i in (towards, away, untouched)] == [
            ("ended", True),
            ("ended", True),
            ("pending", False),
        ]
        assert await _thread(conn, thread) == ("blocked", True)
        await t.act(conn, amina)
        assert await t.run(conn, BLOCK, blocked=brian) == 0
        for sender, to in ((amina, brian), (brian, amina)):
            await t.act(conn, sender)
            params = invitation_params(sender, to, first)
            await refused(conn, INVITE, "a block stands between the two developers", "42501", **params)
        await t.act(conn, brian)
        await refused(conn, POST, "the thread is closed", "55000", id=uuid7(), thread=thread, sender=brian, body="Why?")
        assert await count(conn, brian, "SELECT count(*) FROM developer_blocks") == 0
        assert await count(conn, amina, "SELECT count(*) FROM developer_blocks") == 1
        await t.act(conn, brian)
        assert await t.run(conn, UNBLOCK, blocked=amina) == 0  # not brian's block to lift
        await t.act(conn, amina)
        assert await t.run(conn, UNBLOCK, blocked=brian) == 1
        assert await _thread(conn, thread) == ("blocked", True)
        assert await _status(conn, towards) == ("ended", True)
        await invite(conn, amina, brian, second)  # a new invitation is possible again
        # A direct INSERT by the blocker ends everything the same way.
        _, other_thread = await team(conn, amina, carol, first)
        await t.act(conn, carol)
        await t.run(
            conn, "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:c, :a)", c=carol, a=amina
        )
        assert await _thread(conn, other_thread) == ("blocked", True)
        assert await _status(conn, untouched) == ("ended", True)
        await t.act(conn, amina)
        await refused(conn, BLOCK, "name another developer", "22023", blocked=amina)
        await refused(conn, BLOCK, "name another developer", "22023", blocked=None)
        member = await org_only(conn)
        await t.act(conn, amina)
        await refused(conn, BLOCK, "no developer with that id", "P0002", blocked=member)
        await t.act(conn, member)
        await refused(conn, BLOCK, "developers only", "42501", blocked=amina)
        await refused(conn, UNBLOCK, "developers only", "42501", blocked=amina)
        await refused(
            conn,
            "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:m, :a)",
            RLS,
            m=member,
            a=amina,
        )
        await t.act(conn, amina)
        await refused(
            conn,
            "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:b, :c)",
            RLS,
            b=brian,
            c=carol,
        )
        await refused(
            conn,
            "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:a, :a)",
            "not_self",
            "23514",
            a=amina,
        )


async def test_a_team_message_is_reported_once_ten_a_day_and_read_by_staff_through_the_function(
    owner_engine: AsyncEngine,
) -> None:
    """Given a thread, When a party reports the other's messages, Then each report files one case (team_message,
    report, the reasons in code order), a repeat returns it (created false), the eleventh in a day is refused; a
    non-party and unknown reasons are refused; bridge_app never files one directly; staff admin and moderator read the
    one reported message (with its sender) through ``app_reported_team_message`` only, and nobody else does."""
    async with t.as_app(owner_engine) as conn:
        amina, brian, third = (
            await peer(conn, "amina"),
            await peer(conn, "brian"),
            await peer(conn, "third"),
        )
        moderator = await peer(conn, "moderator", staff="moderator")
        _, thread = await team(conn, amina, brian, await problem(conn, amina))
        messages = [await post(conn, brian, thread, f"Message {n}") for n in range(11)]
        await t.act(conn, amina)
        first = (
            await conn.execute(sa.text(REPORT), {"message": messages[0], "reasons": ["other", "spam", "spam"]})
        ).one()
        assert first.created is True
        again = (await conn.execute(sa.text(REPORT), {"message": messages[0], "reasons": ["abuse"]})).one()
        assert (again.case_id, again.created) == (first.case_id, False)
        for message in messages[1:10]:
            assert (await conn.execute(sa.text(REPORT), {"message": message, "reasons": ["abuse"]})).one().created
        await refused(
            conn, REPORT, "at most 10 team message reports a day", "54000", message=messages[10], reasons=["spam"]
        )
        for reasons in ([], ["rude"], [None], None):
            await refused(
                conn, REPORT, "the reasons are one or more of", "22023", message=messages[10], reasons=reasons
            )
        for caller in (third, moderator, await org_only(conn)):
            await t.act(conn, caller)
            await refused(
                conn, REPORT, "no team message of the caller's", "42501", message=messages[0], reasons=["spam"]
            )
        await t.act(conn, amina)
        await refused(
            conn,
            "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id) VALUES (:id,"
            " 'team_message', :m, '{spam}', 'report', :me)",
            RLS,
            "42501",
            id=uuid7(),
            m=messages[10],
            me=amina,
        )
        await t.as_owner(conn)
        case = (
            await conn.execute(sa.text("SELECT * FROM moderation_cases WHERE id = :id"), {"id": first.case_id})
        ).one()
        assert (case.subject_type, case.subject_id, case.reporter_id, case.reasons) == (
            "team_message",
            messages[0],
            amina,
            ["spam", "other"],
        )
        await t.act(conn, moderator)
        (shared,) = (await conn.execute(sa.text(REPORTED), {"case": first.case_id})).all()
        assert (shared.message_id, shared.thread_id, shared.sender_user_id, shared.body) == (
            messages[0],
            thread,
            brian,
            "Message 0",
        )
        assert shared.sender_handle == await handle(conn, brian)
        await t.act(conn, moderator)
        assert await t.run(conn, "SELECT count(*) FROM team_messages") == 0  # nothing else of the thread
        assert (await conn.execute(sa.text(REPORTED), {"case": uuid7()})).all() == []
        await t.as_owner(conn)  # a case of another kind about the same id shares nothing
        other_case = uuid7()
        await t.run(
            conn,
            "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id)"
            " VALUES (:id, 'message', :m, '{spam}', 'report', :r)",
            id=other_case,
            m=messages[0],
            r=amina,
        )
        await t.act(conn, moderator)
        assert (await conn.execute(sa.text(REPORTED), {"case": other_case})).all() == []
        for caller in (amina, brian):
            await t.act(conn, caller)
            await refused(conn, REPORTED, "staff admin or moderator only", "42501", case=first.case_id)


async def test_the_owner_credits_a_counterpart_and_anyone_who_reads_the_proposal_reads_the_handles(
    owner_engine: AsyncEngine,
) -> None:
    """D-62 (a). Given a developer's published and draft proposals and a team thread with a counterpart, When the owner
    credits, Then the counterpart is credited naming their thread (never a stranger, oneself, nor another pair's thread,
    and never by anyone but the owner); every reader of the proposal (another developer, an organisation's member,
    staff) reads the handles of those not removed, by the time added, through ``app_contributor_handles`` (NULL to
    anyone who cannot read it), while only developers read the rows. The contributor or the owner removes a credit
    once, at the database's time; it is never restored or added back; a block keeps the credit."""
    async with t.as_app(owner_engine) as conn:
        owner, counterpart, second = (
            await peer(conn, "owner"),
            await peer(conn, "counterpart"),
            await peer(conn, "second"),
        )
        stranger, reader = await peer(conn, "stranger"), await peer(conn, "reader")
        member, admin = await org_only(conn), await peer(conn, "admin", staff="admin")
        issue = await problem(conn, owner)
        _, thread = await team(conn, owner, counterpart, issue)
        _, second_thread = await team(conn, second, owner, issue)
        _, other_pair = await team(conn, counterpart, stranger, issue)
        await t.as_owner(conn)
        niche = await t.run(conn, "SELECT niche_id FROM problems WHERE id = :p", p=issue)
        published, _ = await w.add_proposal(conn, owner, niche, issue)
        draft, _ = await w.add_proposal(conn, owner, niche, issue, registered=False)
        await t.act(conn, owner)
        for user, named in (
            (stranger, thread),
            (stranger, None),
            (owner, thread),
            (counterpart, other_pair),
            (counterpart, None),
        ):
            await refused(conn, CONTRIBUTE, RLS, "42501", proposal=published, user=user, thread=named)
        await t.act(conn, counterpart)
        await refused(conn, CONTRIBUTE, RLS, "42501", proposal=published, user=owner, thread=thread)
        await t.act(conn, owner)
        await t.run(conn, CONTRIBUTE, proposal=published, user=counterpart, thread=thread)
        await t.run(conn, CONTRIBUTE, proposal=published, user=second, thread=second_thread)
        await t.run(conn, CONTRIBUTE, proposal=draft, user=counterpart, thread=thread)
        names = [await handle(conn, counterpart), await handle(conn, second)]
        for caller in (owner, reader, member, admin, counterpart):
            await t.act(conn, caller)
            assert await t.run(conn, HANDLES, proposal=published) == names, caller
        for caller in (reader, member, admin, None):
            await t.act(conn, caller)
            expected = names[:1] if caller == admin else None  # staff read every proposal
            assert await t.run(conn, HANDLES, proposal=draft) == expected, caller
        await t.act(conn, None)
        assert await t.run(conn, HANDLES, proposal=published) is None
        # The owner reads all three; the counterpart their own two and the published proposal's other; another
        # developer the published proposal's two; an organisation's member, staff and an unbound session none.
        rows = "SELECT count(*) FROM proposal_contributors"
        readers = (owner, counterpart, reader, member, admin, None)
        assert [await count(conn, caller, rows) for caller in readers] == [3, 3, 2, 0, 0, 0]
        await t.act(conn, counterpart)  # the contributor removes themselves; the database times it
        remove = "UPDATE proposal_contributors SET removed_at = '2001-01-01' WHERE proposal_id = :p AND user_id = :u"
        assert await t.rowcount(conn, remove, p=published, u=counterpart) == 1
        removed = "SELECT removed_at FROM proposal_contributors WHERE proposal_id = :p AND user_id = :u"
        assert (await t.run(conn, removed, p=published, u=counterpart)).year > 2001
        assert await t.run(conn, HANDLES, proposal=published) == names[1:]
        restore = "UPDATE proposal_contributors SET removed_at = NULL WHERE proposal_id = :p AND user_id = :u"
        await refused(conn, restore, "stays removed", "55000", p=published, u=counterpart)
        await t.act(conn, owner)
        await refused(conn, restore, "stays removed", "55000", p=published, u=counterpart)
        await refused(
            conn, CONTRIBUTE, "pk_proposal_contributors", "23505", proposal=published, user=counterpart, thread=thread
        )
        await t.act(conn, reader)
        assert await t.rowcount(conn, remove, p=published, u=second) == 0  # neither owner nor contributor
        await t.act(conn, owner)
        assert await t.rowcount(conn, remove, p=published, u=second) == 1
        assert await t.run(conn, HANDLES, proposal=published) == []
        await refused(conn, "UPDATE proposal_contributors SET thread_id = NULL WHERE proposal_id = :p", DENIED, p=draft)
        await refused(conn, "DELETE FROM proposal_contributors WHERE proposal_id = :p", DENIED, p=draft)
        await t.as_owner(conn)
        await refused(
            conn,
            "UPDATE proposal_contributors SET thread_id = NULL WHERE proposal_id = :p",
            "never change",
            "23514",
            p=draft,
        )
        await t.act(conn, owner)
        assert await t.run(conn, BLOCK, blocked=counterpart) == 2  # the block and the open thread; the credit stays
        assert await t.run(conn, HANDLES, proposal=draft) == names[:1]


async def test_a_read_marker_is_a_partys_own(owner_engine: AsyncEngine) -> None:
    """Given a thread, When its parties and others mark it read, Then a party inserts and moves their own marker only
    (never its thread or user), a third developer marks nothing, and nobody reads another's marker."""
    async with t.as_app(owner_engine) as conn:
        amina, brian, third = (
            await peer(conn, "amina"),
            await peer(conn, "brian"),
            await peer(conn, "third"),
        )
        _, thread = await team(conn, amina, brian, await problem(conn, amina))
        mark = "INSERT INTO team_thread_reads (thread_id, user_id, last_read_at) VALUES (:t, :u, now())"
        move = "UPDATE team_thread_reads SET last_read_at = now() + interval '1 minute' WHERE thread_id = :t"
        await t.act(conn, third)
        await refused(conn, mark, RLS, "42501", t=thread, u=third)
        await t.act(conn, amina)
        await t.run(conn, mark, t=thread, u=amina)
        assert await t.rowcount(conn, move, t=thread) == 1
        await refused(conn, "UPDATE team_thread_reads SET user_id = :u WHERE thread_id = :t", DENIED, u=brian, t=thread)
        await t.act(conn, brian)
        assert await t.rowcount(conn, move, t=thread) == 0  # amina's marker is not brian's
        await t.run(conn, mark, t=thread, u=brian)
        assert await t.run(conn, "SELECT count(*) FROM team_thread_reads") == 1
        await t.act(conn, third)
        assert await t.rowcount(conn, move, t=thread) == 0


async def test_a_party_who_becomes_staff_or_is_suspended_loses_every_power(owner_engine: AsyncEngine) -> None:
    """Given a developer with a team, a pending invitation and a credited proposal, When they become staff (or are
    suspended), Then they decide, close, post, mark, report, credit, remove a credit, block and read cards no more:
    every path needs a developer (staff decide and moderate, they never take part)."""
    async with t.as_app(owner_engine) as conn:
        amina, brian, carol = (
            await peer(conn, "amina"),
            await peer(conn, "brian"),
            await peer(conn, "carol"),
        )
        issue = await problem(conn, amina)
        _, thread = await team(conn, amina, brian, issue)
        message = await post(conn, brian, thread)
        pending = await invite(conn, amina, carol, issue)
        await t.as_owner(conn)
        niche = await t.run(conn, "SELECT niche_id FROM problems WHERE id = :p", p=issue)
        published, _ = await w.add_proposal(conn, amina, niche, issue)
        draft, _ = await w.add_proposal(conn, amina, niche, issue, registered=False)
        await t.act(conn, amina)
        await t.run(conn, CONTRIBUTE, proposal=published, user=brian, thread=thread)
        for change in (
            "UPDATE users SET staff_role = 'moderator', totp_enabled_at = now() WHERE id = :u",
            "UPDATE users SET staff_role = NULL, status = 'suspended' WHERE id = :u",
        ):
            await t.as_owner(conn)
            await t.run(conn, change, u=amina)
            await t.act(conn, amina)
            await refused(conn, DECIDE, NO_INVITATION, "42501", invitation=pending, decision="withdraw")
            await refused(conn, CLOSE, "no thread of the caller's", "42501", thread=thread, reason="left")
            await refused(conn, POST, NO_THREAD, "42501", id=uuid7(), thread=thread, sender=amina, body="Hi")
            await refused(
                conn, "INSERT INTO team_thread_reads (thread_id, user_id) VALUES (:t, :u)", RLS, t=thread, u=amina
            )
            await refused(conn, REPORT, "no team message of the caller's", "42501", message=message, reasons=["spam"])
            await refused(conn, CONTRIBUTE, RLS, "42501", proposal=draft, user=brian, thread=thread)
            remove = "UPDATE proposal_contributors SET removed_at = now() WHERE proposal_id = :p"
            assert await t.rowcount(conn, remove, p=published) == 0
            await refused(conn, BLOCK, "developers only", "42501", blocked=brian)
            assert (await conn.execute(sa.text("SELECT * FROM app_developer_card(:u)"), {"u": brian})).all() == []
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'active' WHERE id = :u", u=amina)
        await t.act(conn, amina)  # a developer again: the credit and the thread are still theirs
        assert (
            await t.rowcount(
                conn, "UPDATE proposal_contributors SET removed_at = now() WHERE proposal_id = :p", p=published
            )
            == 1
        )
