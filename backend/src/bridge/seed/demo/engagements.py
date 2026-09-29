"""Demo seed step for the tracker (``bridge.seed.demo``; P5, REQ-ENG-01..REQ-ENG-10 main path).

Each ``DemoEngagement`` was opened by its Pitch (``SUBMITTED``); this step drives it along the main path through the
tracker API (``POST /api/engagements/{id}/<command>``, which runs ``bridge.engagements.commands.execute``) until it
reaches its target, each command by the party and role the state machine names, every signature and endorsement from
a session whose second factor was just given with the account's demo TOTP code (ADR-002 step-up). Nothing is written
to the tracker tables directly, so each History tab is the real hash chain.

Resumable and idempotent: at every turn the engagement's state is read and the next step is the first one of the
path, for that state, that its actor is offered (``actions``); an engagement at its target is left alone. Steps from
``send_nda`` on need ``FEATURE_DEALS_ENABLED`` (``make demo`` sets it): without it the engagement stops before them
and the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings
from bridge.engagements.calendar import add_business_days
from bridge.models.enums import EngagementState, OrgRole
from bridge.seed.demo.data import ORGS, PROPOSALS, DemoEngagement, DemoOrg
from bridge.seed.demo.runtime import Actor, Actors, DemoReport, DemoSeedError, one

S = EngagementState
DEVELOPER: Final = "developer"
CONTACT_BY_BD: Final = 2  # the contact-by date named at approval: two business days ahead (policy allows five)
MAX_TURNS: Final = 60
# Commands gated by FEATURE_DEALS_ENABLED (docs/spec/10; P5 decision 3): everything from sending the NDA on.
DEAL_COMMANDS: Final = frozenset(
    {
        "send-nda",
        "sign-nda",
        "propose-terms",
        "mark-final",
        "sign-agreement",
        "deliver",
        "accept-delivery",
        "sign-certificate",
        "record-payment",
        "confirm-payment",
        "start",
        "submit",
        "accept",
    }
)


@dataclass(frozen=True, slots=True)
class Step:
    state: EngagementState  # the state the step runs in
    who: str  # "developer" or an organisation role (OrgRole value); OWNER is also the named contact
    command: str  # the URL segment


# The main path of docs/spec/06 6.9 as the parties run it (the milestone sub-tracker is handled apart).
MAIN_PATH: Final = (
    Step(S.SUBMITTED, OrgRole.REVIEWER, "start-review"),
    Step(S.UNDER_REVIEW, OrgRole.SIGNATORY, "approve"),
    Step(S.INTEREST_CONFIRMED, OrgRole.OWNER, "mark-contacted"),
    Step(S.CONTACT_MADE, DEVELOPER, "confirm-contact"),
    Step(S.CONTACT_MADE, DEVELOPER, "send-nda"),
    Step(S.NDA_PENDING, DEVELOPER, "sign-nda"),
    Step(S.NDA_PENDING, OrgRole.SIGNATORY, "sign-nda"),
    Step(S.NDA_SIGNED, OrgRole.OWNER, "propose-terms"),
    Step(S.NEGOTIATION, DEVELOPER, "mark-final"),
    Step(S.AGREEMENT_SIGNING, OrgRole.SIGNATORY, "sign-agreement"),
    Step(S.AGREEMENT_SIGNING, DEVELOPER, "sign-agreement"),
    Step(S.IN_IMPLEMENTATION, DEVELOPER, "deliver"),
    Step(S.DELIVERED, OrgRole.REVIEWER, "accept-delivery"),
    Step(S.SIGN_OFF, OrgRole.SIGNATORY, "sign-certificate"),
    Step(S.SIGN_OFF, DEVELOPER, "sign-certificate"),
    Step(S.PAYMENT_FINAL, OrgRole.FINANCE, "record-payment"),
    Step(S.PAYMENT_FINAL, DEVELOPER, "confirm-payment"),
)
# Milestone state -> (who, command) of the sub-tracker (docs/spec/06 6.9 stage 9).
MILESTONE_STEPS: Final = {
    "PLANNED": (DEVELOPER, "start"),
    "IN_PROGRESS": (DEVELOPER, "submit"),
    "CHANGES_REQUESTED": (DEVELOPER, "start"),
    "SUBMITTED_FOR_REVIEW": (OrgRole.REVIEWER, "accept"),
}


def _org(name: str) -> DemoOrg:
    return next(org for org in ORGS if org.legal_name == name)


def _email(plan: DemoEngagement, who: str) -> str:
    """The address of the person who acts as ``who`` in ``plan``: the developer, or the fixture's seat."""
    if who == DEVELOPER:
        return next(p.owner for p in PROPOSALS if p.key == plan.proposal)
    org = _org(plan.org)
    seats = ([org.owner] if org.owner else []) + list(org.seats)
    return next(seat.email for seat in seats if OrgRole(who) in seat.roles)


