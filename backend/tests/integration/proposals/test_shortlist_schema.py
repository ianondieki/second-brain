"""Revision 0008 (REQ-REPO-02, P21 track B, D-57 (6)): the organisation shortlist's tenancy and roles.

- ``app_org_sees_proposal(org, proposal)`` is the organisation's Inbox: a published, clear proposal pitched to it (a
  delivered tag), matched by its scout or answering its Brief; true only for a member of that organisation (narrowed
  by ``app.org_id``), so nobody learns another organisation's Inbox.
- Every member reads the shortlist (no other organisation, staff or developer does); members with a Tier-2 role
  (reviewer, signatory, admin) add a proposal of the Inbox as themselves and remove one; finance and viewers do not.

Every test runs in one rolled-back transaction (``tracker.as_app``).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

ADD = "INSERT INTO org_shortlist (org_id, proposal_id, added_by) VALUES (:org, :p, :by)"
LISTED = "SELECT count(*) FROM org_shortlist"
SEES = "SELECT app_org_sees_proposal(:org, :p)"
RLS = "row-level security"


@dataclass(frozen=True, slots=True)
class Inbox:
    p: t.Parties
    pitched: UUID  # the developer's proposal, tagged to the organisation (delivered)
    matched: UUID  # matched by the organisation's scout
    answering: UUID  # its current version links the organisation's Brief
    unseen: UUID  # published and clear, but in none of the three
    held: UUID  # pitched, but held by moderation
    elsewhere: UUID  # pitched to the other organisation only


async def inbox(conn: AsyncConnection) -> Inbox:
    """As the owner: the parties' organisation and the proposals around its Inbox."""
    p = await t.parties(conn)
    niche = uuid7()
    await t.run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Shortlist')", id=niche, s=f"s-{niche}")
    problem = await w.add_problem(conn, p.outsider, niche)
    matched, matched_version = await w.add_proposal(conn, p.outsider, niche, problem)
    await w.add_scout_rows(conn, p.org, p.owner, niche, matched, matched_version)
    brief = await w.add_problem(conn, p.owner, niche, org_id=p.org)
    await t.run(
        conn,
        "INSERT INTO problem_briefs (problem_id, org_id, visibility, status) VALUES (:id, :org, 'public', 'published')",
        id=brief,
        org=p.org,
    )
    answering, _ = await w.add_proposal(conn, p.outsider, niche, brief)
    unseen, _ = await w.add_proposal(conn, p.outsider, niche, problem)
    pitcher = await w.add_user(conn, f"pitcher-{uuid7().hex}@example.test", "Pitcher")
    held, _ = await w.add_proposal(conn, pitcher, niche, problem, moderation_state="held")
    await t.tag(conn, held, p.org, pitcher)
    elsewhere, _ = await w.add_proposal(conn, pitcher, niche, problem)
    await t.tag(conn, elsewhere, p.other_org, pitcher)
    return Inbox(p, p.proposal, matched, answering, unseen, held, elsewhere)


async def test_the_inbox_check_answers_only_for_the_callers_own_organisation(owner_engine: AsyncEngine) -> None:
    """Pitched, matched and Brief-answering proposals are in the Inbox, an unseen, held or elsewhere-pitched one is not;
    and the check is false for anyone who is not a member of the organisation asked about (another organisation, a
    forged context, staff, a developer, no user), so it never reveals another organisation's Inbox."""
    async with t.as_app(owner_engine) as conn:
        s = await inbox(conn)
        p = s.p
        await t.act(conn, p.viewer, p.org)  # any member: the check is about the Inbox, the policy about the role
        for proposal, seen in (
            (s.pitched, True),
            (s.matched, True),
            (s.answering, True),
            (s.unseen, False),
            (s.held, False),
            (s.elsewhere, False),
            (uuid7(), False),
        ):
            assert await t.run(conn, SEES, org=p.org, p=proposal) is seen, proposal
        for by, org in (
            (p.other_member, p.other_org),
            (p.owner, p.other_org),  # a forged organisation context
            (p.staff, None),
            (p.developer, None),
            (None, None),
        ):
            await t.act(conn, by, org)
            assert await t.run(conn, SEES, org=p.org, p=s.pitched) is False, by
        await t.act(conn, p.other_member, p.other_org)
        assert await t.run(conn, SEES, org=p.other_org, p=s.elsewhere) is True


