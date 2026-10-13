"""Revision 0015 (P28-M; REQ-ENG-06, AC-TRACK-5; REQ-NOT-05; REQ-TEN-02): the database half of the procurement route
(3b), the nudges ledger and the organisation's team.

- Where 3b sits: a public entity's engagement enters ``PROCUREMENT_ROUTE`` from ``UNDER_REVIEW`` only and leaves it for
  ``INTEREST_CONFIRMED`` (never for ``CONTACT_MADE``; ``INTEREST_CONFIRMED`` never returns to it), with the side
  branches ``INTEREST_CONFIRMED`` has (hold and request for information resuming to 3b, decline, withdrawal, the
  system's expiry); a private organisation's engagement never enters it, neither by an event nor by the owner's insert
  (AC-TRACK-5 at the database level, both ways).
- The decision: an engagement starts undecided; the route is decided in 3b only, by an owner or admin of the
  organisation (a signatory, a reviewer, the developer are refused; another organisation's member reaches no row), the
  time and decider the database's; the developer reads it; it never changes afterwards, for any role.
- Together with the move: 3b moves to ``INTEREST_CONFIRMED`` only once the route is decided and the contact named with
  its contact-by date; a decided route leaves 3b for ``INTEREST_CONFIRMED`` only; a decision left in 3b is refused at
  commit (the deferred constraint trigger, fired here with ``SET CONSTRAINTS ALL IMMEDIATE``).
- The CHECKs: ``direct`` needs a justification of at least 20 characters once trimmed; a justification is not blank,
  at most 1,000 characters (line breaks allowed) and only with a route; a named contact may lack its date only while
  the route is undecided.
- The nudges ledger: ``app_record_nudge`` records a nudge once per engagement, kind and key (true, then false), for a
  session with no user bound only, never after the engagement ended, with the engagement's organisation and the shared
  clock's time; the kind and key CHECKs keep free text out; the ledger is append-only for every role and read by the
  organisation's members only (never the developer, another organisation, a forged context or staff);
  ``app_nudge_candidates`` lists, to the job only, the engagements a nudge may be due for, each with a member to bind.
- The team: niche defaults set by an owner or admin for a triage member only, read by members, cleared when the member
  leaves or loses the roles; the escalation contact (a table of its own) an active member, read by the organisation's
  members only (never a developer of its engagement), cleared when they leave or their account goes; invitations
  listed, created (as the caller; an owner for a protected role), revoked and resent by the organisation's admins only,
  one open per address, at least one role, expiring within 30 days of their creation (the shared clock's), nothing else
  of them the app's, nothing of a closed one anybody's;
  ``app_accept_invitation`` (open, expired on the shared clock, revoked, accepted, unknown, another or unverified
  address, an active member, a removed one reactivated) and ``app_invitation_preview``; the last active owner is
  neither removed nor demoted by the organisation's writes, in one row, many, or two concurrent transactions (that test
  commits its own organisation and removes it), while staff's correction is not judged.

Every other test runs in one rolled-back transaction (``tracker.as_app``); the round trip, the grants and the policies
are in ``test_migrations.py``, the downgrade's refusals in ``test_migration_0015_downgrade.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements import tracker as t

DECIDE = (
    "UPDATE engagements SET procurement_route = CAST(:route AS procurement_route), procurement_justification = :why,"
    " contact_by = :by WHERE id = :e"
)
DECISION = (
    "SELECT procurement_route::text AS route, procurement_justification AS why, procurement_decided_at AS decided_at,"
    " procurement_decided_by AS decided_by FROM engagements WHERE id = :e"
)
PUBLIC_ONLY = "PROCUREMENT_ROUTE is for a public entity only"
THROUGH_3B = "a public entity's engagement enters INTEREST_CONFIRMED through PROCUREMENT_ROUTE"
DECIDED_IN_3B = "decided in PROCUREMENT_ROUTE only"
OWNER_OR_ADMIN = "an owner or admin of the organisation decides"
NEVER_CHANGES = "a procurement decision never changes"
NEEDS_DECISION = "moves to INTEREST_CONFIRMED once its route is decided"
NEEDS_CONTACT = "with the named contact and its contact-by date"
DECIDED_LEAVES = "leaves PROCUREMENT_ROUTE for INTEREST_CONFIRMED only"
AT_COMMIT = "decided in the transaction that moves the engagement"
DENIED = "permission denied"
CONTACT_BY = date(2026, 12, 1)
WHY = "Below the PPADA 2015 threshold for a pilot."  # more than 20 characters
MOVE = "procurement_route"  # the command code of the decision's move to INTEREST_CONFIRMED


async def public_scene(conn: AsyncConnection) -> tuple[t.Parties, UUID]:
    """As the owner: the tracker's parties with the organisation a public entity, and the developer's engagement with
    it walked to UNDER_REVIEW."""
    p = await t.parties(conn)
    await t.run(conn, "UPDATE organizations SET public_entity = true WHERE id = :org", org=p.org)
    await t.act(conn, p.developer)
    engagement = await t.engage(conn, p)
    await t.walk(conn, p, engagement, "UNDER_REVIEW")
    return p, engagement


async def enter_route(conn: AsyncConnection, p: t.Parties, engagement: UUID) -> None:
    """The signatory approves to proceed: names the contact person and channel (no date yet) and enters 3b."""
    await t.act(conn, p.signatory, p.org)
    await t.run(
        conn,
        "UPDATE engagements SET contact_user_id = :c, contact_channel = 'email' WHERE id = :e",
        c=p.owner,
        e=engagement,
    )
    await t.append(conn, engagement, p.signatory, "signatory", "approve", "UNDER_REVIEW", "PROCUREMENT_ROUTE")


async def route_scene(conn: AsyncConnection) -> tuple[t.Parties, UUID]:
    p, engagement = await public_scene(conn)
    await enter_route(conn, p, engagement)
    return p, engagement


def decision(engagement: UUID, route: str = "rfq_tender", why: str | None = WHY) -> dict[str, object]:
    return {"e": engagement, "route": route, "why": why, "by": CONTACT_BY}


async def decide_and_move(conn: AsyncConnection, p: t.Parties, engagement: UUID, route: str = "rfq_tender") -> None:
    """The owner (owner and admin) decides the route and moves the engagement to INTEREST_CONFIRMED."""
    await t.act(conn, p.owner, p.org)
    await t.run(conn, DECIDE, **decision(engagement, route))
    await t.append(conn, engagement, p.owner, "admin", MOVE, "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED")


async def add_member(conn: AsyncConnection, p: t.Parties, roles: str) -> UUID:
    """As the owner: a new member of the parties' organisation holding ``roles``."""
    await t.as_owner(conn)
    user = uuid7()
    await t.run(
        conn,
        "INSERT INTO users (id, email, display_name, email_verified_at) VALUES (:id, :email, 'Member', now())",
        id=user,
        email=f"member-{user.hex}@example.test",
    )
    await t.member(conn, p.org, user, roles)
    return user


async def immediately(conn: AsyncConnection) -> None:
    """Fire the deferred constraint triggers now (as at commit), then defer them again for the rest of the test."""
    await conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    await conn.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))


# --- where 3b sits (AC-TRACK-5) --------------------------------------------------------------------------------------


