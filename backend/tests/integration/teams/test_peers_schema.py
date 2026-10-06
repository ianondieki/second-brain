"""Revision 0011 (REQ-DEV-03; P22 track C, D-58): peers at the database, each test in one rolled-back transaction.

- C1 at the database: the switch is the developer's own (``peers_visible``) and its time the database's; only
  developers who opted in see peers and appear among them; a developer not opted in, staff, organisation-only
  accounts and unbound sessions are refused.
- C2 at the database: the county-or-niche rule (liked niches only; a county, never the country); the order (more shared
  niches first, then the caller's county, then the newest opt-in); the page bounds; nothing but the card's fields;
  real and demo accounts apart.
- A block hides both from each other (peers and cards) until it is lifted; a developer's card reaches another
  developer only as a counterpart of an invitation or as a peer, never across a block.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import (
    BLOCK,
    DENIED,
    INVITE,
    PEERS,
    UNBLOCK,
    card,
    county,
    decide,
    developer,
    handle,
    invitation_params,
    invite,
    niche,
    org_only,
    peer_ids,
    peers,
    problem,
    refused,
    slug,
    team,
)

OPTED_IN = "SELECT peers_visible, peers_opted_in_at FROM developer_profiles WHERE user_id = :u"
NOT_REACHABLE = "the recipient is neither a peer nor a counterpart of the sender"
SWITCH = "UPDATE developer_profiles SET peers_visible = :on WHERE user_id = :u"


async def test_the_switch_is_the_developers_own_and_its_time_the_databases(owner_engine: AsyncEngine) -> None:
    """Given a developer who has not opted in, When they turn the switch on, off and on again, Then the database sets
    the opt-in time at each turn on (the shared clock), keeps it while the switch stays on and clears it when off,
    whatever was sent; nobody else turns another's switch, and bridge_app never writes the time itself."""
    async with t.as_app(owner_engine) as conn:
        dev, other = await developer(conn, "dev", peers=False), await developer(conn, "other", peers=False)
        await t.act(conn, dev)
        assert tuple((await conn.execute(sa.text(OPTED_IN), {"u": dev})).one()) == (False, None)
        before: datetime = await t.run(conn, "SELECT app_clock_now()")
        assert await t.rowcount(conn, SWITCH, on=True, u=dev) == 1
        on, first = (await conn.execute(sa.text(OPTED_IN), {"u": dev})).one()
        assert on is True
        assert first > before
        assert await t.rowcount(conn, SWITCH, on=True, u=dev) == 1  # still on: the time is kept
        assert (await conn.execute(sa.text(OPTED_IN), {"u": dev})).one()[1] == first
        await refused(conn, "UPDATE developer_profiles SET peers_opted_in_at = now() WHERE user_id = :u", DENIED, u=dev)
        assert await t.rowcount(conn, SWITCH, on=True, u=other) == 0  # another's profile: RLS
        assert await t.rowcount(conn, SWITCH, on=False, u=dev) == 1
        assert tuple((await conn.execute(sa.text(OPTED_IN), {"u": dev})).one()) == (False, None)
        assert await t.rowcount(conn, SWITCH, on=True, u=dev) == 1
        assert (await conn.execute(sa.text(OPTED_IN), {"u": dev})).one()[1] > first
        await t.as_owner(conn)  # every role: the owner's value is replaced too
        await t.run(conn, "UPDATE developer_profiles SET peers_opted_in_at = '2001-01-01' WHERE user_id = :u", u=dev)
        assert (await conn.execute(sa.text(OPTED_IN), {"u": dev})).one()[1].year > 2001
        sent = await developer(conn, "sent", peers=False)
        await t.run(
            conn,
            "UPDATE developer_profiles SET peers_visible = true, peers_opted_in_at = '2001-01-01' WHERE user_id = :u",
            u=sent,
        )
        assert (await conn.execute(sa.text(OPTED_IN), {"u": sent})).one()[1].year > 2001
        await t.run(conn, SWITCH, on=False, u=sent)
        assert (await conn.execute(sa.text(OPTED_IN), {"u": sent})).one()[1] is None
        inserted = await developer(conn, "inserted", peers=True)  # an insert with the switch on is timed too
        assert (await conn.execute(sa.text(OPTED_IN), {"u": inserted})).one()[1] is not None