async def test_tier2_members_keep_the_shortlist_and_every_member_reads_it(owner_engine: AsyncEngine) -> None:
    """Reviewer, signatory and admin add Inbox proposals as themselves (once each); finance, viewers, another
    organisation and a proposal outside the Inbox are refused; every member reads the list and nobody else does; a
    Tier-2 member removes an entry, others cannot; nothing is ever updated and added_at is the database's."""
    async with t.as_app(owner_engine) as conn:
        s = await inbox(conn)
        p = s.p
        for by, proposal in ((p.reviewer, s.pitched), (p.signatory, s.matched), (p.owner, s.answering)):
            await t.act(conn, by, p.org)
            await t.run(conn, ADD, org=p.org, p=proposal, by=by)
        await t.act(conn, p.reviewer, p.org)
        await t.expect(conn, ADD, "pk_org_shortlist", org=p.org, p=s.pitched, by=p.reviewer)  # once per proposal
        repeat = ADD + " ON CONFLICT (org_id, proposal_id) DO NOTHING"
        assert await t.rowcount(conn, repeat, org=p.org, p=s.pitched, by=p.reviewer) == 0  # an idempotent PUT
        for by, org, target_org, proposal, added_by in (
            (p.finance, p.org, p.org, s.unseen, p.finance),
            (p.viewer, p.org, p.org, s.unseen, p.viewer),
            (p.reviewer, p.org, p.org, s.unseen, p.reviewer),  # not in the Inbox
            (p.reviewer, p.org, p.org, s.held, p.reviewer),
            (p.reviewer, p.org, p.org, s.elsewhere, p.reviewer),
            (p.reviewer, p.org, p.org, s.unseen, p.signatory),  # in someone else's name
            (p.other_member, p.other_org, p.org, s.unseen, p.other_member),  # into another organisation's list
            (p.other_member, p.other_org, p.other_org, s.pitched, p.other_member),  # from another's Inbox
            (p.owner, p.other_org, p.org, s.unseen, p.owner),  # a forged organisation context
            (p.staff, None, p.org, s.unseen, p.staff),
        ):
            await t.act(conn, by, org)
            await t.expect(conn, ADD, RLS, org=target_org, p=proposal, by=added_by)
        await t.act(conn, p.other_member, p.other_org)
        await t.run(conn, ADD, org=p.other_org, p=s.elsewhere, by=p.other_member)  # its own list, its own Inbox
        for reader, org, seen in (
            (p.viewer, p.org, 3),
            (p.finance, p.org, 3),
            (p.owner, None, 3),
            (p.other_member, p.other_org, 1),
            (p.owner, p.other_org, 0),
            (p.staff, None, 0),
            (p.developer, None, 0),
            (None, None, 0),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, LISTED) == seen, (reader, org)
        await t.act(conn, p.reviewer, p.org)
        await t.expect(
            conn,
            "INSERT INTO org_shortlist (org_id, proposal_id, added_by, added_at) VALUES (:org, :p, :by, now())",
            "permission denied",
            org=p.org,
            p=s.unseen,
            by=p.reviewer,
        )
        await t.expect(conn, "UPDATE org_shortlist SET added_by = :by", "permission denied", by=p.reviewer)
        remove = "DELETE FROM org_shortlist WHERE org_id = :org AND proposal_id = :p"
        for by, org in ((p.viewer, p.org), (p.finance, p.org), (p.other_member, p.other_org), (p.staff, None)):
            await t.act(conn, by, org)
            assert await t.rowcount(conn, remove, org=p.org, p=s.pitched) == 0, by
        await t.act(conn, p.signatory, p.org)
        assert await t.rowcount(conn, remove, org=p.org, p=s.pitched) == 1
        assert await t.run(conn, LISTED) == 2


async def test_a_shortlisted_proposal_put_on_hold_stays_harmless(owner_engine: AsyncEngine) -> None:
    """Given proposals on the organisation's shortlist, When moderation holds one (staff, app_moderate_proposal), Then
    its shortlist row stays, holding ids, who added it and when only, but shows nothing: no member reads the proposal
    through it (the proposals' RLS hides a held proposal from everyone but its owner and staff, so the API, which
    re-reads under RLS, drops it from the list and Compare), the Inbox check is false, a Tier-2 member still removes
    it and nobody adds it back while it is held; the other entry is untouched. No database change is needed."""
    async with t.as_app(owner_engine) as conn:
        s = await inbox(conn)
        p = s.p
        await t.act(conn, p.reviewer, p.org)
        for proposal in (s.matched, s.pitched):
            await t.run(conn, ADD, org=p.org, p=proposal, by=p.reviewer)
        await t.act(conn, p.staff)
        await t.run(conn, "SELECT app_moderate_proposal(:p, 'held')", p=s.matched)
        through = (
            "SELECT count(*) FROM org_shortlist s JOIN proposals x ON x.id = s.proposal_id"
            " LEFT JOIN proposal_versions v ON v.id = x.current_version_id WHERE s.proposal_id = :p"
        )
        for reader in (p.viewer, p.reviewer, p.owner):
            await t.act(conn, reader, p.org)
            assert await t.run(conn, LISTED) == 2, reader  # the row stays
            assert await t.run(conn, through, p=s.matched) == 0, reader  # but leads nowhere
            assert await t.run(conn, through, p=s.pitched) == 1, reader
            assert await t.run(conn, SEES, org=p.org, p=s.matched) is False
        columns = (
            "SELECT array_agg(column_name::text ORDER BY column_name) FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = 'org_shortlist'"
        )
        assert await t.run(conn, columns) == ["added_at", "added_by", "org_id", "proposal_id"]  # no proposal text
        await t.act(conn, p.reviewer, p.org)
        remove = "DELETE FROM org_shortlist WHERE org_id = :org AND proposal_id = :p"
        assert await t.rowcount(conn, remove, org=p.org, p=s.matched) == 1
        await t.expect(conn, ADD, RLS, org=p.org, p=s.matched, by=p.reviewer)  # not back while held
        assert await t.run(conn, LISTED) == 1