async def test_a_public_entity_enters_the_route_and_a_private_one_never_does(owner_engine: AsyncEngine) -> None:
    """Given an engagement under review, When the signatory approves to proceed into PROCUREMENT_ROUTE, Then a public
    entity's engagement enters it, and a private organisation's is refused (its approve goes to INTEREST_CONFIRMED as
    before); the owner cannot insert a private organisation's engagement in 3b either, a public entity's it can."""
    async with t.as_app(owner_engine) as conn:
        _, engagement = await route_scene(conn)
        assert await t.state_of(conn, engagement) == "PROCUREMENT_ROUTE"

        await t.as_owner(conn)
        q = await t.parties(conn)  # public_entity false: a private organisation
        await t.act(conn, q.developer)
        private = await t.engage(conn, q)
        await t.walk(conn, q, private, "UNDER_REVIEW")
        await t.act(conn, q.signatory, q.org)
        await t.expect(
            conn,
            t.APPEND,
            PUBLIC_ONLY,
            **t.event_params(private, q.signatory, "signatory", "approve", "UNDER_REVIEW", "PROCUREMENT_ROUTE"),
        )
        await t.walk(conn, q, private, "INTEREST_CONFIRMED")  # the private approve, unchanged

        await t.as_owner(conn)
        r = await t.parties(conn)
        await t.expect(conn, t.ENGAGE, PUBLIC_ONLY, **_engage_params(r, "PROCUREMENT_ROUTE"))
        await t.run(conn, "UPDATE organizations SET public_entity = true WHERE id = :org", org=r.org)
        inserted = await t.engage(conn, r, state="PROCUREMENT_ROUTE")
        assert await t.state_of(conn, inserted) == "PROCUREMENT_ROUTE"


def _engage_params(p: t.Parties, state: str) -> dict[str, object]:
    return {
        "id": uuid7(),
        "p": p.proposal,
        "org": p.org,
        "dev": p.developer,
        "v": p.version,
        "origin": "tagged",
        "state": state,
    }


async def test_3b_follows_review_and_leads_to_interest_confirmed(owner_engine: AsyncEngine) -> None:
    """Revision 0015's predecessors: PROCUREMENT_ROUTE is entered from UNDER_REVIEW (or ORG_INTEREST: the next test),
    never from SUBMITTED, never back from INTEREST_CONFIRMED, and left for INTEREST_CONFIRMED, never straight for
    CONTACT_MADE (revision 0003's "around stage 3" path); stage 3 then goes on to CONTACT_MADE as before."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.run(conn, "UPDATE organizations SET public_entity = true WHERE id = :org", org=p.org)
        await t.act(conn, p.developer)
        engagement = await t.engage(conn, p)
        await t.act(conn, p.signatory, p.org)
        await t.expect(
            conn,
            t.APPEND,
            "PROCUREMENT_ROUTE cannot follow SUBMITTED",
            **t.event_params(engagement, p.signatory, "signatory", "approve", "SUBMITTED", "PROCUREMENT_ROUTE"),
        )
        await t.walk(conn, p, engagement, "UNDER_REVIEW")
        await enter_route(conn, p, engagement)
        await t.act(conn, p.owner, p.org)
        await t.expect(
            conn,
            t.APPEND,
            "CONTACT_MADE cannot follow PROCUREMENT_ROUTE",
            **t.event_params(engagement, p.owner, "owner", "mark_contacted", "PROCUREMENT_ROUTE", "CONTACT_MADE"),
        )
        await decide_and_move(conn, p, engagement)
        assert await t.state_of(conn, engagement) == "INTEREST_CONFIRMED"
        await t.act(conn, p.signatory, p.org)
        await t.expect(
            conn,
            t.APPEND,
            "PROCUREMENT_ROUTE cannot follow INTEREST_CONFIRMED",
            **t.event_params(
                engagement, p.signatory, "signatory", "approve", "INTEREST_CONFIRMED", "PROCUREMENT_ROUTE"
            ),
        )
        await t.walk(conn, p, engagement, "CONTACT_MADE")
        await immediately(conn)  # the decision moved with the engagement: nothing is left for commit


async def test_a_public_entity_enters_stage_3_only_through_3b_and_a_private_one_as_before(
    owner_engine: AsyncEngine,
) -> None:
    """The orchestrator's ruling (P28-M): a public entity's engagement enters INTEREST_CONFIRMED only from
    PROCUREMENT_ROUTE. Its signatory's approve from UNDER_REVIEW and the developer's accept of its interest from
    ORG_INTEREST are refused, the accept into 3b admitted; a resume into stage 3 (a hold) and the return of a disputed
    first contact from CONTACT_MADE stay as they were. A private organisation keeps exactly today's paths: both moves
    into stage 3 are admitted and its interest never enters 3b."""
    async with t.as_app(owner_engine) as conn:
        p, reviewed = await public_scene(conn)
        await t.act(conn, p.signatory, p.org)
        await t.run(
            conn,
            "UPDATE engagements SET contact_user_id = :c, contact_channel = 'email', contact_by = :by WHERE id = :e",
            c=p.owner,
            by=CONTACT_BY,
            e=reviewed,
        )
        approve = t.event_params(reviewed, p.signatory, "signatory", "approve", "UNDER_REVIEW", "INTEREST_CONFIRMED")
        await t.expect(conn, t.APPEND, THROUGH_3B, **approve)

        await t.as_owner(conn)
        q = await t.parties(conn)
        await t.run(conn, "UPDATE organizations SET public_entity = true WHERE id = :org", org=q.org)
        await t.act(conn, q.signatory, q.org)
        interest = await t.engage(conn, q, origin="org_browse", state="ORG_INTEREST")
        await t.act(conn, q.developer)
        accept = t.event_params(
            interest, q.developer, "developer", "accept_interest", "ORG_INTEREST", "INTEREST_CONFIRMED"
        )
        await t.expect(conn, t.APPEND, THROUGH_3B, **accept)
        await t.append(conn, interest, q.developer, "developer", "accept_interest", "ORG_INTEREST", "PROCUREMENT_ROUTE")
        await t.act(conn, q.owner, q.org)
        await t.run(
            conn,
            "UPDATE engagements SET contact_user_id = :c, contact_channel = 'email' WHERE id = :e",
            c=q.owner,
            e=interest,
        )
        await decide_and_move(conn, q, interest)
        assert await t.state_of(conn, interest) == "INTEREST_CONFIRMED"
        await t.act(conn, q.developer)  # a hold in stage 3 resumes to it, a public entity's too
        await t.append(conn, interest, q.developer, "developer", "pause", "INTEREST_CONFIRMED", "ON_HOLD")
        await t.append(conn, interest, q.developer, "developer", "resume", "ON_HOLD", "INTEREST_CONFIRMED")
        await t.walk(conn, q, interest, "CONTACT_MADE")
        await t.act(conn, q.owner, q.org)  # revision 0003's return of a disputed first contact, after 3b
        await t.append(conn, interest, q.owner, "owner", "dispute_contact", "CONTACT_MADE", "INTEREST_CONFIRMED")
        await immediately(conn)

        await t.as_owner(conn)
        _, approved = await private_scene(conn, "INTEREST_CONFIRMED")  # UNDER_REVIEW -> INTEREST_CONFIRMED, as before
        assert await t.state_of(conn, approved) == "INTEREST_CONFIRMED"
        await t.as_owner(conn)
        s = await t.parties(conn)
        await t.act(conn, s.signatory, s.org)
        private_interest = await t.engage(conn, s, origin="org_browse", state="ORG_INTEREST")
        await t.act(conn, s.developer)
        to_3b = t.event_params(
            private_interest, s.developer, "developer", "accept_interest", "ORG_INTEREST", "PROCUREMENT_ROUTE"
        )
        await t.expect(conn, t.APPEND, PUBLIC_ONLY, **to_3b)
        await t.append(
            conn, private_interest, s.developer, "developer", "accept_interest", "ORG_INTEREST", "INTEREST_CONFIRMED"
        )
        assert await t.state_of(conn, private_interest) == "INTEREST_CONFIRMED"


async def test_3b_has_the_side_branches_of_stage_3(owner_engine: AsyncEngine) -> None:
    """From PROCUREMENT_ROUTE: a hold and a request for information resume to it; the organisation declines; the
    developer withdraws; the system expires it (each, undecided)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await route_scene(conn)
        await t.act(conn, p.developer)
        await t.append(conn, engagement, p.developer, "developer", "pause", "PROCUREMENT_ROUTE", "ON_HOLD")
        await t.expect(
            conn,
            t.APPEND,
            "ON_HOLD resumes to PROCUREMENT_ROUTE",
            **t.event_params(engagement, p.developer, "developer", "resume", "ON_HOLD", "INTEREST_CONFIRMED"),
        )
        await t.append(conn, engagement, p.developer, "developer", "resume", "ON_HOLD", "PROCUREMENT_ROUTE")
        await t.act(conn, p.reviewer, p.org)
        await t.append(conn, engagement, p.reviewer, "reviewer", "request_info", "PROCUREMENT_ROUTE", "INFO_REQUESTED")
        await t.act(conn, p.developer)
        await t.append(conn, engagement, p.developer, "developer", "answer_info", "INFO_REQUESTED", "PROCUREMENT_ROUTE")
        await t.act(conn, p.owner, p.org)
        await t.append(conn, engagement, p.owner, "owner", "decline", "PROCUREMENT_ROUTE", "DECLINED", reason="BUDGET")
        assert await t.state_of(conn, engagement) == "DECLINED"

        await t.as_owner(conn)
        q, withdrawn = await route_scene(conn)
        await t.act(conn, q.developer)
        await t.append(conn, withdrawn, q.developer, "developer", "withdraw", "PROCUREMENT_ROUTE", "WITHDRAWN")
        assert await t.state_of(conn, withdrawn) == "WITHDRAWN"

        await t.as_owner(conn)
        r, expired = await route_scene(conn)
        await t.act(conn, r.developer)  # the expiry job, bound to the developer, writes the system's event
        await t.append(conn, expired, None, "system", "expire", "PROCUREMENT_ROUTE", "EXPIRED", reason="NO_DECISION")
        assert await t.state_of(conn, expired) == "EXPIRED"


