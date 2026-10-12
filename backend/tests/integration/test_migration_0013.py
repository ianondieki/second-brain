"""Revision 0013 (P27-M; REQ-ENG-15, D-68; REQ-PROV-06; REQ-ENG-13, D-70; REQ-DEV-04): the database half of team triage,
the prior-knowledge declaration, calendar feeds and the D3 references.

- Assignments: an owner, admin, reviewer or signatory assigns, as themselves, an engagement of their organisation to an
  active owner, admin, reviewer or signatory of it; one live assignment per engagement (a second is refused by the
  partial unique index); a close is the database's time, once, and nothing else of a row ever changes; a viewer, a
  finance member, the developer and another organisation's member cannot assign; members read every row (viewers
  included) and nobody else does.
- Recommendations: one per member and engagement, upserted by the member as themselves while a triage member, changing
  ``updated_at`` (the database's); a member withdraws their own and nobody else's; the note is one line of 1 to 200
  characters or none; the developer and another organisation read none.
- The declaration: refused before the organisation's first Tier-2 view; then one per engagement, by an owner, admin or
  signatory naming the engagement's organisation, proposal and version, with the window, its first view and its time
  the database's (``app_prior_knowledge_window``: the 10th Kenyan business day after the first view's Nairobi day,
  holidays included, as ``bridge.engagements.calendar.add_business_days``); refused once the Nairobi day on the shared
  clock is past the closing day and for evidence dated after today; append-only for every role, the owner included;
  read by the engagement's readers (the developer, the members, staff admin), never by another organisation.
- Calendar feeds: one live feed per user and per user and organisation; rotation revokes (the database's time) and a
  revoked feed never changes; an organisation's feed only for a member of it; ``app_calendar_feed_lookup`` answers the
  live feed of an active user who is still a member of its organisation and nothing for a revoked, unknown or
  wrong-length hash; ``app_calendar_feed_touch`` stamps the live feed, a bound caller's own only.
- D3: the developer sets their own references and dismissal; an invalid GitHub login, a blank or control-character
  reference are refused by the CHECKs; another developer's profile is untouched.

Every test runs in one rolled-back transaction (``tracker.as_app``); the downgrade's refusal is in
``test_migration_0013_downgrade.py``.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.engagements.calendar import add_business_days, local_date
from bridge.ids import uuid7
from tests.integration.engagements import tracker as t

ASSIGN = (
    "INSERT INTO engagement_assignments (id, engagement_id, org_id, assignee_user_id, assigned_by)"
    " VALUES (:id, :e, :org, :assignee, :by)"
)
RECOMMEND = (
    "INSERT INTO engagement_recommendations (id, engagement_id, org_id, member_user_id, stance, note)"
    " VALUES (:id, :e, :org, :member, CAST(:stance AS recommendation_stance), :note)"
    " ON CONFLICT (engagement_id, member_user_id) DO UPDATE SET stance = EXCLUDED.stance, note = EXCLUDED.note"
)
DECLARE = (
    "INSERT INTO prior_knowledge_declarations (id, engagement_id, org_id, proposal_id, version_id, declared_by,"
    " evidence_sha256, evidence_title, evidence_dated_on) VALUES (:id, :e, :org, :p, :v, :by, :sha, :title, :dated)"
)
FEED = "INSERT INTO calendar_feeds (id, user_id, org_id, token_hash) VALUES (:id, :user, :org, :hash)"
VIEW = (
    "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id, render_kind,"
    " fingerprint_seed) VALUES (:id, :p, :v, :owner, :viewer, :org, 'html', :seed)"
)
WINDOW = "SELECT first_tier2_view_at, window_closes_on FROM app_prior_knowledge_window(:e)"
LOOKUP = "SELECT feed_id, user_id, org_id FROM app_calendar_feed_lookup(:hash)"
HIDDEN = "no engagement of the caller's with that id"
RLS = "row-level security"
DENIED = "permission denied"
EVIDENCE = hashlib.sha256(b"internal pilot memo, 2026-03-02").digest()


async def scene(conn: AsyncConnection) -> tuple[t.Parties, UUID]:
    """The tracker's parties and the developer's engagement with the organisation (SUBMITTED), as bridge_app."""
    p = await t.parties(conn)
    await t.act(conn, p.developer)
    return p, await t.engage(conn, p)


def assign(p: t.Parties, engagement: UUID, assignee: UUID, by: UUID, org: UUID | None = None) -> dict[str, object]:
    return {"id": uuid7(), "e": engagement, "org": org or p.org, "assignee": assignee, "by": by}


def recommend(
    p: t.Parties, engagement: UUID, member: UUID, stance: str = "pursue", note: str | None = "Worth a pilot"
) -> dict[str, object]:
    return {"id": uuid7(), "e": engagement, "org": p.org, "member": member, "stance": stance, "note": note}


def declaration(p: t.Parties, engagement: UUID, by: UUID, **overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "id": uuid7(),
        "e": engagement,
        "org": p.org,
        "p": p.proposal,
        "v": p.version,
        "by": by,
        "sha": EVIDENCE,
        "title": "Internal pilot memo",
        "dated": date(2026, 3, 2),
    }
    return params | overrides


async def count(conn: AsyncConnection, table: str, engagement: UUID) -> int:
    return int(await t.run(conn, f"SELECT count(*) FROM {table} WHERE engagement_id = :e", e=engagement))


async def view(conn: AsyncConnection, p: t.Parties, viewer: UUID) -> datetime:
    """As the owner: the organisation's Tier-2 view of the proposal by ``viewer`` (its time is the database's now())."""
    await t.as_owner(conn)
    view_id = uuid7()
    await t.run(
        conn,
        VIEW,
        id=view_id,
        p=p.proposal,
        v=p.version,
        owner=p.developer,
        viewer=viewer,
        org=p.org,
        seed=uuid7().bytes,
    )
    started = await t.run(conn, "SELECT started_at FROM document_views WHERE id = :id", id=view_id)
    assert isinstance(started, datetime)
    return started


async def holidays(conn: AsyncConnection) -> frozenset[date]:
    found = await conn.execute(sa.text("SELECT observed_on FROM holidays WHERE country = 'KE'"))
    return frozenset(found.scalars())


async def move_clock(conn: AsyncConnection, days: int) -> None:
    """As the owner, inside the test's transaction: the shared clock ``days`` ahead of the database clock."""
    await t.as_owner(conn)
    await t.run(conn, "UPDATE test_clock SET enabled = true, clock_offset = make_interval(days => :d)", d=days)