async def test_only_developers_who_opted_in_see_peers_and_appear(owner_engine: AsyncEngine) -> None:
    """Given developers sharing a liked niche, When each asks for peers, Then a developer who opted in sees the others
    who opted in and nobody else (one who did not opt in, a suspended one, a staff member with a developer profile);
    a developer who did not opt in, staff, a suspended account, an organisation-only account and an unbound session are
    refused (insufficient_privilege)."""
    async with t.as_app(owner_engine) as conn:
        shared = await niche(conn, "fintech")
        amina = await developer(conn, "amina", liked=(shared,))
        brian = await developer(conn, "brian", liked=(shared,))
        hidden = await developer(conn, "hidden", peers=False, liked=(shared,))
        staff = await developer(conn, "staff", liked=(shared,), staff="admin")
        gone = await developer(conn, "gone", liked=(shared,))
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=gone)
        member = await org_only(conn)
        assert await peer_ids(conn, amina) == [brian]
        assert await peer_ids(conn, brian) == [amina]
        for caller in (hidden, staff, gone, member, None):
            await t.act(conn, caller)
            await refused(conn, PEERS, "developers who opted in to peers only", "42501", limit=20, offset=0)
        await t.act(conn, amina)
        visible = "SELECT app_is_visible_peer(:u)"
        assert [await t.run(conn, visible, u=u) for u in (brian, hidden, staff, gone, member)] == [True] + [False] * 4
        await t.act(conn, member)  # a caller who is no developer learns nothing of anyone's opt-in
        assert await t.run(conn, visible, u=brian) is False
        await t.act(conn, brian)
        assert await t.rowcount(conn, "SELECT 1 FROM developer_profiles WHERE user_id = :u", u=amina) == 0


async def test_a_peer_shares_a_liked_niche_or_the_county(owner_engine: AsyncEngine) -> None:
    """Given a developer in a county with a liked niche, When they ask for peers, Then a developer who opted in appears
    when they share a liked niche (a followed one does not count, on either side) or are in the caller's county (a
    county, never the country), with the shared niches' slugs, whether the county is the caller's and the county's
    name; one with neither does not appear."""
    async with t.as_app(owner_engine) as conn:
        kisumu, nakuru = await county(conn, "Kisumu"), await county(conn, "Nakuru")
        agri, health = await niche(conn, "agri"), await niche(conn, "health")
        caller = await developer(conn, "caller", county_code=kisumu, liked=(agri,), followed=(health,))
        neighbour = await developer(conn, "neighbour", county_code=kisumu)
        colleague = await developer(conn, "colleague", county_code=nakuru, liked=(agri,))
        nowhere = await developer(conn, "nowhere", liked=(agri, health))
        stranger = await developer(conn, "stranger", county_code=nakuru, liked=(health,))
        follower = await developer(conn, "follower", county_code=nakuru, followed=(agri,))
        found = {row.user_id: row for row in await peers(conn, caller)}
        assert set(found) == {neighbour, colleague, nowhere}
        assert stranger not in found
        assert follower not in found
        agri_slug = await slug(conn, agri)
        near = found[neighbour]
        assert (near.county_code, near.county_name, near.shared_niches, near.same_county) == (
            kisumu,
            "Kisumu",
            [],
            True,
        )
        far = found[colleague]
        assert (far.county_code, far.county_name, far.shared_niches, far.same_county) == (
            nakuru,
            "Nakuru",
            [agri_slug],
            False,
        )
        assert (found[nowhere].county_code, found[nowhere].shared_niches) == (None, [agri_slug])
        # Kenya is the country, not a county: two developers there are not neighbours by it
        country, compatriot = await developer(conn, "country", county_code="KE"), await developer(conn, "kenyan")
        await t.run(conn, "UPDATE developer_profiles SET county_code = 'KE' WHERE user_id = :u", u=compatriot)
        assert await peer_ids(conn, country) == []


async def test_peers_come_by_shared_niches_then_county_then_newest_opt_in(owner_engine: AsyncEngine) -> None:
    """Given peers with two, one and no shared niches, in and out of the caller's county, opted in at different times,
    When the caller asks, Then two shared niches come before one, among equals the caller's county first, then the
    newest opt-in (``late`` turned the switch on after ``early``, against their handles' order); pages of 1 to 50 from
    an offset of 0 or more."""
    async with t.as_app(owner_engine) as conn:
        home, away = await county(conn, "Mombasa"), await county(conn, "Kilifi")
        a, b, c = await niche(conn, "a"), await niche(conn, "b"), await niche(conn, "c")
        caller = await developer(conn, "caller", county_code=home, liked=(a, b, c))
        two_away = await developer(conn, "twoaway", county_code=away, liked=(a, b))
        early = await developer(conn, "early", county_code=home, liked=(a,))  # opted in first, sorts first by handle
        late = await developer(conn, "late", county_code=home, liked=(b,))
        one_away = await developer(conn, "oneaway", county_code=away, liked=(c,))
        none_home = await developer(conn, "nonehome", county_code=home)
        assert await handle(conn, early) < await handle(conn, late)
        order = [two_away, late, early, one_away, none_home]
        assert await peer_ids(conn, caller) == order
        pages = [[row.user_id for row in await peers(conn, caller, 2, offset)] for offset in (0, 2, 4, 6)]
        assert pages == [order[:2], order[2:4], order[4:], []]
        assert [row.user_id for row in await peers(conn, caller, 1, 0)] == order[:1]
        await t.act(conn, caller)
        for limit, offset in ((0, 0), (51, 0), (None, 0), (20, -1), (20, None)):
            await refused(conn, PEERS, "a limit of 1 to 50", "22023", limit=limit, offset=offset)
        assert len(await peers(conn, caller, 50, 0)) == 5