# --- the decision ----------------------------------------------------------------------------------------------------


async def test_only_an_owner_or_admin_decides_the_route_and_only_in_3b(owner_engine: AsyncEngine) -> None:
    """Given a public entity's engagement, Then the route cannot be decided under review; in 3b a signatory, a reviewer
    and the developer are refused and another organisation's member reaches no row; an admin decides it, the time
    (the shared clock) and the decider (the admin, whatever is sent) the database's and not the app's to write; the
    developer reads the decision."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await public_scene(conn)
        await t.act(conn, p.owner, p.org)
        await t.expect(conn, DECIDE, DECIDED_IN_3B, **decision(engagement))
        await enter_route(conn, p, engagement)
        for refused in (p.signatory, p.reviewer):
            await t.act(conn, refused, p.org)
            await t.expect(conn, DECIDE, OWNER_OR_ADMIN, **decision(engagement))
        await t.act(conn, p.developer)
        await t.expect(conn, DECIDE, OWNER_OR_ADMIN, **decision(engagement))
        await t.act(conn, p.other_member, p.other_org)
        assert await t.rowcount(conn, DECIDE, **decision(engagement)) == 0
        admin = await add_member(conn, p, "{admin}")
        await t.act(conn, admin, p.org)
        for column, value in (("procurement_decided_by", p.owner), ("procurement_decided_at", "2026-01-01")):
            await t.expect(conn, f"UPDATE engagements SET {column} = :v WHERE id = :e", DENIED, v=value, e=engagement)
        before = await t.run(conn, "SELECT app_clock_now()")
        await t.run(conn, DECIDE, **decision(engagement, "pilot_mou", None))
        after = await t.run(conn, "SELECT app_clock_now()")
        await t.append(conn, engagement, admin, "admin", MOVE, "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED")
        await t.act(conn, p.developer)
        row = (await conn.execute(sa.text(DECISION), {"e": engagement})).one()
        assert (row.route, row.why, row.decided_by) == ("pilot_mou", None, admin)
        assert before <= row.decided_at <= after
        await immediately(conn)


async def test_an_engagement_starts_undecided_and_a_decision_never_changes(owner_engine: AsyncEngine) -> None:
    """An engagement is inserted with no decision (the developer's insert and the owner's); once decided, the route,
    the justification and the decider never change, for the admin and for the owner role alike."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.run(conn, "UPDATE organizations SET public_entity = true WHERE id = :org", org=p.org)
        decided = (
            "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state,"
            " procurement_route) VALUES (:id, :p, :org, :dev, :v, CAST(:origin AS engagement_origin),"
            " CAST(:state AS engagement_state), 'rfq_tender')"
        )
        await t.expect(conn, decided, "starts with no procurement decision", **_engage_params(p, "PROCUREMENT_ROUTE"))
        await t.act(conn, p.developer)
        await t.expect(conn, decided, "starts with no procurement decision", **_engage_params(p, "SUBMITTED"))

        await t.as_owner(conn)
        q, engagement = await route_scene(conn)
        await decide_and_move(conn, q, engagement, "direct")
        for change in (
            "procurement_route = 'rfq_tender'",
            "procurement_justification = 'A different reason, long enough.'",
            "procurement_route = NULL, procurement_justification = NULL",
        ):
            await t.expect(conn, f"UPDATE engagements SET {change} WHERE id = :e", NEVER_CHANGES, e=engagement)
        await t.as_owner(conn)
        for change in (
            "procurement_justification = 'A different reason, long enough.'",
            "procurement_decided_by = NULL, procurement_decided_at = NULL, procurement_route = NULL,"
            " procurement_justification = NULL",
            "procurement_decided_at = now()",
        ):
            await t.expect(conn, f"UPDATE engagements SET {change} WHERE id = :e", NEVER_CHANGES, e=engagement)
        await t.act(conn, q.owner, q.org)  # other columns still change (the contact-by date, say)
        await t.run(conn, "UPDATE engagements SET contact_by = :by WHERE id = :e", by=date(2026, 12, 2), e=engagement)


# --- together with the move -------------------------------------------------------------------------------------------