# --- engagement_assignments ----------------------------------------------------------------------------------------


async def test_one_live_assignment_per_engagement_closed_once_by_the_database(owner_engine: AsyncEngine) -> None:
    """Given an engagement, When a reviewer assigns it to the signatory, Then the database times it; a second live
    assignment is refused by ``uq_engagement_assignments_live``; closing the live row sets ``unassigned_at`` to the
    shared clock whatever was sent, after which the next assignment is accepted; a closed row stays closed and no
    assignment's keys, people or time ever change, for the owner too."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await t.act(conn, p.reviewer, p.org)
        first = assign(p, engagement, p.signatory, p.reviewer)
        await t.run(conn, ASSIGN, **first)
        assigned_at = await t.run(conn, "SELECT assigned_at FROM engagement_assignments WHERE id = :id", id=first["id"])
        assert assigned_at is not None
        await t.expect(conn, ASSIGN, "uq_engagement_assignments_live", **assign(p, engagement, p.owner, p.reviewer))
        closed = await t.rowcount(
            conn,
            "UPDATE engagement_assignments SET unassigned_at = '2000-01-01' WHERE engagement_id = :e"
            " AND unassigned_at IS NULL",
            e=engagement,
        )
        assert closed == 1
        unassigned_at = await t.run(
            conn, "SELECT unassigned_at FROM engagement_assignments WHERE id = :id", id=first["id"]
        )
        assert unassigned_at >= assigned_at  # the shared clock, never the 2000 sent
        await t.run(conn, ASSIGN, **assign(p, engagement, p.owner, p.reviewer))
        assert await count(conn, "engagement_assignments", engagement) == 2
        # bridge_app's UPDATE policy reaches live rows only; the guard refuses every role, the owner included
        again = "UPDATE engagement_assignments SET unassigned_at = now() WHERE id = :id"
        assert await t.rowcount(conn, again, id=first["id"]) == 0
        await t.as_owner(conn)
        await t.expect(conn, again, "a closed assignment stays closed", id=first["id"])
        await t.expect(
            conn,
            "UPDATE engagement_assignments SET assignee_user_id = :u WHERE engagement_id = :e"
            " AND unassigned_at IS NULL",
            "never change",
            u=p.signatory,
            e=engagement,
        )
        await t.act(conn, p.reviewer, p.org)
        await t.expect(
            conn,
            "UPDATE engagement_assignments SET assignee_user_id = :u WHERE engagement_id = :e",
            DENIED,
            u=p.signatory,
            e=engagement,
        )
        await t.expect(conn, "DELETE FROM engagement_assignments WHERE engagement_id = :e", DENIED, e=engagement)


async def test_only_triage_members_assign_and_only_to_triage_members(owner_engine: AsyncEngine) -> None:
    """Given an engagement, Then the owner, admin, reviewer and signatory may assign (as themselves); a viewer and a
    finance member are refused by RLS; the developer, who reads the engagement but not the organisation's roster, gets
    the same refusal whoever they name (the guard reads the roster under the writer's RLS: no oracle of who is a
    triage member); another organisation's member is told there is no such engagement; an assigner who is not the
    caller is refused; the assignee must be an active owner, admin, reviewer or signatory of the engagement's
    organisation (a viewer, the developer, a removed member are refused, every role); the organisation is the
    engagement's."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        for member in (p.owner, p.signatory, p.reviewer):  # each assigns once (closing the live row first)
            await t.act(conn, member, p.org)
            await t.run(
                conn,
                "UPDATE engagement_assignments SET unassigned_at = now() WHERE engagement_id = :e"
                " AND unassigned_at IS NULL",
                e=engagement,
            )
            await t.run(conn, ASSIGN, **assign(p, engagement, member, member))  # self-assignment included
        for member in (p.viewer, p.finance):
            await t.act(conn, member, p.org)
            await t.expect(conn, ASSIGN, RLS, **assign(p, engagement, p.reviewer, member))
        await t.act(conn, p.developer)  # reads the engagement, never the roster: one refusal, whoever is named
        for named in (p.reviewer, p.signatory, p.viewer, p.outsider):
            await t.expect(conn, ASSIGN, "the assignee must be", **assign(p, engagement, named, p.developer))
        await t.act(conn, p.other_member, p.other_org)
        await t.expect(conn, ASSIGN, HIDDEN, **assign(p, engagement, p.reviewer, p.other_member))
        await t.act(conn, p.reviewer, p.org)
        await t.run(
            conn, "UPDATE engagement_assignments SET unassigned_at = now() WHERE engagement_id = :e", e=engagement
        )
        await t.expect(conn, ASSIGN, RLS, **assign(p, engagement, p.reviewer, p.signatory))  # not the caller
        for assignee in (p.viewer, p.finance, p.developer, p.other_member):
            await t.expect(conn, ASSIGN, "the assignee must be", **assign(p, engagement, assignee, p.reviewer))
        await t.as_owner(conn)
        await t.run(conn, "UPDATE memberships SET status = 'removed' WHERE user_id = :u", u=p.signatory)
        await t.expect(conn, ASSIGN, "the assignee must be", **assign(p, engagement, p.signatory, p.owner))
        await t.expect(
            conn, ASSIGN, "the organisation is the engagement's", **assign(p, engagement, p.owner, p.owner, p.other_org)
        )


