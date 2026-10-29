"""Demo seed steps for P22's Peers and team up (REQ-DEV-03; D-58, D-62 (a)), so the peers page, the team-up
invitations, a team thread and the contributors line have something to show on ``make demo``. Part of ``python -m
bridge.seed --demo``, last: after the liked niches (P12), Amina's county (This week) and the proposals.

- **Peers** (``PEERS``): Amina and Brian turn Peers on, Brian in Amina's county (Nairobi City) and liking
  Networks & Telecommunications too, so the two share two liked niches; Zawadi (``data.ZAWADI``) turns it on in
  Mombasa liking one of Amina's niches (Agriculture); Juma (``data.JUMA``) likes Amina's niches in her county but never
  turns it on, so nobody sees him. Each through the app: ``PATCH /api/me/profile`` (the county only while the profile
  has none; the switch) and ``PUT /api/me/niches`` (the niches a developer has none of, or the ones Brian lacks).
- **A team** (``TEAM``): Amina invites Brian through ``POST /api/me/teams/invitations`` to team up on P2's problem
  (her published idea's), Brian accepts, and the two write four messages in turn on the thread.
- **A contributor**: Amina credits Brian on P2 (``POST /api/me/ideas/{id}/contributors``), so the idea page and its
  certificate say "Contributors: <Brian's handle>".
- **A pending invitation** (``PENDING``): Zawadi invites Amina to team up on P1's problem, with a note.

Idempotent and safe on a used demo (P9's rules), each step looking first as the owner role, so a run with nothing to do
signs nobody in. The peers step runs only until Amina's first team-up invitation exists (the scene's start): a switch
someone turned off later stays off, a county or niches someone changed stay theirs. The team step writes the thread's
messages only into an empty, open thread; an invitation between Amina and Brian that someone declined, withdrew or
ended is left as it is with one line in the report. The contributor is added only while Brian was never credited on
P2 (a removed credit is never added back), and Zawadi's invitation only while she never invited Amina. A refusal of the
app is left to ``guarded``. Dev and test only (``demo_refusal``, checked by the seed before any step).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.seed.demo.data import AMINA, BRIAN, JUMA, P1, P2, ZAWADI
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one


@dataclass(frozen=True, slots=True)
class DemoPeer:
    email: str
    county: str | None  # set while the profile has none (None: keep what it has)
    liked: tuple[str, ...]  # niche slugs the developer likes after the step (the others they like stay)
    opted_in: bool


@dataclass(frozen=True, slots=True)
class DemoTeamUp:
    sender: str
    recipient: str
    problem_of: str  # the proposal key whose new problem the invitation names
    note: str | None
    messages: tuple[tuple[str, str], ...] = ()  # (writer's address, body), in order, once accepted


NAIROBI_CITY: Final = "KE-30"
MOMBASA: Final = "KE-28"
PEERS: Final = (
    DemoPeer(AMINA.email, None, (), opted_in=True),  # her county is This week's, her niches P12's
    DemoPeer(BRIAN.email, NAIROBI_CITY, ("networks-telecommunications",), opted_in=True),
    DemoPeer(ZAWADI.email, MOMBASA, ("agriculture", "energy", "logistics"), opted_in=True),
    DemoPeer(JUMA.email, NAIROBI_CITY, ("microfinance-saccos", "agriculture", "retail"), opted_in=False),
)
# Fixture text: short, plain, about the work.
TEAM: Final = DemoTeamUp(
    sender=AMINA.email,
    recipient=BRIAN.email,
    problem_of=P2.key,
    note="Your county work has the radio know-how my tower-site alerts need. Shall we build the alert rules together?",
    messages=(
        (AMINA.email, "Thanks for joining. The fuel sensors report from two test sites now; the alert rules are next."),
        (BRIAN.email, "Happy to take those. I can write the burn-rate check and test it on last month's readings."),
        (AMINA.email, "Good. Let us aim for a first version by Friday and go through it together."),
        (BRIAN.email, "Agreed. I will post my notes here when the first tests pass."),
    ),
)
PENDING: Final = DemoTeamUp(
    sender=ZAWADI.email,
    recipient=AMINA.email,
    problem_of=P1.key,
    note="I build farm-sensor dashboards in Mombasa. Would you like help with the repayment nudges?",
)
CONTRIBUTOR: Final = (P2.key, BRIAN.email)  # the idea and the developer it credits

_STARTED = "SELECT 1 FROM team_invitations WHERE from_user_id = :u OR to_user_id = :u LIMIT 1"  # Amina's scene began
_PROFILE = "SELECT county_code, peers_visible FROM developer_profiles WHERE user_id = :u"
_LIKED = (
    "SELECT n.slug::text AS slug FROM developer_niches d JOIN niches n ON n.id = d.niche_id"
    " WHERE d.user_id = :u AND d.kind = 'liked' ORDER BY n.slug"
)
_PROBLEM = (
    "SELECT pr.id, pr.title FROM proposals p JOIN proposal_versions v ON v.proposal_id = p.id AND v.version_no = 1"
    " JOIN proposal_problems pp ON pp.proposal_version_id = v.id JOIN problems pr ON pr.id = pp.problem_id"
    " WHERE p.id = :p ORDER BY pr.created_at LIMIT 1"
)
_INVITATIONS = (
    "SELECT id, status FROM team_invitations WHERE from_user_id = :a AND to_user_id = :b AND problem_id = :p"
    " ORDER BY created_at DESC"
)
_THREAD = (
    "SELECT t.id, t.closed_at, EXISTS (SELECT 1 FROM team_messages m WHERE m.thread_id = t.id) AS written"
    " FROM team_threads t JOIN team_invitations i ON i.id = t.invitation_id"
    " WHERE i.from_user_id = :a AND i.to_user_id = :b AND i.problem_id = :p"
)
_EVER_INVITED = "SELECT 1 FROM team_invitations WHERE from_user_id = :a AND to_user_id = :b LIMIT 1"
_EVER_CREDITED = "SELECT 1 FROM proposal_contributors WHERE proposal_id = :p AND user_id = :u"


def _user(report: DemoReport, email: str) -> UUID:
    user_id = report.users.get(email)
    if user_id is None:
        raise DemoSeedError(f"{email} is not there to team up")
    return user_id


async def ensure_peers(owner: AsyncEngine, actors: Actors, niches: dict[str, UUID], report: DemoReport) -> None:
    """``PEERS``' profiles (module docstring), until Amina's scene began."""
    if await _one(owner, _STARTED, u=_user(report, AMINA.email)) is not None:
        return
    for plan in PEERS:
        await _profile(owner, actors, niches, plan, _user(report, plan.email), report)


async def _profile(
    owner: AsyncEngine, actors: Actors, niches: dict[str, UUID], plan: DemoPeer, user_id: UUID, report: DemoReport
) -> None:
    profile = await _one(owner, _PROFILE, u=user_id)
    if profile is None:
        raise DemoSeedError(f"{plan.email} has no developer profile")
    liked = [row.slug for row in await _rows(owner, _LIKED, u=user_id)]
    wanted = sorted(set(liked) | set(plan.liked))
    changes: dict[str, object] = {}
    if plan.county is not None and profile.county_code is None:
        changes["county_code"] = plan.county
    if plan.opted_in and not profile.peers_visible:
        changes["peers_visible"] = True
    if not changes and wanted == liked:
        return
    missing = [slug for slug in wanted if slug not in niches]
    if missing:
        raise DemoSeedError(f"niches {missing} are missing: run the reference seed first")
    actor = await actors.get(plan.email)
    if changes:
        await actor.call("PATCH", "/api/me/profile", json=changes)
        if "county_code" in changes:
            report.did(f"county of {plan.email}: {plan.county}")
        if "peers_visible" in changes:
            report.did(f"peers on for {plan.email}")
    if wanted != liked:
        await actor.call("PUT", "/api/me/niches", json={"liked": [str(niches[slug]) for slug in wanted]})
        report.did(f"liked niches of {plan.email}: {', '.join(wanted)}")


async def _rows(owner: AsyncEngine, sql: str, **params: object) -> list[Any]:
    """Seed only: the rows of an owner-role query."""
    async with owner.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def _problem(owner: AsyncEngine, report: DemoReport, key: str) -> tuple[UUID, str]:
    proposal_id = report.proposals.get(key)
    found = None if proposal_id is None else await _one(owner, _PROBLEM, p=proposal_id)
    if found is None:
        raise DemoSeedError(f"{key}'s problem is not there to team up on")
    return UUID(str(found.id)), str(found.title)


async def _invite(actors: Actors, plan: DemoTeamUp, to: UUID, problem_id: UUID) -> str:
    sender = await actors.get(plan.sender)
    body = {"to_user_id": str(to), "problem_id": str(problem_id), "note": plan.note}
    made = await sender.call("POST", "/api/me/teams/invitations", json=body, expect=(201,))
    invitation_id: str = made.json()["id"]
    return invitation_id


async def ensure_team(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """``TEAM``: the invitation, its acceptance and the thread's messages (module docstring)."""
    plan = TEAM
    sender, recipient = _user(report, plan.sender), _user(report, plan.recipient)
    problem_id, title = await _problem(owner, report, plan.problem_of)
    keys = {"a": sender, "b": recipient, "p": problem_id}
    thread = await _one(owner, _THREAD, **keys)
    if thread is None:
        invitations = await _rows(owner, _INVITATIONS, **keys)
        pending = [row for row in invitations if row.status == "pending"]
        if invitations and not pending:
            report.notes.append(f"team-up of {plan.sender} and {plan.recipient} left as it is: it was answered")
            return
        invitation_id = str(pending[0].id) if pending else await _invite(actors, plan, recipient, problem_id)
        accepter = await actors.get(plan.recipient)
        await accepter.call("POST", f"/api/me/teams/invitations/{invitation_id}/accept", expect=(201,))
        report.did(f"team-up of {plan.sender} and {plan.recipient} on {title}")
        thread = await _one(owner, _THREAD, **keys)
        if thread is None:
            raise DemoSeedError("the accepted team-up opened no thread")
    if thread.written or thread.closed_at is not None:
        return
    writers = {email: await actors.get(email) for email in dict.fromkeys(email for email, _ in plan.messages)}
    for email, body in plan.messages:
        await writers[email].call("POST", f"/api/me/teams/{thread.id}/messages", json={"body": body}, expect=(201,))
    report.did(f"team thread of {plan.sender} and {plan.recipient}: {len(plan.messages)} messages")


async def ensure_contributor(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """``CONTRIBUTOR``: the idea's owner credits the developer they team up with, while never credited before."""
    key, email = CONTRIBUTOR
    proposal_id, user_id = report.proposals.get(key), _user(report, email)
    if proposal_id is None:
        raise DemoSeedError(f"{key} is not there to credit a contributor on")
    if await _one(owner, _EVER_CREDITED, p=proposal_id, u=user_id) is not None:
        return
    actor = await actors.get(TEAM.sender)
    path = f"/api/me/ideas/{proposal_id}/contributors"
    await actor.call("POST", path, json={"user_id": str(user_id)}, expect=(201,))
    report.did(f"contributor on {key}: {email}")


async def ensure_pending_invitation(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """``PENDING``: Zawadi's invitation to Amina, while she never invited her."""
    plan = PENDING
    sender, recipient = _user(report, plan.sender), _user(report, plan.recipient)
    if await _one(owner, _EVER_INVITED, a=sender, b=recipient) is not None:
        return
    problem_id, title = await _problem(owner, report, plan.problem_of)
    await _invite(actors, plan, recipient, problem_id)
    report.did(f"team-up invitation from {plan.sender} to {plan.recipient} on {title}")