async def test_the_decision_and_the_move_to_stage_3_are_one(owner_engine: AsyncEngine) -> None:
    """3b moves to INTEREST_CONFIRMED only once the route is decided and the contact named with its date; a decided
    route is not declined, held or withdrawn from 3b; and a decision still in 3b at commit is refused."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await route_scene(conn)
        await t.act(conn, p.owner, p.org)
        move = t.event_params(engagement, p.owner, "admin", MOVE, "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED")
        await t.expect(conn, t.APPEND, NEEDS_DECISION, **move)
        await t.run(conn, DECIDE, **decision(engagement))
        await t.expect(conn, "SET CONSTRAINTS ALL IMMEDIATE", AT_COMMIT)  # left in 3b: refused at commit
        await t.expect(
            conn,
            t.APPEND,
            DECIDED_LEAVES,
            **t.event_params(engagement, p.owner, "owner", "decline", "PROCUREMENT_ROUTE", "DECLINED", reason="BUDGET"),
        )
        await t.act(conn, p.developer)
        for side in (("pause", "ON_HOLD"), ("withdraw", "WITHDRAWN")):
            params = t.event_params(engagement, p.developer, "developer", side[0], "PROCUREMENT_ROUTE", side[1])
            await t.expect(conn, t.APPEND, DECIDED_LEAVES, **params)
        await t.act(conn, p.owner, p.org)
        await t.run(conn, t.APPEND, **move)
        assert await t.state_of(conn, engagement) == "INTEREST_CONFIRMED"
        await immediately(conn)

        await t.as_owner(conn)
        q, unnamed = await public_scene(conn)
        await t.act(conn, q.signatory, q.org)  # 3b entered without naming the contact
        await t.append(conn, unnamed, q.signatory, "signatory", "approve", "UNDER_REVIEW", "PROCUREMENT_ROUTE")
        await t.act(conn, q.owner, q.org)
        await t.run(
            conn,
            "UPDATE engagements SET procurement_route = 'ppp_pip', procurement_justification = NULL WHERE id = :e",
            e=unnamed,
        )
        params = t.event_params(unnamed, q.owner, "admin", MOVE, "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED")
        await t.expect(conn, t.APPEND, NEEDS_CONTACT, **params)


async def test_the_direct_route_needs_twenty_characters_of_justification(owner_engine: AsyncEngine) -> None:
    """The CHECKs: ``direct`` needs a justification of at least 20 characters once trimmed (none, 19 and a padded 19
    are refused; 20 are accepted); a justification is not blank, at most 1,000 characters (line breaks allowed) and
    only with a route; another route needs none; a named contact has its date once the route is decided."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await route_scene(conn)
        await t.act(conn, p.owner, p.org)
        direct = "ck_engagements_procurement_direct_justified"
        valid = "ck_engagements_procurement_justification_valid"
        for route, why, refusal in (
            ("direct", None, direct),
            ("direct", "x" * 19, direct),
            ("direct", "   " + "x" * 19 + "   ", direct),
            ("rfq_tender", "   ", valid),
            ("rfq_tender", "\n\t ", valid),
            ("ppp_pip", "x" * 1001, valid),
        ):
            await t.expect(conn, DECIDE, refusal, **decision(engagement, route, why))
        await t.expect(
            conn,
            "UPDATE engagements SET procurement_justification = :why WHERE id = :e",
            valid,
            why=WHY,
            e=engagement,
        )
        await t.expect(
            conn,
            "UPDATE engagements SET procurement_route = 'rfq_tender', contact_by = NULL WHERE id = :e",
            "ck_engagements_contact_consistent",
            e=engagement,
        )
        for route, why in (
            ("direct", "x" * 20),
            ("rfq_tender", None),
            ("innovation_challenge", "Line one of the reason.\nLine two.\n" + "y" * 900),
        ):
            savepoint = await conn.begin_nested()
            await t.run(conn, DECIDE, **decision(engagement, route, why))
            assert (await conn.execute(sa.text(DECISION), {"e": engagement})).one().route == route
            await savepoint.rollback()


# --- the nudges ledger (REQ-NOT-05) ----------------------------------------------------------------------------------

RECORD = "SELECT app_record_nudge(:e, :kind, :key, CAST(:state AS engagement_state))"
CANDIDATES = "SELECT engagement_id, org_id, developer_id, member_id FROM app_nudge_candidates()"
NUDGES = "SELECT count(*) FROM engagement_nudges WHERE engagement_id = :e"
JOB_ONLY = "the nudge job only, with no user bound"


async def private_scene(conn: AsyncConnection, until: str) -> tuple[t.Parties, UUID]:
    """As the owner: the tracker's parties (a private organisation) and the developer's engagement walked to
    ``until``."""
    p = await t.parties(conn)
    await t.act(conn, p.developer)
    engagement = await t.engage(conn, p)
    await t.walk(conn, p, engagement, until)
    return p, engagement


async def test_a_nudge_is_recorded_once_and_only_by_the_job(owner_engine: AsyncEngine) -> None:
    """Given an engagement at INTEREST_CONFIRMED, When the job (no user bound) records a contact escalation, Then the
    first call returns true and stores the engagement's organisation and the shared clock's time; the same kind and key
    return false and store nothing; another key or kind is a new nudge; a session bound to a user (a member, the
    developer) is refused; NULL arguments, an unknown kind, a key that is not a code and an unknown engagement are
    refused; nothing is recorded (false) once the engagement has ended or when it is no longer in the state the job
    decided the nudge in (a party's command committed between the job's read and the record)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await private_scene(conn, "INTEREST_CONFIRMED")
        here = "INTEREST_CONFIRMED"
        nudge = {"e": engagement, "kind": "contact_escalation", "key": "bd:3", "state": here}
        for user, org in ((p.owner, p.org), (p.developer, None)):
            await t.act(conn, user, org)
            await t.expect(conn, RECORD, JOB_ONLY, **nudge)
        await t.act(conn, None)
        before = await t.run(conn, "SELECT app_clock_now()")
        assert await t.run(conn, RECORD, **nudge) is True
        after = await t.run(conn, "SELECT app_clock_now()")
        assert await t.run(conn, RECORD, **nudge) is False
        assert await t.run(conn, RECORD, e=engagement, kind="contact_escalation", key="bd:6", state=here) is True
        assert await t.run(conn, RECORD, e=engagement, kind="contact_overdue", key="2026-12-01", state=here) is True
        for stale in ("NDA_PENDING", "CONTACT_MADE", "UNDER_REVIEW"):  # the job read another state: nothing recorded
            assert await t.run(conn, RECORD, e=engagement, kind="contact_escalation", key="bd:7", state=stale) is False
        for bad, refusal in (
            ({"kind": None}, "name the engagement, the kind, the key and the expected state"),
            ({"key": None}, "name the engagement, the kind, the key and the expected state"),
            ({"state": None}, "name the engagement, the kind, the key and the expected state"),
            ({"kind": "pester"}, "ck_engagement_nudges_kind_known"),
            ({"key": "Dear Amina"}, "ck_engagement_nudges_key_valid"),
            ({"key": "amina@example.test"}, "ck_engagement_nudges_key_valid"),
            ({"key": ""}, "ck_engagement_nudges_key_valid"),
            ({"key": "x" * 121}, "ck_engagement_nudges_key_valid"),
            ({"e": uuid7()}, "no engagement"),
        ):
            await t.expect(conn, RECORD, refusal, **(nudge | {"key": "bd:9"} | bad))
        await t.as_owner(conn)
        stored = (
            await conn.execute(
                sa.text("SELECT org_id, sent_at FROM engagement_nudges WHERE engagement_id = :e AND key = 'bd:3'"),
                {"e": engagement},
            )
        ).one()
        assert stored.org_id == p.org
        assert before <= stored.sent_at <= after
        assert await t.run(conn, NUDGES, e=engagement) == 3

        q, ended = await private_scene(conn, "UNDER_REVIEW")
        await t.act(conn, q.owner, q.org)
        await t.append(conn, ended, q.owner, "owner", "decline", "UNDER_REVIEW", "DECLINED", reason="BUDGET")
        await t.act(conn, None)
        for state in ("UNDER_REVIEW", "DECLINED"):  # ended: nothing, whatever state the job names
            assert await t.run(conn, RECORD, e=ended, kind="contact_escalation", key="bd:3", state=state) is False
        assert await t.run(conn, NUDGES, e=ended) == 0

        await t.as_owner(conn)  # the race: the job decided in INTEREST_CONFIRMED, first contact committed meanwhile
        r, raced = await private_scene(conn, "INTEREST_CONFIRMED")
        await t.walk(conn, r, raced, "CONTACT_MADE")
        await t.act(conn, None)
        assert await t.run(conn, RECORD, e=raced, kind="contact_escalation", key="bd:3", state=here) is False
        assert await t.run(conn, NUDGES, e=raced) == 0


async def test_the_ledger_is_append_only_and_the_organisations_alone(owner_engine: AsyncEngine) -> None:
    """Given a recorded nudge, Then the organisation's members read it (a viewer too), the engagement's developer,
    another organisation's member, a member scoped to another organisation and staff admin read none; bridge_app
    inserts, updates and deletes none (no grant), and no role, the owner included, updates, deletes or truncates
    it."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await private_scene(conn, "INTEREST_CONFIRMED")
        await t.act(conn, None)
        recorded = await t.run(
            conn, RECORD, e=engagement, kind="contact_escalation", key="bd:3", state="INTEREST_CONFIRMED"
        )
        assert recorded is True
        for reader, org in ((p.reviewer, p.org), (p.viewer, p.org), (p.owner, None)):
            await t.act(conn, reader, org)
            assert await t.run(conn, NUDGES, e=engagement) == 1, reader
        for reader, org in (
            (p.developer, None),
            (p.other_member, p.other_org),
            (p.owner, p.other_org),
            (p.staff, None),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, NUDGES, e=engagement) == 0, reader
        await t.act(conn, p.owner, p.org)
        for statement in (
            "INSERT INTO engagement_nudges (id, engagement_id, org_id, kind, key)"
            " VALUES (gen_random_uuid(), :e, :org, 'contact_escalation', 'bd:9')",
            "UPDATE engagement_nudges SET key = 'bd:4' WHERE engagement_id = :e",
            "DELETE FROM engagement_nudges WHERE engagement_id = :e",
        ):
            await t.expect(conn, statement, DENIED, e=engagement, org=p.org)
        await t.as_owner(conn)
        for statement in (
            "UPDATE engagement_nudges SET key = 'bd:4' WHERE engagement_id = :e",
            "DELETE FROM engagement_nudges WHERE engagement_id = :e",
            "TRUNCATE engagement_nudges",
        ):
            await t.expect(conn, statement, "is not allowed: the table is append-only", e=engagement)


