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
engagement has not ended (one that ended is left with one line in the report); every writer signs in before the first
post, so a sign-in refused on a used demo (a password changed) writes nothing rather than half a thread, which, being
append-only, a later run could never complete. The shortlist step runs only while Telco A never shortlisted the match
(no row and no ``shortlist.added`` event), so an entry people removed stays removed. The saved search is saved only
while Amina has none at all, as the liked niches are set only for a developer with none (``trending``): one she
renamed, replaced or deleted beside others of her own stays as she left it (deleting every search she has brings it
back at the next start). A refusal of the app (a thread that is not open, a proposal no longer in the Inbox, a password
changed) is left to ``guarded``. Dev and test only (``demo_refusal``, checked by the seed before any step).
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements import state_machine as sm
from bridge.models.enums import EngagementState
from bridge.seed.demo.data import SAVED_SEARCH, TELCO_A, THREAD
from bridge.seed.demo.engagements import party_email
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
_HAS_SAVED = "SELECT 1 FROM saved_searches WHERE user_id = :u LIMIT 1"


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
    # Every writer signs in before the first post: a refused sign-in then writes nothing (the thread is append-only).
    emails = [party_email(plan, message.who) for message in plan.messages]
    writers = {email: await actors.get(email) for email in dict.fromkeys(emails)}
    path = f"/api/engagements/{row.id}/messages"
    for message, email in zip(plan.messages, emails, strict=True):
        await writers[email].call("POST", path, json={"body": message.body}, expect=(201,))
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
    """``SAVED_SEARCH``, saved by its developer through the API while they have no saved search at all."""
    plan = SAVED_SEARCH
    user_id = report.users.get(plan.owner)
    if user_id is None:
        raise DemoSeedError(f"{plan.owner} is not there to save a search")
    if await _one(owner, _HAS_SAVED, u=user_id) is not None:
        return
    actor = await actors.get(plan.owner)
    body = {"name": plan.name, "view": plan.view, "niche": plan.niche, "county": plan.county, "words": plan.words}
    await actor.call("POST", "/api/me/saved-searches", json=body, expect=(201,))
    report.did(f"saved search of {plan.owner}: {plan.name}")