async def test_a_block_hides_both_from_each_other_until_it_is_lifted(owner_engine: AsyncEngine) -> None:
    """Given two peers, When one blocks the other (either way), Then neither sees the other among peers nor gets the
    other's card; When the blocker lifts it, Then both see each other again."""
    async with t.as_app(owner_engine) as conn:
        shared = await niche(conn, "edtech")
        amina = await developer(conn, "amina", liked=(shared,))
        brian = await developer(conn, "brian", liked=(shared,))
        third = await developer(conn, "third", liked=(shared,))
        assert set(await peer_ids(conn, amina)) == {brian, third}
        either = "SELECT app_blocked_either_way(:a, :b)"
        for blocker, blocked in ((amina, brian), (brian, amina)):
            await t.act(conn, blocker)
            assert await t.run(conn, BLOCK, blocked=blocked) == 1
            for caller, answer in ((amina, True), (brian, True), (third, None)):  # only the two learn of it
                await t.act(conn, caller)
                assert await t.run(conn, either, a=amina, b=brian) is answer, caller
            assert await peer_ids(conn, amina) == [third]
            assert await peer_ids(conn, brian) == [third]
            assert await card(conn, amina, brian) == []
            assert await card(conn, brian, amina) == []
            await t.act(conn, blocker)
            assert await t.run(conn, UNBLOCK, blocked=blocked) == 1
            assert set(await peer_ids(conn, amina)) == {brian, third}
            assert [row.user_id for row in await card(conn, amina, brian)] == [brian]


async def test_the_peers_page_carries_the_card_fields_only(owner_engine: AsyncEngine) -> None:
    """Given a peer with a headline, a bio and a verification level, When the caller asks, Then each row is the seven
    card fields (user id, handle, headline, county code and name, shared niches, same county) and never the bio, the
    level, an email, a name or the opt-in time (it orders the page and is never returned)."""
    async with t.as_app(owner_engine) as conn:
        shared = await niche(conn, "civic")
        caller, peer = await developer(conn, "caller", liked=(shared,)), await developer(conn, "peer", liked=(shared,))
        await t.run(
            conn,
            "UPDATE developer_profiles SET headline = 'Builds USSD apps', bio = 'Private', verification_level = 'd2'"
            " WHERE user_id = :u",
            u=peer,
        )
        await t.act(conn, caller)
        result = await conn.execute(sa.text(PEERS), {"limit": 20, "offset": 0})
        assert list(result.keys()) == [
            "user_id",
            "handle",
            "headline",
            "county_code",
            "county_name",
            "shared_niches",
            "same_county",
        ]
        (row,) = result.all()
        assert (row.user_id, row.handle, row.headline) == (peer, await handle(conn, peer), "Builds USSD apps")
        signature = await t.run(conn, "SELECT pg_get_function_result('app_peers(integer, integer)'::regprocedure)")
        for private in ("bio", "verification", "email", "display_name", "opted_in"):
            assert private not in signature


async def test_demo_accounts_are_peers_of_demo_accounts_only(owner_engine: AsyncEngine) -> None:
    """Given real and demo developers sharing a niche, When each asks, Then a real caller sees real peers only and a
    demo caller demo peers only (the local demo shows its own people, as the quiz board)."""
    async with t.as_app(owner_engine) as conn:
        shared = await niche(conn, "demo")
        real, real_peer = (
            await developer(conn, "real", liked=(shared,)),
            await developer(conn, "realpeer", liked=(shared,)),
        )
        demo = await developer(conn, "demo", liked=(shared,), demo=True)
        demo_peer = await developer(conn, "demopeer", liked=(shared,), demo=True)
        assert await peer_ids(conn, real) == [real_peer]
        assert await peer_ids(conn, demo) == [demo_peer]