async def test_the_job_lists_the_engagements_a_nudge_may_be_due_for(owner_engine: AsyncEngine) -> None:
    """Given engagements under review, at INTEREST_CONFIRMED, in a public entity's 3b, at NDA_PENDING, in
    implementation with a milestone submitted for review and one ended, When the job (no user bound) asks, Then it
    gets the four that may be due (ids only) and not the others, each with a member of the organisation to bind: the
    named contact while an active member, else the earliest active owner or admin; a bound session is refused."""
    async with t.as_app(owner_engine) as conn:
        a, review = await private_scene(conn, "UNDER_REVIEW")
        await t.as_owner(conn)
        b, confirmed = await private_scene(conn, "INTEREST_CONFIRMED")
        await t.act(conn, b.owner, b.org)  # the reviewer becomes the named contact, then leaves the organisation
        await t.run(conn, "UPDATE engagements SET contact_user_id = :c WHERE id = :e", c=b.reviewer, e=confirmed)
        await t.as_owner(conn)
        await t.run(
            conn, "UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u", o=b.org, u=b.reviewer
        )
        c, procurement = await route_scene(conn)
        await t.as_owner(conn)
        d, nda = await private_scene(conn, "NDA_PENDING")
        await t.as_owner(conn)
        e, building = await private_scene(conn, "IN_IMPLEMENTATION")
        await t.act(conn, e.developer)
        for state in ("IN_PROGRESS", "SUBMITTED_FOR_REVIEW"):
            await t.run(
                conn,
                "UPDATE milestones SET state = CAST(:s AS milestone_state) WHERE engagement_id = :e",
                s=state,
                e=building,
            )
        await t.as_owner(conn)
        f, quiet = await private_scene(conn, "IN_IMPLEMENTATION")  # its milestone not submitted: nothing to remind
        await t.act(conn, a.owner, a.org)
        await t.append(conn, review, a.owner, "owner", "decline", "UNDER_REVIEW", "DECLINED", reason="BUDGET")

        await t.act(conn, d.owner, d.org)
        await t.expect(conn, CANDIDATES, JOB_ONLY)
        await t.act(conn, None)
        listed = {row.engagement_id: row for row in (await conn.execute(sa.text(CANDIDATES))).all()}
        mine = {review, confirmed, procurement, nda, building, quiet}
        assert set(listed) & mine == {confirmed, procurement, nda, building}
        expected = {
            confirmed: (b.org, b.developer, b.owner),  # the contact left: the earliest owner or admin
            procurement: (c.org, c.developer, c.owner),  # the named contact
            nda: (d.org, d.developer, d.owner),
            building: (e.org, e.developer, e.owner),
        }
        for engagement, (org, developer, member) in expected.items():
            row = listed[engagement]
            assert (row.org_id, row.developer_id, row.member_id) == (org, developer, member), engagement
        assert f.org not in {row.org_id for row in listed.values()}


# --- the team (REQ-TEN-02) -------------------------------------------------------------------------------------------

DEFAULT = (
    "INSERT INTO org_niche_defaults (id, org_id, niche_id, user_id) VALUES (:id, :org, :niche, :user)"
    " ON CONFLICT (org_id, niche_id) DO UPDATE SET user_id = EXCLUDED.user_id"
)
DEFAULTS = "SELECT count(*) FROM org_niche_defaults WHERE org_id = :org"
NOT_TRIAGE = "the default reviewer is an active owner, admin, reviewer or signatory"
ESCALATION = (
    "INSERT INTO org_escalation_contacts (org_id, user_id) VALUES (:org, :user)"
    " ON CONFLICT (org_id) DO UPDATE SET user_id = EXCLUDED.user_id"
)
CONTACT = "SELECT user_id FROM org_escalation_contacts WHERE org_id = :org"
NOT_A_MEMBER = "the escalation contact is an active member"
INVITE = (
    "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at)"
    " VALUES (:id, :org, :email, CAST(:roles AS org_role[]), :hash, :by, app_clock_now() + interval '7 days')"
)
INVITATIONS = "SELECT count(*) FROM invitations WHERE org_id = :org"
ACCEPT = "SELECT app_accept_invitation(:hash, :user)"
PREVIEW = "SELECT org_name, CAST(roles AS text[]) AS roles FROM app_invitation_preview(:h)"
NOT_OPEN = "no open invitation with that token"
MISMATCH = "the invitation is for another email address"
LAST_OWNER = "the organisation's last active owner is neither removed nor demoted"
RLS = "row-level security"


async def add_niche(conn: AsyncConnection) -> UUID:
    """As the owner: a niche of its own."""
    await t.as_owner(conn)
    niche = uuid7()
    await t.run(
        conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Team')", id=niche, s=f"team-{niche.hex}"
    )
    return niche


