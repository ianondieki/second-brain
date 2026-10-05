"""Demo seed steps for P21's beats (REQ-ENG-11, REQ-REPO-02, REQ-PERS-03; D-57), so the Messages tab, the Shortlist and
the Saved searches panel have something to show on ``make demo``. Part of ``python -m bridge.seed --demo``, last: after
the tracker (the thread needs Amina's engagement with SACCO B past ``INTEREST_CONFIRMED``), the liked niches and the
Telco A scout (whose match is the shortlist entry).

- **A thread** (``data.THREAD``): on Amina's P1 engagement with SACCO B (``NEGOTIATION``; ``CONTACT_MADE`` without
  ``FEATURE_DEALS_ENABLED``), SACCO B's owner, its named contact, and Amina write three short messages in turn through
  ``POST /api/engagements/{id}/messages``, each signed in as themselves. Every post is audited and queues its N18 job,
  so the worker puts it in the other side's bell (and, at most one per 30 minutes, an email in Mailpit). The text holds
  no contact details or links, which the thread refuses before first contact (D-57 (8)).
- **A shortlist entry** (``SHORTLISTED``): Telco A's reviewer, who gets the scout's digest, puts the scout's match
  (``scouts.SCOUTED``) on the organisation's shortlist through ``PUT /api/orgs/{org}/shortlist/{proposal}``.
- **A saved search** (``data.SAVED_SEARCH``): Amina saves Discover's Problems view of Microfinance & SACCOs, a niche
  she likes and the seed gives problems, through ``POST /api/me/saved-searches``, alerts on; the daily job (07:05 in
  Nairobi) tells her about problems published after it.

Idempotent and safe on a used demo (P9's rules), each step looking first as the owner role, so a run with nothing to do
signs nobody in. The thread step writes only into an empty thread (one people wrote in is theirs) and only while the
engagement has not ended (one that ended is left with one line in the report). The shortlist step runs only while
Telco A never shortlisted the match (no row and no ``shortlist.added`` event), so an entry people removed stays
removed. The saved search is looked for by its name and by its view and filters (renaming changes only the name), and
is not added when Amina keeps the most a developer may (``MAX_SAVED_SEARCHES``, one line in the report); a deleted
saved search leaves no trace, so the next start saves it again. A refusal of the app (a thread that is not open, a
proposal no longer in the Inbox, a password changed) is left to ``guarded``. Dev and test only (``demo_refusal``,
checked by the seed before any step).
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements import state_machine as sm
from bridge.models.enums import EngagementState, OrgRole
from bridge.profiles.models import MAX_SAVED_SEARCHES
from bridge.seed.demo.data import ORGS, PROPOSALS, SAVED_SEARCH, TELCO_A, THREAD, DemoThread
from bridge.seed.demo.engagements import DEVELOPER
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one
from bridge.seed.demo.scouts import SCOUTED

# The shortlist entry as (proposal, organisation, the seat that adds it), like ``data.VIEWED``: the scout's match, by
# the reviewer its digest goes to.
SHORTLISTED: Final = (SCOUTED, TELCO_A, TELCO_A.seats[1])

_THREAD_OF = (
    "SELECT e.id, e.state::text AS state, EXISTS (SELECT 1 FROM engagement_messages m WHERE m.engagement_id = e.id)"
    " AS written FROM engagements e WHERE e.proposal_id = :p AND e.org_id = :o ORDER BY e.created_at DESC LIMIT 1"
)
_EVER_SHORTLISTED = (
    "SELECT EXISTS (SELECT 1 FROM org_shortlist WHERE org_id = :org AND proposal_id = :p) OR EXISTS (SELECT 1 FROM"
    " audit_events WHERE org_id = :org AND action = 'shortlist.added' AND subject_id = :p) AS ever"
)
_SAVED = (
    "SELECT count(*) AS kept, count(*) FILTER (WHERE name = :name OR (view = :view"
    " AND niche_slug IS NOT DISTINCT FROM CAST(:niche AS text)"
    " AND county_code IS NOT DISTINCT FROM CAST(:county AS text)"
    " AND words IS NOT DISTINCT FROM CAST(:words AS text))) AS found FROM saved_searches WHERE user_id = :u"
)


def writer(thread: DemoThread, who: str) -> str:
    """The address of whoever writes as ``who`` on ``thread``: the proposal's owner, or the fixture's seat with the
    role (its owner first)."""
    if who == DEVELOPER:
        return next(p.owner for p in PROPOSALS if p.key == thread.proposal)
    org = next(o for o in ORGS if o.legal_name == thread.org)
    seats = ([org.owner] if org.owner else []) + list(org.seats)
    return next(seat.email for seat in seats if OrgRole(who) in seat.roles)


async def ensure_thread(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """``THREAD``'s messages, posted in turn by their writers into its engagement's empty thread (module docstring)."""
    plan = THREAD
    if plan.proposal not in report.proposals or plan.org not in report.orgs:
        raise DemoSeedError(f"{plan.proposal} or {plan.org} is not there to write on")
    row = await _one(owner, _THREAD_OF, p=report.proposals[plan.proposal], o=report.orgs[plan.org])
    if row is None:
        raise DemoSeedError(f"no engagement for {plan.proposal} with {plan.org}: its Pitch did not open one")
    if row.written:
        return
    state = EngagementState(row.state)
    if state in sm.TERMINAL:
        report.notes.append(f"thread of {plan.proposal} with {plan.org} left as it is: the engagement is {state.value}")
        return
    for message in plan.messages:
        actor = await actors.get(writer(plan, message.who))
        await actor.call("POST", f"/api/engagements/{row.id}/messages", json={"body": message.body}, expect=(201,))
    report.did(f"thread of {plan.proposal} with {plan.org}: {len(plan.messages)} messages")


async def ensure_shortlisted(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """``SHORTLISTED``'s entry, added by its seat through the API, unless the organisation ever shortlisted it."""
    proposal, org, seat = SHORTLISTED
    org_id, proposal_id = report.orgs.get(org.legal_name), report.proposals.get(proposal.key)
    if org_id is None or proposal_id is None:
        raise DemoSeedError(f"{proposal.key} or {org.legal_name} is not there to shortlist")
    if (await _one(owner, _EVER_SHORTLISTED, org=org_id, p=proposal_id)).ever:
        return
    actor = await actors.get(seat.email)
    await actor.call("PUT", f"/api/orgs/{org_id}/shortlist/{proposal_id}")
    report.did(f"shortlist of {org.legal_name}: {proposal.key} by {seat.email}")


async def ensure_saved_search(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """``SAVED_SEARCH``, saved by its developer through the API, unless found by name or by its view and filters."""
    plan = SAVED_SEARCH
    user_id = report.users.get(plan.owner)
    if user_id is None:
        raise DemoSeedError(f"{plan.owner} is not there to save a search")
    filters = {"view": plan.view, "niche": plan.niche, "county": plan.county, "words": plan.words}
    row = await _one(owner, _SAVED, u=user_id, name=plan.name, **filters)
    if row.found:
        return
    if row.kept >= MAX_SAVED_SEARCHES:
        report.notes.append(f"saved search of {plan.owner} not added: they keep {MAX_SAVED_SEARCHES} already")
        return
    actor = await actors.get(plan.owner)
    await actor.call("POST", "/api/me/saved-searches", json={"name": plan.name, **filters}, expect=(201,))
    report.did(f"saved search of {plan.owner}: {plan.name}")