async def test_a_card_reaches_a_counterpart_or_a_peer_and_never_across_a_block(owner_engine: AsyncEngine) -> None:
    """Given a developer's peer, the counterpart of their pending invitation (no peer any more) and a stranger, When the
    developer asks for each one's card, Then the peer and the counterpart (both ways, even after the counterpart opts
    out) get one row of user id, handle and headline, and the stranger, oneself, a user who is no developer, anyone
    across a block, and every caller who is not a developer get none. A declined or withdrawn invitation makes nobody
    a counterpart: once the other opts out, neither a card nor an invitation (P0002). A thread does: its counterpart's
    card stays when they opt out, but a new invitation to them is refused. ``app_blocked_developers`` lists the
    caller's own blocks with the handles, never another's."""
    async with t.as_app(owner_engine) as conn:
        shared = await niche(conn, "logistics")
        dev = await developer(conn, "dev", liked=(shared,))
        peer = await developer(conn, "peer", liked=(shared,))
        counterpart = await developer(conn, "counterpart", liked=(shared,))  # a peer when invited, then no more
        stranger = await developer(conn, "stranger")
        member, admin = await org_only(conn), await developer(conn, "admin", staff="admin")
        await invite(conn, dev, counterpart, await problem(conn, dev))
        await t.as_owner(conn)
        await t.run(conn, "DELETE FROM developer_niches WHERE user_id = :u", u=counterpart)
        assert [row.user_id for row in await card(conn, dev, peer)] == [peer]
        assert [tuple(row) for row in await card(conn, dev, counterpart)] == [
            (counterpart, await handle(conn, counterpart), None)
        ]
        assert [row.user_id for row in await card(conn, counterpart, dev)] == [dev]  # not a peer: the invitation
        await t.as_owner(conn)
        await t.run(conn, "UPDATE developer_profiles SET peers_visible = false WHERE user_id = :u", u=counterpart)
        assert [row.user_id for row in await card(conn, dev, counterpart)] == [counterpart]  # still pending
        assert await card(conn, dev, stranger) == []
        opt_out = "UPDATE developer_profiles SET peers_visible = false WHERE user_id = :u"
        for decision in ("decline", "withdraw"):  # a decided invitation counts for nothing
            former = await developer(conn, f"former{decision}", liked=(shared,))
            invitation = await invite(conn, dev, former, await problem(conn, dev))
            await decide(conn, former if decision == "decline" else dev, invitation, decision)
            await t.as_owner(conn)
            await t.run(conn, opt_out, u=former)
            assert await card(conn, dev, former) == []
            assert await card(conn, former, dev) == []
            params = invitation_params(dev, former, await problem(conn, dev))
            await t.act(conn, dev)
            await refused(conn, INVITE, NOT_REACHABLE, "P0002", **params)
        teammate = await developer(conn, "teammate", liked=(shared,))  # a thread does count, for the card only
        await team(conn, dev, teammate, await problem(conn, dev))
        await t.as_owner(conn)
        await t.run(conn, opt_out, u=teammate)
        assert [row.user_id for row in await card(conn, dev, teammate)] == [teammate]
        assert [row.user_id for row in await card(conn, teammate, dev)] == [dev]
        params = invitation_params(dev, teammate, await problem(conn, dev))
        await t.act(conn, dev)
        await refused(conn, INVITE, NOT_REACHABLE, "P0002", **params)
        hidden = await developer(conn, "hidden", peers=False, liked=(shared,))  # not opted in: no peer's card
        assert await card(conn, hidden, peer) == []
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET staff_role = 'admin', totp_enabled_at = now() WHERE id = :u", u=counterpart)
        assert await card(conn, counterpart, dev) == []  # staff now: no card, not even a counterpart's
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET staff_role = NULL WHERE id = :u", u=counterpart)
        assert await card(conn, dev, dev) == []
        assert await card(conn, dev, member) == []
        for caller in (member, admin, None):
            assert await card(conn, caller, dev) == [], caller
        await t.act(conn, counterpart)
        assert await t.run(conn, BLOCK, blocked=dev) == 2  # the block and the pending invitation it ended
        assert await t.run(conn, "SELECT status FROM team_invitations WHERE to_user_id = :u", u=counterpart) == "ended"
        assert await card(conn, dev, counterpart) == []
        assert await card(conn, counterpart, dev) == []
        await t.act(conn, counterpart)
        blocks = (await conn.execute(sa.text("SELECT user_id, handle::text FROM app_blocked_developers()"))).all()
        assert [tuple(row) for row in blocks] == [(dev, await handle(conn, dev))]
        await t.act(conn, dev)  # the blocked side reads no block
        assert (await conn.execute(sa.text("SELECT count(*) FROM app_blocked_developers()"))).scalar_one() == 0
        assert await t.run(conn, "SELECT count(*) FROM developer_blocks") == 0
        await t.act(conn, member)
        await refused(conn, "SELECT * FROM app_blocked_developers()", "developers only", "42501")