async def add_user(conn: AsyncConnection, email: str | None = None, *, verified: bool = True) -> UUID:
    """As the owner: a user (with a verified email unless told otherwise)."""
    await t.as_owner(conn)
    user = uuid7()
    await t.run(
        conn,
        "INSERT INTO users (id, email, display_name, email_verified_at)"
        " VALUES (:id, :email, 'Invitee', CASE WHEN :verified THEN now() END)",
        id=user,
        email=email or f"invitee-{user.hex}@example.test",
        verified=verified,
    )
    return user


def default(p: t.Parties, niche: UUID, user: UUID, org: UUID | None = None) -> dict[str, object]:
    return {"id": uuid7(), "org": org or p.org, "niche": niche, "user": user}


def invitation(org: UUID, email: str, by: UUID, roles: str = "{reviewer}") -> dict[str, object]:
    token = uuid7().bytes
    return {"id": uuid7(), "org": org, "email": email, "roles": roles, "hash": _sha256(token), "by": by}


def _sha256(token: bytes) -> bytes:
    return hashlib.sha256(token).digest()


async def test_niche_defaults_are_set_by_admins_for_triage_members(owner_engine: AsyncEngine) -> None:
    """An owner or admin sets the organisation's default reviewer per niche (one per niche, upserted; the times the
    database's), to an active owner, admin, reviewer or signatory only (a viewer, a finance member, a removed member,
    the developer and another organisation's member are refused); a reviewer writes none; the members read them and
    nobody else does; a default's organisation and niche never change; a member who leaves or loses the triage roles
    loses their defaults."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        niche, other_niche, third_niche = await add_niche(conn), await add_niche(conn), await add_niche(conn)
        admin = await add_member(conn, p, "{admin}")
        removed = await add_member(conn, p, "{reviewer}")
        await t.run(conn, "UPDATE memberships SET status = 'removed' WHERE user_id = :u", u=removed)
        await t.act(conn, p.owner, p.org)
        await t.run(conn, DEFAULT, **default(p, niche, p.reviewer))
        created = (
            await conn.execute(
                sa.text("SELECT created_at, updated_at FROM org_niche_defaults WHERE org_id = :org AND niche_id = :n"),
                {"org": p.org, "n": niche},
            )
        ).one()
        await t.act(conn, admin, p.org)
        await t.run(conn, DEFAULT, **default(p, niche, p.signatory))  # the upsert: one per niche
        await t.run(conn, DEFAULT, **default(p, other_niche, admin))
        for refused in (p.viewer, p.finance, removed, p.developer, p.other_member):
            await t.expect(conn, DEFAULT, NOT_TRIAGE, **default(p, other_niche, refused))
        await t.expect(
            conn,
            "INSERT INTO org_niche_defaults (id, org_id, niche_id, user_id) VALUES (:id, :org, :niche, :user)",
            "uq_org_niche_defaults_org_id_niche_id",
            **default(p, niche, p.reviewer),
        )
        row = (
            await conn.execute(
                sa.text(
                    "SELECT user_id, created_at, updated_at FROM org_niche_defaults"
                    " WHERE org_id = :org AND niche_id = :n"
                ),
                {"org": p.org, "n": niche},
            )
        ).one()
        assert (row.user_id, row.created_at) == (p.signatory, created.created_at)
        assert row.updated_at >= created.updated_at
        await t.act(conn, p.reviewer, p.org)
        await t.expect(conn, DEFAULT, RLS, **default(p, third_niche, p.reviewer))
        assert await t.rowcount(conn, "DELETE FROM org_niche_defaults WHERE org_id = :org", org=p.org) == 0
        for reader, org, seen in (
            (p.viewer, p.org, 2),
            (p.reviewer, None, 2),
            (p.developer, None, 0),
            (p.other_member, p.other_org, 0),
            (p.owner, p.other_org, 0),
            (p.staff, None, 0),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, DEFAULTS, org=p.org) == seen, reader
        await t.as_owner(conn)
        await t.expect(
            conn,
            "UPDATE org_niche_defaults SET niche_id = :n WHERE org_id = :org AND niche_id = :old",
            "never change",
            n=await add_niche(conn),
            org=p.org,
            old=niche,
        )
        await t.act(conn, p.owner, p.org)
        await t.run(
            conn, "UPDATE memberships SET roles = '{finance}' WHERE org_id = :org AND user_id = :u", org=p.org, u=admin
        )
        await t.run(
            conn,
            "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u",
            org=p.org,
            u=p.signatory,
        )
        assert await t.run(conn, DEFAULTS, org=p.org) == 0  # the admin lost the triage roles, the signatory left
        await t.run(conn, DEFAULT, **default(p, niche, p.reviewer))
        assert await t.rowcount(conn, "DELETE FROM org_niche_defaults WHERE org_id = :org", org=p.org) == 1


async def test_the_escalation_contact_is_the_members_own_and_leaves_with_them(owner_engine: AsyncEngine) -> None:
    """The security review's MINOR (P28-M): the escalation contact is a row of ``org_escalation_contacts``, not a column
    of ``organizations`` (whose listed rows every signed-in user reads). An owner or admin names an active member, one
    per organisation (an upsert; ``updated_at`` the database's), never another organisation's member, the developer, a
    removed member or an unknown user; a reviewer writes none; the organisation's members read it (a viewer too) and
    nobody else does: not another organisation's member, not the developer of an engagement with the organisation, not
    a member under another organisation's context, not staff admin. The organisation never changes; the contact goes
    when they leave the organisation and when their account is deleted."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        assert (
            await t.run(
                conn,
                "SELECT count(*) FROM information_schema.columns WHERE table_name = 'organizations'"
                " AND column_name LIKE '%escalation%'",
            )
            == 0
        )
        removed = await add_member(conn, p, "{reviewer}")
        await t.run(conn, "UPDATE memberships SET status = 'removed' WHERE user_id = :u", u=removed)
        admin = await add_member(conn, p, "{admin}")
        await t.act(conn, p.developer)
        await t.engage(conn, p)  # the developer has an engagement with the organisation
        await t.act(conn, admin, p.org)
        before = await t.run(conn, "SELECT app_clock_now()")
        await t.run(conn, ESCALATION, org=p.org, user=p.reviewer)
        await t.run(conn, ESCALATION, org=p.org, user=p.signatory)  # one per organisation: the upsert replaces it
        for refused in (p.other_member, p.developer, removed, uuid7()):
            await t.expect(conn, ESCALATION, NOT_A_MEMBER, org=p.org, user=refused)
        await t.act(conn, p.reviewer, p.org)
        await t.expect(conn, ESCALATION, RLS, org=p.org, user=p.viewer)
        assert await t.rowcount(conn, "DELETE FROM org_escalation_contacts WHERE org_id = :org", org=p.org) == 0
        for reader, org, seen in (
            (p.viewer, p.org, p.signatory),
            (p.reviewer, None, p.signatory),
            (p.developer, None, None),
            (p.developer, p.org, None),
            (p.other_member, p.other_org, None),
            (p.owner, p.other_org, None),
            (p.staff, None, None),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, CONTACT, org=p.org) == seen, reader
        await t.as_owner(conn)
        assert (
            await t.run(conn, "SELECT updated_at FROM org_escalation_contacts WHERE org_id = :org", org=p.org) >= before
        )
        await t.expect(
            conn,
            "UPDATE org_escalation_contacts SET org_id = :other WHERE org_id = :org",
            "the organisation never changes",
            other=p.other_org,
            org=p.org,
        )
        await t.act(conn, p.owner, p.org)
        await t.run(
            conn,
            "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u",
            org=p.org,
            u=p.signatory,
        )
        assert await t.run(conn, CONTACT, org=p.org) is None  # the leaver's seat went
        await t.run(conn, ESCALATION, org=p.org, user=p.viewer)
        await t.as_owner(conn)
        await t.run(conn, "DELETE FROM users WHERE id = :u", u=p.viewer)
        assert await t.run(conn, CONTACT, org=p.org) is None  # and a deleted account's