async def test_assignments_are_read_by_the_organisations_members_only(owner_engine: AsyncEngine) -> None:
    """Given an assignment, Then every member reads it (a viewer and finance too), while the developer, another
    organisation's member (also with a forged organisation context), an outside developer and staff admin read none
    (D-68: the organisation's own)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await t.act(conn, p.signatory, p.org)
        await t.run(conn, ASSIGN, **assign(p, engagement, p.reviewer, p.signatory))
        for member in (p.owner, p.reviewer, p.finance, p.viewer):
            for org in (p.org, None):
                await t.act(conn, member, org)
                assert await count(conn, "engagement_assignments", engagement) == 1
        for reader, org in (
            (p.developer, None),
            (p.developer, p.org),
            (p.other_member, p.other_org),
            (p.other_member, p.org),  # a forged organisation context
            (p.outsider, None),
            (p.staff, None),
        ):
            await t.act(conn, reader, org)
            assert await count(conn, "engagement_assignments", engagement) == 0, reader


# --- engagement_recommendations ------------------------------------------------------------------------------------


async def test_a_member_recommends_once_upserts_and_withdraws_only_their_own(owner_engine: AsyncEngine) -> None:
    """Given an engagement, When the reviewer recommends and then recommends again, Then one row holds the latest
    stance and note and ``updated_at`` moved (the database's); another member neither changes nor deletes it; the
    reviewer withdraws it; a viewer, finance and the developer cannot recommend (the guard: not a triage member of the
    organisation), nor anyone for someone else (the policy), nor another organisation's member (no such engagement)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await t.act(conn, p.reviewer, p.org)
        await t.run(conn, RECOMMEND, **recommend(p, engagement, p.reviewer))
        mine = (
            "SELECT stance::text, note, created_at, updated_at FROM engagement_recommendations"
            " WHERE member_user_id = :m"
        )
        before = (await conn.execute(sa.text(mine), {"m": p.reviewer})).one()
        await t.run(conn, RECOMMEND, **recommend(p, engagement, p.reviewer, "discuss", None))
        after = (await conn.execute(sa.text(mine), {"m": p.reviewer})).one()
        assert (after.stance, after.note, after.created_at) == ("discuss", None, before.created_at)
        assert after.updated_at > before.updated_at
        assert await count(conn, "engagement_recommendations", engagement) == 1
        await t.act(conn, p.signatory, p.org)
        await t.run(conn, RECOMMEND, **recommend(p, engagement, p.signatory, "pass", "Not this quarter"))
        others = "WHERE engagement_id = :e AND member_user_id = :m"
        assert (
            await t.rowcount(
                conn, f"UPDATE engagement_recommendations SET stance = 'pass' {others}", e=engagement, m=p.reviewer
            )
            == 0
        )
        assert (
            await t.rowcount(conn, f"DELETE FROM engagement_recommendations {others}", e=engagement, m=p.reviewer) == 0
        )
        await t.act(conn, p.reviewer, p.org)
        assert (
            await t.rowcount(conn, f"DELETE FROM engagement_recommendations {others}", e=engagement, m=p.reviewer) == 1
        )
        assert await count(conn, "engagement_recommendations", engagement) == 1  # the signatory's stays
        await t.expect(conn, RECOMMEND, RLS, **recommend(p, engagement, p.owner))  # for someone else
        # the guard (BEFORE INSERT) refuses a member who is not a triage member before the policy would
        for member, org in ((p.viewer, p.org), (p.finance, p.org), (p.developer, None)):
            await t.act(conn, member, org)
            await t.expect(conn, RECOMMEND, "the member must be", **recommend(p, engagement, member))
        await t.act(conn, p.other_member, p.other_org)
        await t.expect(conn, RECOMMEND, HIDDEN, **recommend(p, engagement, p.other_member))
        await t.as_owner(conn)
        await t.expect(
            conn,
            "UPDATE engagement_recommendations SET member_user_id = :m WHERE engagement_id = :e",
            "never change",
            m=p.owner,
            e=engagement,
        )
        await t.expect(conn, RECOMMEND, "the member must be", **recommend(p, engagement, p.viewer))


async def test_a_note_is_one_line_of_at_most_200_characters(owner_engine: AsyncEngine) -> None:
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await t.act(conn, p.reviewer, p.org)
        for note in ("x" * 201, "   ", "", "Line one\nline two", "tab\there"):
            await t.expect(
                conn,
                RECOMMEND,
                "ck_engagement_recommendations_note_valid",
                **recommend(p, engagement, p.reviewer, note=note),
            )
        await t.run(conn, RECOMMEND, **recommend(p, engagement, p.reviewer, note="x" * 200))
        await t.run(conn, RECOMMEND, **recommend(p, engagement, p.reviewer, note=None))


async def test_recommendations_are_never_read_outside_the_organisation(owner_engine: AsyncEngine) -> None:
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await t.act(conn, p.reviewer, p.org)
        await t.run(conn, RECOMMEND, **recommend(p, engagement, p.reviewer, "pass", "Already in progress internally"))
        for member in (p.owner, p.signatory, p.finance, p.viewer):
            await t.act(conn, member, p.org)
            assert await count(conn, "engagement_recommendations", engagement) == 1
        for reader, org in (
            (p.developer, None),
            (p.other_member, p.other_org),
            (p.other_member, p.org),
            (p.staff, None),
        ):
            await t.act(conn, reader, org)
            assert await count(conn, "engagement_recommendations", engagement) == 0, reader


# --- prior_knowledge_declarations ----------------------------------------------------------------------------------


async def test_a_declaration_needs_a_tier2_view_and_takes_the_databases_window(owner_engine: AsyncEngine) -> None:
    """Given an engagement whose proposal the organisation has not viewed, When its signatory declares, Then the
    database refuses (no Tier-2 view yet) and the window reads NULL; after a reviewer's view, the window is the 10th
    Kenyan business day after the view's Nairobi day (``add_business_days`` on the same holidays), the declaration is
    accepted with the view, the window and the time the database's, and a second declaration is refused; bridge_app
    cannot send the database's columns."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await t.act(conn, p.signatory, p.org)
        assert (await conn.execute(sa.text(WINDOW), {"e": engagement})).one() == (None, None)
        await t.expect(
            conn, DECLARE, "has not viewed the proposal's Tier 2 yet", **declaration(p, engagement, p.signatory)
        )
        first = await view(conn, p, p.reviewer)
        await view(conn, p, p.signatory)  # another member's view: the first stays the first
        closes = add_business_days(local_date(first), 10, await holidays(conn))
        await t.act(conn, p.signatory, p.org)
        assert (await conn.execute(sa.text(WINDOW), {"e": engagement})).one() == (first, closes)
        params = declaration(p, engagement, p.signatory)
        await t.run(conn, DECLARE, **params)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT first_tier2_view_at, window_closes_on, declared_at, evidence_sha256, evidence_title"
                    " FROM prior_knowledge_declarations WHERE id = :id"
                ),
                {"id": params["id"]},
            )
        ).one()
        assert (row.first_tier2_view_at, row.window_closes_on) == (first, closes)
        assert row.declared_at >= first
        assert (bytes(row.evidence_sha256), row.evidence_title) == (EVIDENCE, "Internal pilot memo")
        await t.expect(
            conn,
            DECLARE,
            "uq_prior_knowledge_declarations_engagement_id",
            **declaration(p, engagement, p.signatory),
        )
        for column, value in (("declared_at", "now()"), ("window_closes_on", "'2099-01-01'")):
            await t.expect(
                conn,
                f"INSERT INTO prior_knowledge_declarations (id, engagement_id, {column}) VALUES (:id, :e, {value})",
                DENIED,
                id=uuid7(),
                e=engagement,
            )


async def test_the_window_closes_after_ten_kenyan_business_days(owner_engine: AsyncEngine) -> None:
    """Given the organisation's first Tier-2 view and a holiday three business days later, Then the window closes on
    the 10th business day after the view's Nairobi day counting the holiday out; with the shared clock on the day after
    it the declaration is refused (window closed), evidence dated after today is refused, and on the closing day itself
    it is accepted, dated that day."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        first = await view(conn, p, p.reviewer)
        start, known = local_date(first), await holidays(conn)
        holiday = add_business_days(start, 3, known)
        await t.run(
            conn,
            "INSERT INTO holidays (id, country, holiday_on, observed_on, name)"
            " VALUES (:id, 'KE', :d, :d, 'P27 test holiday')",
            id=uuid7(),
            d=holiday,
        )
        closes = add_business_days(start, 10, known | {holiday})
        assert closes > add_business_days(start, 10, known)  # the holiday moved it
        await t.act(conn, p.signatory, p.org)
        assert (await conn.execute(sa.text(WINDOW), {"e": engagement})).one() == (first, closes)
        today = await t.run(conn, "SELECT (now() AT TIME ZONE 'Africa/Nairobi')::date")
        await move_clock(conn, (closes - today).days + 1)
        await t.act(conn, p.signatory, p.org)
        assert await t.run(conn, "SELECT app_nairobi_today()") == closes + timedelta(days=1)
        await t.expect(
            conn,
            DECLARE,
            f"the declaration window closed on {closes.isoformat()}",
            **declaration(p, engagement, p.signatory),
        )
        await move_clock(conn, (closes - today).days)
        await t.act(conn, p.signatory, p.org)
        assert await t.run(conn, "SELECT app_nairobi_today()") == closes
        await t.expect(
            conn,
            DECLARE,
            "the evidence is dated after today",
            **declaration(p, engagement, p.signatory, dated=closes + timedelta(days=1)),
        )
        params = declaration(p, engagement, p.signatory, dated=closes)
        await t.run(conn, DECLARE, **params)
        declared = await t.run(
            conn,
            "SELECT (declared_at AT TIME ZONE 'Africa/Nairobi')::date FROM prior_knowledge_declarations WHERE id = :id",
            id=params["id"],
        )
        assert declared == closes


async def test_only_a_declarer_of_the_engagements_organisation_declares_its_own_engagement(
    owner_engine: AsyncEngine,
) -> None:
    """Given a viewed proposal, Then a reviewer, a viewer, a finance member and the developer are refused by RLS,
    another organisation's member is told there is no such engagement, a declarer cannot declare for someone else, and
    the organisation, proposal and version must be the engagement's (every role); the owner, an admin and the signatory
    may each declare (one at a time)."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await view(conn, p, p.reviewer)
        for member, org in ((p.reviewer, p.org), (p.viewer, p.org), (p.finance, p.org), (p.developer, None)):
            await t.act(conn, member, org)
            await t.expect(conn, DECLARE, RLS, **declaration(p, engagement, member))
        await t.act(conn, p.other_member, p.other_org)
        await t.expect(conn, DECLARE, HIDDEN, **declaration(p, engagement, p.other_member, org=p.other_org))
        await t.act(conn, p.signatory, p.org)
        await t.expect(conn, DECLARE, RLS, **declaration(p, engagement, p.owner))  # not the caller
        await t.as_owner(conn)
        other_version = uuid7()
        await t.run(
            conn,
            "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask,"
            " problem_statement, summary) SELECT :id, proposal_id, 2, title, niche_id, maturity, ask,"
            " problem_statement, summary FROM proposal_versions WHERE id = :v",
            id=other_version,
            v=p.version,
        )
        await t.act(conn, p.signatory, p.org)
        mismatch = "the organisation, proposal and version are the engagement's"
        await t.expect(conn, DECLARE, mismatch, **declaration(p, engagement, p.signatory, v=other_version))
        await t.as_owner(conn)  # the owner's insert is checked too
        await t.expect(conn, DECLARE, mismatch, **declaration(p, engagement, p.signatory, org=p.other_org))
        for declarer in (p.owner, p.signatory):
            await t.act(conn, declarer, p.org)
            savepoint = await conn.begin_nested()
            await t.run(conn, DECLARE, **declaration(p, engagement, declarer))
            assert await count(conn, "prior_knowledge_declarations", engagement) == 1
            await savepoint.rollback()


async def test_a_declaration_is_append_only_for_every_role(owner_engine: AsyncEngine) -> None:
    """Given a declaration, Then bridge_app holds no UPDATE or DELETE of it, and the triggers refuse UPDATE, DELETE and
    TRUNCATE to the owner too."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await view(conn, p, p.reviewer)
        await t.act(conn, p.signatory, p.org)
        await t.run(conn, DECLARE, **declaration(p, engagement, p.signatory))
        update = "UPDATE prior_knowledge_declarations SET evidence_title = 'Changed' WHERE engagement_id = :e"
        delete = "DELETE FROM prior_knowledge_declarations WHERE engagement_id = :e"
        for statement in (update, delete):
            await t.expect(conn, statement, DENIED, e=engagement)
        await t.as_owner(conn)
        for statement in (update, delete):
            await t.expect(conn, statement, "append-only evidence", e=engagement)
        await t.expect(conn, "TRUNCATE prior_knowledge_declarations", "append-only evidence")
        assert await count(conn, "prior_knowledge_declarations", engagement) == 1


async def test_a_declaration_is_read_by_the_engagements_readers_only(owner_engine: AsyncEngine) -> None:
    """Given a declaration, Then the developer (the proposal's owner), every member and staff admin read it and its
    window; another organisation's member (also with a forged organisation context) and an outside developer read
    neither."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await view(conn, p, p.reviewer)
        await t.act(conn, p.signatory, p.org)
        await t.run(conn, DECLARE, **declaration(p, engagement, p.signatory))
        readers = ((p.developer, None), (p.viewer, p.org), (p.finance, p.org), (p.reviewer, None), (p.staff, None))
        for reader, org in readers:
            await t.act(conn, reader, org)
            assert await count(conn, "prior_knowledge_declarations", engagement) == 1, reader
            assert len((await conn.execute(sa.text(WINDOW), {"e": engagement})).all()) == 1, reader
        outsiders: tuple[tuple[UUID | None, UUID | None], ...] = (
            (p.other_member, p.other_org),
            (p.other_member, p.org),  # a forged organisation context
            (p.outsider, None),
            (None, None),  # no user bound
        )
        for outsider, context in outsiders:
            await t.act(conn, outsider, context)
            assert await count(conn, "prior_knowledge_declarations", engagement) == 0, outsider
            assert (await conn.execute(sa.text(WINDOW), {"e": engagement})).all() == [], outsider


async def test_the_evidence_is_a_sha256_and_a_one_line_title(owner_engine: AsyncEngine) -> None:
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await view(conn, p, p.reviewer)
        await t.act(conn, p.signatory, p.org)
        for overrides, constraint in (
            ({"sha": EVIDENCE[:31]}, "ck_prior_knowledge_declarations_evidence_sha256"),
            ({"sha": EVIDENCE + b"\x00"}, "ck_prior_knowledge_declarations_evidence_sha256"),
            ({"title": "x" * 201}, "ck_prior_knowledge_declarations_evidence_title_valid"),
            ({"title": "  "}, "ck_prior_knowledge_declarations_evidence_title_valid"),
            ({"title": "Memo\nsecond line"}, "ck_prior_knowledge_declarations_evidence_title_valid"),
        ):
            await t.expect(conn, DECLARE, constraint, **declaration(p, engagement, p.signatory, **overrides))
        await t.run(conn, DECLARE, **declaration(p, engagement, p.signatory, title="x" * 200))


# --- calendar_feeds ------------------------------------------------------------------------------------------------


def token_hash(label: str) -> bytes:
    return hashlib.sha256(f"{label}-{uuid7()}".encode()).digest()


def feed(user: UUID, org: UUID | None, hashed: bytes) -> dict[str, object]:
    return {"id": uuid7(), "user": user, "org": org, "hash": hashed}


async def test_one_live_feed_per_user_and_organisation_and_rotation_revokes(owner_engine: AsyncEngine) -> None:
    """Given a developer and a member, Then each has at most one live personal feed and one live feed per organisation
    they are a member of; rotation revokes the live feed (the database's time) and the next is accepted; a revoked feed
    never changes again; nobody creates a feed for someone else or for an organisation they are not a member of."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        old, new = token_hash("old"), token_hash("new")
        await t.run(conn, FEED, **feed(p.developer, None, old))
        await t.expect(conn, FEED, "uq_calendar_feeds_live_personal", **feed(p.developer, None, new))
        revoke = (
            "UPDATE calendar_feeds SET revoked_at = '2000-01-01' WHERE user_id = :u"
            " AND org_id IS NOT DISTINCT FROM CAST(:o AS uuid) AND revoked_at IS NULL"
        )
        assert await t.rowcount(conn, revoke, u=p.developer, o=None) == 1
        revoked = await t.run(conn, "SELECT revoked_at > created_at FROM calendar_feeds WHERE token_hash = :h", h=old)
        assert revoked is True  # the shared clock, never the 2000 sent
        await t.run(conn, FEED, **feed(p.developer, None, new))
        await t.expect(
            conn,
            "UPDATE calendar_feeds SET revoked_at = now() WHERE token_hash = :h",
            "a revoked feed never changes",
            h=old,
        )
        await t.expect(conn, FEED, RLS, **feed(p.developer, p.org, token_hash("not-a-member")))
        await t.expect(conn, FEED, RLS, **feed(p.owner, None, token_hash("someone-else")))
        await t.expect(conn, "UPDATE calendar_feeds SET last_fetched_at = now()", DENIED)
        await t.expect(conn, "DELETE FROM calendar_feeds", DENIED)
        await t.act(conn, p.owner, p.org)
        await t.run(conn, FEED, **feed(p.owner, None, token_hash("owner-personal")))
        await t.run(conn, FEED, **feed(p.owner, p.org, token_hash("owner-org")))
        await t.expect(conn, FEED, "uq_calendar_feeds_live_org", **feed(p.owner, p.org, token_hash("owner-org-2")))
        assert await t.run(conn, "SELECT count(*) FROM calendar_feeds") == 2  # the owner's own only
        await t.act(conn, p.signatory, p.org)  # no feed yet: only the token's uniqueness is at stake
        await t.expect(conn, FEED, "uq_calendar_feeds_token_hash", **feed(p.signatory, None, new))
        await t.as_owner(conn)
        await t.expect(
            conn,
            "UPDATE calendar_feeds SET token_hash = :h WHERE user_id = :u",
            "never change",
            h=token_hash("swap"),
            u=p.owner,
        )


async def test_the_lookup_answers_only_a_live_feed_of_an_active_member(owner_engine: AsyncEngine) -> None:
    """Given feeds, Then ``app_calendar_feed_lookup`` answers a session with no user bound with the live feed's id, user
    and organisation; nothing for an unknown, revoked or wrong-length hash, for a suspended user, or for an
    organisation's feed once its user is no longer a member; ``app_calendar_feed_touch`` stamps a live feed (a bound
    caller's own only) and never a revoked one."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        personal, org_feed, revoked = token_hash("personal"), token_hash("org"), token_hash("revoked")
        await t.act(conn, p.signatory, p.org)
        mine = feed(p.signatory, None, revoked)
        await t.run(conn, FEED, **mine)
        await t.run(conn, "UPDATE calendar_feeds SET revoked_at = now() WHERE id = :id", id=mine["id"])
        personal_feed, member_feed = feed(p.signatory, None, personal), feed(p.signatory, p.org, org_feed)
        await t.run(conn, FEED, **personal_feed)
        await t.run(conn, FEED, **member_feed)
        await t.act(conn, None)  # the unauthenticated read: no user bound
        found = (await conn.execute(sa.text(LOOKUP), {"hash": personal})).one()
        assert tuple(found) == (personal_feed["id"], p.signatory, None)
        found = (await conn.execute(sa.text(LOOKUP), {"hash": org_feed})).one()
        assert tuple(found) == (member_feed["id"], p.signatory, p.org)
        for unknown in (revoked, token_hash("unknown"), personal[:31], b""):
            assert (await conn.execute(sa.text(LOOKUP), {"hash": unknown})).all() == []
        touch = "SELECT app_calendar_feed_touch(:id)"
        assert await t.run(conn, touch, id=personal_feed["id"]) is True
        assert await t.run(conn, touch, id=mine["id"]) is False  # revoked
        await t.act(conn, p.owner, p.org)
        assert await t.run(conn, touch, id=member_feed["id"]) is False  # another user's
        await t.act(conn, p.signatory, p.org)
        assert await t.run(conn, touch, id=member_feed["id"]) is True  # the caller's own
        stamped = "SELECT count(*) FROM calendar_feeds WHERE last_fetched_at IS NOT NULL"
        assert await t.run(conn, stamped) == 2
        await t.as_owner(conn)
        await t.run(
            conn, "UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u", o=p.org, u=p.signatory
        )
        await t.act(conn, None)
        assert (await conn.execute(sa.text(LOOKUP), {"hash": org_feed})).all() == []  # no longer a member
        assert len((await conn.execute(sa.text(LOOKUP), {"hash": personal})).all()) == 1
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=p.signatory)
        await t.act(conn, None)
        assert (await conn.execute(sa.text(LOOKUP), {"hash": personal})).all() == []  # a suspended user


# --- developer_profiles: D3 ----------------------------------------------------------------------------------------


async def test_the_d3_references_are_the_developers_own_and_well_formed(owner_engine: AsyncEngine) -> None:
    """Given a developer, Then they set their GitHub login, KECOBO and KIPI references and dismiss the nudge on their
    own profile; GitHub's rule refuses a leading, trailing or double hyphen, an underscore and a 40-character login;
    a blank or control-character reference and a 41-character one are refused; another developer's profile is
    untouched."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        own = "WHERE user_id = :u"
        updated = await t.rowcount(
            conn,
            "UPDATE developer_profiles SET github_login = 'octo-cat-9', kecobo_number = 'KECOBO/LIT/2026/0042',"
            f" kipi_number = 'KE/U/2026/000123', ip_nudge_dismissed_at = now() {own}",
            u=p.developer,
        )
        assert updated == 1
        for login in ("-octo", "octo-", "oc--to", "octo_cat", "octo cat"):
            await t.expect(
                conn,
                f"UPDATE developer_profiles SET github_login = :v {own}",
                "ck_developer_profiles_github_login_valid",
                v=login,
                u=p.developer,
            )
        await t.expect(
            conn, f"UPDATE developer_profiles SET github_login = :v {own}", "too long", v="a" * 40, u=p.developer
        )
        await t.run(conn, f"UPDATE developer_profiles SET github_login = :v {own}", v="a" * 39, u=p.developer)
        for column in ("kecobo_number", "kipi_number"):
            for value in ("   ", "KIPI\n123", "KIPI\x07"):
                await t.expect(
                    conn,
                    f"UPDATE developer_profiles SET {column} = :v {own}",
                    f"ck_developer_profiles_{column}_valid",
                    v=value,
                    u=p.developer,
                )
            await t.expect(
                conn, f"UPDATE developer_profiles SET {column} = :v {own}", "too long", v="K" * 41, u=p.developer
            )
        assert await t.rowcount(conn, f"UPDATE developer_profiles SET github_login = 'taken' {own}", u=p.outsider) == 0