class Driver:
    """Runs one engagement's steps through the API, reading ``lock_version`` and the actions before each."""

    def __init__(self, owner: AsyncEngine, actors: Actors, report: DemoReport, plan: DemoEngagement, eid: UUID) -> None:
        self.owner, self.actors, self.report, self.plan, self.id = owner, actors, report, plan, eid

    def path(self, suffix: str = "") -> str:
        return f"/api/engagements/{self.id}{suffix}"

    async def detail(self, actor: Actor) -> dict[str, Any]:
        detail: dict[str, Any] = (await actor.call("GET", self.path())).json()
        return detail

    async def run(self, actor: Actor, command: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        lock = (await self.detail(actor))["lock_version"]
        response = await actor.call("POST", self.path(f"/{command}"), json={"lock_version": lock, **(body or {})})
        detail: dict[str, Any] = response.json()
        return detail

    async def today(self) -> date:
        """Today on the app clock (the database clock plus the dev/test clock's offset), in Nairobi."""
        row = await one(self.owner, "SELECT (app_clock_now() AT TIME ZONE 'Africa/Nairobi')::date AS today")
        return date.fromisoformat(str(row.today))

    async def body(self, command: str) -> dict[str, Any] | None:
        today = await self.today()
        if command == "approve":
            async with self.owner.connect() as conn:
                rows = await conn.execute(
                    text("SELECT observed_on FROM holidays WHERE observed_on >= :d"), {"d": today}
                )
                holidays = frozenset(r[0] for r in rows)
            return {
                "contact_user_id": str(self.report.users[_email(self.plan, OrgRole.OWNER)]),
                "contact_channel": "email",
                "contact_by": str(add_business_days(today, CONTACT_BY_BD, holidays)),
            }
        if command == "propose-terms":
            return {
                "ip_terms": self.plan.ip_terms.value,
                "deemed_acceptance_days": self.plan.deemed_acceptance_days,
                "milestones": [
                    {
                        "deliverable": m.deliverable,
                        "amount_kes_minor": m.amount_kes_minor,
                        "due_date": str(today + timedelta(days=m.due_in_days)),
                    }
                    for m in self.plan.milestones
                ],
            }
        total = sum(m.amount_kes_minor for m in self.plan.milestones)
        if command == "record-payment":
            return {
                "amount_kes_minor": total,
                "method": "mpesa",
                "reference": self.plan.payment_reference,
                "paid_on": str(today),
            }
        if command == "confirm-payment":
            return {"amount_received_kes_minor": total}
        return None

    async def next_step(self, state: EngagementState, *, deals: bool) -> tuple[Actor, str] | None:
        """The first step of the path for ``state`` that its actor is offered now (the milestones at stage 9), or None
        when the next step is a deal step and ``FEATURE_DEALS_ENABLED`` is off (nobody is offered it then)."""
        steps = [step for step in MAIN_PATH if step.state == state]
        if not deals and steps and all(step.command in DEAL_COMMANDS for step in steps):
            return None
        if state == S.IN_IMPLEMENTATION:
            developer = await self.actors.get(_email(self.plan, DEVELOPER))
            agreements = (await self.detail(developer))["agreements"]
            signed = next(a for a in agreements if a["status"] == "signed")
            for milestone in signed["milestones"]:
                if milestone["state"] in MILESTONE_STEPS:
                    who, segment = MILESTONE_STEPS[milestone["state"]]
                    return await self.actors.get(_email(self.plan, who)), f"milestones/{milestone['id']}/{segment}"
        offered: list[str] = []
        for step in steps:
            actor = await self.actors.get(_email(self.plan, step.who))
            actions = (await self.detail(actor))["actions"]
            if step.command.replace("-", "_") in actions:
                return actor, step.command
            if step.command in DEAL_COMMANDS and not deals:
                return None
            offered.append(f"{step.who}: {', '.join(actions) or 'nothing'}")
        raise DemoSeedError(
            f"{self.plan.proposal} with {self.plan.org}: no step to take in {state.value} ({'; '.join(offered)})"
        )


async def _engagement(owner: AsyncEngine, report: DemoReport, plan: DemoEngagement) -> tuple[UUID, EngagementState]:
    row = await one(
        owner,
        "SELECT id, state::text AS state FROM engagements WHERE proposal_id = :p AND org_id = :o"
        " ORDER BY created_at DESC LIMIT 1",
        p=report.proposals[plan.proposal],
        o=report.orgs[plan.org],
    )
    if row is None:
        raise DemoSeedError(f"no engagement for {plan.proposal} with {plan.org}: its Pitch did not open one")
    return UUID(str(row.id)), EngagementState(row.state)


async def drive(
    owner: AsyncEngine, actors: Actors, settings: Settings, plan: DemoEngagement, report: DemoReport
) -> None:
    """Drive ``plan``'s engagement to its target (see the module docstring)."""
    engagement_id, state = await _engagement(owner, report, plan)
    driver = Driver(owner, actors, report, plan, engagement_id)
    for _ in range(MAX_TURNS):
        if state == plan.target:
            return
        found = await driver.next_step(state, deals=settings.feature_deals_enabled)
        if found is None:
            report.notes.append(
                f"{plan.proposal} with {plan.org} stopped at {state.value}: FEATURE_DEALS_ENABLED is off"
            )
            return
        actor, command = found
        state = EngagementState((await driver.run(actor, command, await driver.body(command)))["state"])
        report.did(f"{plan.proposal} with {plan.org}: {command} -> {state.value}")
    raise DemoSeedError(f"{plan.proposal} with {plan.org}: {plan.target.value} not reached in {MAX_TURNS} steps")