async def test_invitations_are_the_admins_own_across_two_organisations(owner_engine: AsyncEngine) -> None:
    """An owner or admin invites as themselves (only an owner with a protected role), lists, revokes (the shared clock,
    once) and resends (a new token, the old one dead) the organisation's invitations; a member who is not an admin,
    another organisation's admin and a forged organisation context see and touch none; one open invitation per address
    (case-insensitive) until it is revoked; nothing else of an invitation is the app's to change, and nothing of an
    accepted or revoked one is anybody's."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        admin = await add_member(conn, p, "{admin}")
        await t.act(conn, admin, p.org)
        mine = invitation(p.org, "Newcomer@Example.test", admin)
        await t.run(conn, INVITE, **mine)
        await t.expect(conn, INVITE, RLS, **invitation(p.org, "someone@example.test", p.owner))  # not as themselves
        await t.expect(conn, INVITE, RLS, **invitation(p.org, "signer@example.test", admin, "{signatory}"))
        await t.expect(conn, INVITE, "uq_invitations_open", **invitation(p.org, "newcomer@example.TEST", admin))
        await t.act(conn, p.owner, p.org)
        await t.run(conn, INVITE, **invitation(p.org, "signer@example.test", p.owner, "{signatory}"))
        for reader, org, seen in (
            (admin, p.org, 2),
            (p.owner, None, 2),
            (p.reviewer, p.org, 0),
            (p.signatory, p.org, 0),
            (p.other_member, p.other_org, 0),
            (p.owner, p.other_org, 0),
            (p.developer, None, 0),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, INVITATIONS, org=p.org) == seen, reader
        await t.act(conn, p.other_member, p.other_org)
        revoke = "UPDATE invitations SET revoked_at = '2000-01-01' WHERE id = :id"
        assert await t.rowcount(conn, revoke, id=mine["id"]) == 0
        await t.expect(conn, INVITE, RLS, **invitation(p.org, "outsider@example.test", p.other_member))

        await t.act(conn, admin, p.org)
        for statement in (
            "UPDATE invitations SET accepted_at = now() WHERE id = :id",
            "UPDATE invitations SET email = 'other@example.test' WHERE id = :id",
            "UPDATE invitations SET invited_by = invited_by WHERE id = :id",
        ):
            await t.expect(conn, statement, DENIED, id=mine["id"])
        await t.expect(
            conn,
            "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at, revoked_at)"
            " VALUES (:id, :org, :email, '{viewer}', :hash, :by, now(), now())",
            DENIED,
            **invitation(p.org, "late@example.test", admin),
        )
        resent = _sha256(b"a new token")
        await t.run(
            conn,
            "UPDATE invitations SET token_hash = :h, expires_at = now() + interval '7 days' WHERE id = :id",
            h=resent,
            id=mine["id"],
        )
        assert await t.run(conn, "SELECT count(*) FROM app_invitation_preview(:h)", h=mine["hash"]) == 0
        assert await t.run(conn, "SELECT count(*) FROM app_invitation_preview(:h)", h=resent) == 1
        before = await t.run(conn, "SELECT app_clock_now()")
        assert await t.rowcount(conn, revoke, id=mine["id"]) == 1
        assert await t.run(conn, "SELECT revoked_at FROM invitations WHERE id = :id", id=mine["id"]) >= before
        assert await t.rowcount(conn, revoke, id=mine["id"]) == 0  # open invitations only
        await t.run(conn, INVITE, **invitation(p.org, "newcomer@example.test", admin))  # the address is free again
        await t.expect(
            conn, INVITE, "ck_invitations_roles_not_empty", **invitation(p.org, "x@example.test", admin, "{}")
        )
        long_link = INVITE.replace("interval '7 days'", "interval '31 days'")
        await t.expect(
            conn, long_link, "ck_invitations_expires_within_30_days", **invitation(p.org, "y@example.test", admin)
        )
        await t.run(
            conn, INVITE.replace("interval '7 days'", "interval '30 days'"), **invitation(p.org, "z@x.test", admin)
        )
        await t.expect(
            conn,
            "UPDATE invitations SET expires_at = created_at + interval '31 days'"
            " WHERE org_id = :org AND email = 'z@x.test'",
            "ck_invitations_expires_within_30_days",
            org=p.org,
        )
        await t.as_owner(conn)
        await t.expect(conn, revoke, "an accepted or revoked invitation never changes", id=mine["id"])
        await t.expect(
            conn,
            "UPDATE invitations SET roles = '{viewer}' WHERE org_id = :org AND revoked_at IS NULL",
            "never change",
            org=p.org,
        )
        await t.expect(
            conn,
            "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at, revoked_at)"
            " VALUES (:id, :org, :email, '{viewer}', :hash, :by, now(), now())",
            "an invitation is created open",
            **invitation(p.org, "late@example.test", admin),
        )
        backdated = invitation(p.org, "backdated@example.test", admin)
        await t.run(  # the creation time is the shared clock's, whatever is sent (the owner's own insert too)
            conn,
            "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at, created_at)"
            " VALUES (:id, :org, :email, '{viewer}', :hash, :by, now() + interval '1 day', '2000-01-01')",
            **backdated,
        )
        created = await t.run(conn, "SELECT created_at FROM invitations WHERE id = :id", id=backdated["id"])
        assert created >= before


async def test_an_invitation_is_accepted_once_by_its_address_while_open(owner_engine: AsyncEngine) -> None:
    """The invitee, signed in with a verified email equal to the invitation's (case-insensitive), accepts it: an active
    membership with its roles, the invitation accepted (the shared clock) and its organisation returned, and the
    preview gone. Refused: another user's id or no user bound; another address or an unverified one; an accepted,
    revoked, resent-over, expired (on the shared clock) or unknown token; an active member. A removed membership is
    reactivated with the invitation's roles. The preview answers the organisation's name and the roles of an open
    invitation, to any session, and nothing else."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        invitee = await add_user(conn, "amina.invitee@example.test")
        stranger = await add_user(conn)
        unverified = await add_user(conn, "unverified.invitee@example.test", verified=False)
        await t.act(conn, p.owner, p.org)
        open_one = invitation(p.org, "AMINA.Invitee@example.test", p.owner, "{reviewer,finance}")
        await t.run(conn, INVITE, **open_one)
        await t.act(conn, None)
        preview = (await conn.execute(sa.text(PREVIEW), {"h": open_one["hash"]})).one()
        assert (preview.org_name, sorted(preview.roles)) == ("Tracker Ltd", ["finance", "reviewer"])

        await t.act(conn, invitee)
        await t.expect(conn, ACCEPT, "accepts for themselves only", hash=open_one["hash"], user=stranger)
        await t.act(conn, None)
        await t.expect(conn, ACCEPT, "accepts for themselves only", hash=open_one["hash"], user=invitee)
        await t.act(conn, stranger)
        await t.expect(conn, ACCEPT, MISMATCH, hash=open_one["hash"], user=stranger)
        await t.act(conn, invitee)
        await t.expect(conn, ACCEPT, NOT_OPEN, hash=_sha256(b"unknown"), user=invitee)
        assert await t.run(conn, ACCEPT, hash=open_one["hash"], user=invitee) == p.org
        await t.expect(conn, ACCEPT, NOT_OPEN, hash=open_one["hash"], user=invitee)  # accepted already
        await t.act(conn, None)
        assert await t.run(conn, "SELECT count(*) FROM app_invitation_preview(:h)", h=open_one["hash"]) == 0
        await t.as_owner(conn)
        joined = (
            await conn.execute(
                sa.text(
                    "SELECT CAST(m.status AS text) AS status, CAST(m.roles AS text[]) AS roles, i.accepted_at"
                    " FROM memberships m JOIN invitations i ON i.org_id = m.org_id AND i.id = :i"
                    " WHERE m.org_id = :org AND m.user_id = :u"
                ),
                {"i": open_one["id"], "org": p.org, "u": invitee},
            )
        ).one()
        assert (joined.status, sorted(joined.roles)) == ("active", ["finance", "reviewer"])
        assert joined.accepted_at is not None

        await t.act(conn, p.owner, p.org)
        again = invitation(p.org, "amina.invitee@example.test", p.owner)
        await t.run(conn, INVITE, **again)
        await t.act(conn, invitee)
        await t.expect(conn, ACCEPT, "already an active member", hash=again["hash"], user=invitee)

        await t.act(conn, p.owner, p.org)
        unverified_one = invitation(p.org, "unverified.invitee@example.test", p.owner)
        revoked = invitation(p.org, "revoked.invitee@example.test", p.owner)
        expiring = invitation(p.org, "later.invitee@example.test", p.owner)
        for params in (unverified_one, revoked, expiring):
            await t.run(conn, INVITE, **params)
        await t.run(conn, "UPDATE invitations SET revoked_at = now() WHERE id = :id", id=revoked["id"])
        await t.act(conn, unverified)
        await t.expect(conn, ACCEPT, MISMATCH, hash=unverified_one["hash"], user=unverified)
        revoked_user = await add_user(conn, "revoked.invitee@example.test")
        await t.act(conn, revoked_user)
        await t.expect(conn, ACCEPT, NOT_OPEN, hash=revoked["hash"], user=revoked_user)
        later_user = await add_user(conn, "later.invitee@example.test")
        await t.as_owner(conn)  # the shared clock moves past the seven days
        await t.run(conn, "UPDATE test_clock SET enabled = true, clock_offset = interval '8 days'")
        await t.act(conn, None)
        assert await t.run(conn, "SELECT count(*) FROM app_invitation_preview(:h)", h=expiring["hash"]) == 0
        await t.act(conn, later_user)
        await t.expect(conn, ACCEPT, NOT_OPEN, hash=expiring["hash"], user=later_user)

        await t.act(conn, p.owner, p.org)  # a removed member is invited back as a signatory
        await t.run(conn, "UPDATE invitations SET revoked_at = now() WHERE id = :id", id=again["id"])
        await t.run(
            conn, "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u", org=p.org, u=invitee
        )
        back = invitation(p.org, "amina.invitee@example.test", p.owner, "{signatory}")
        await t.run(conn, INVITE, **back)
        await t.act(conn, invitee)
        assert await t.run(conn, ACCEPT, hash=back["hash"], user=invitee) == p.org
        await t.as_owner(conn)
        rejoined = await t.run(
            conn,
            "SELECT CAST(roles AS text[]) FROM memberships WHERE org_id = :org AND user_id = :u AND status = 'active'",
            org=p.org,
            u=invitee,
        )
        assert rejoined == ["signatory"]


