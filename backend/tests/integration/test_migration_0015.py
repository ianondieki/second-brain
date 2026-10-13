"""Revision 0015 (P28-M; REQ-ENG-06, AC-TRACK-5): the database half of the procurement route (3b).

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

Every test runs in one rolled-back transaction (``tracker.as_app``); the round trip and the grants are in
``test_migrations.py``.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import sqlalchemy as sa
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


async def test_3b_follows_under_review_only_and_leads_to_interest_confirmed(owner_engine: AsyncEngine) -> None:
    """Revision 0015's predecessors: PROCUREMENT_ROUTE is entered from UNDER_REVIEW only (never from SUBMITTED, never
    back from INTEREST_CONFIRMED) and left for INTEREST_CONFIRMED, never straight for CONTACT_MADE (revision 0003's
    "around stage 3" path); stage 3 then goes on to CONTACT_MADE as before."""
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