async def test_the_last_active_owner_is_neither_removed_nor_demoted(owner_engine: AsyncEngine) -> None:
    """The organisation's own writes never remove or demote its last active owner, in one row or many; with a second
    owner either may go; staff's roster correction (a definer function) is not judged."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)  # the owner holds owner and admin, alone
        await t.act(conn, p.owner, p.org)
        mine = {"org": p.org, "u": p.owner}
        demote = "UPDATE memberships SET roles = '{admin}' WHERE org_id = :org AND user_id = :u"
        remove = "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u"
        await t.expect(conn, demote, LAST_OWNER, **mine)
        await t.expect(conn, remove, LAST_OWNER, **mine)
        await t.run(conn, "UPDATE memberships SET roles = '{owner}' WHERE org_id = :org AND user_id = :u", **mine)
        second = await add_member(conn, p, "{owner}")
        await t.act(conn, p.owner, p.org)
        await t.expect(
            conn,
            "UPDATE memberships SET roles = '{admin}' WHERE org_id = :org AND 'owner' = ANY (roles)",
            LAST_OWNER,
            org=p.org,
        )
        await t.run(conn, demote, **mine)  # the second owner stays
        await t.act(conn, second, p.org)
        await t.expect(conn, remove, LAST_OWNER, org=p.org, u=second)
        await t.run(conn, "UPDATE memberships SET roles = '{owner,admin}' WHERE org_id = :org AND user_id = :u", **mine)
        await t.run(conn, remove, org=p.org, u=second)  # now the first owner stays
        await t.as_owner(conn)  # staff admin's correction (a definer) may leave an organisation without an owner
        membership = await t.run(
            conn, "SELECT id FROM memberships WHERE org_id = :org AND user_id = :u", org=p.org, u=p.owner
        )
        await t.act(conn, p.staff)
        assert await t.run(conn, "SELECT app_staff_remove_membership(:m, 'upheld dispute')", m=membership) is True


async def test_two_owners_removing_each_other_at_once_leave_one(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given an organisation with two active owners (committed), When each removes the other in concurrent
    transactions, Then the second waits for the first (the guard's advisory lock per organisation) and, once the first
    commits, is refused: one owner stays."""
    org, owners = uuid7(), (uuid7(), uuid7())
    async with owner_engine.begin() as conn:
        await t.run(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source) VALUES (:id, 'sme', 'Two Owners Ltd', :s,"
            " 'self_signup')",
            id=org,
            s=f"two-owners-{org.hex}",
        )
        for owner in owners:
            await t.run(
                conn,
                "INSERT INTO users (id, email, display_name, email_verified_at) VALUES (:id, :e, 'Owner', now())",
                id=owner,
                e=f"owner-{owner.hex}@example.test",
            )
            await t.member(conn, org, owner, "{owner,admin}")
    remove = "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u"
    bind = "SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"
    try:
        async with app_engine.connect() as first, app_engine.connect() as second, owner_engine.connect() as observer:
            await first.begin()
            await first.execute(sa.text(bind), {"u": str(owners[0]), "o": str(org)})
            await first.execute(sa.text(remove), {"org": org, "u": owners[1]})
            await second.begin()
            await second.execute(sa.text(bind), {"u": str(owners[1]), "o": str(org)})
            pid = await t.backend_pid(second)
            racing = asyncio.create_task(second.execute(sa.text(remove), {"org": org, "u": owners[0]}))
            await t.wait_until_blocked(observer, pid, racing)
            await first.commit()
            with pytest.raises(DBAPIError, match=LAST_OWNER):
                await racing
            await second.rollback()
        async with owner_engine.connect() as conn:
            active = await t.run(
                conn,
                "SELECT array_agg(user_id) FROM memberships WHERE org_id = :org AND status = 'active'"
                " AND 'owner' = ANY (roles)",
                org=org,
            )
            assert active == [owners[0]]
    finally:
        async with owner_engine.begin() as conn:
            await t.run(conn, "DELETE FROM organizations WHERE id = :id", id=org)
            await t.run(conn, "DELETE FROM users WHERE id = ANY (:ids)", ids=list(owners))
