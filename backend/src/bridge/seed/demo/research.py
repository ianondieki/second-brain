"""Demo seed steps for the research agent (P11; REQ-RES-01): the demo staff admin and one approved research card per
saved-excerpt niche, so the demo shows cards even with no LLM provider configured.

**The staff admin** (``data.STAFF_ADMIN``) is an account like the organisations' seats: created as the app creates a
user, with the reminders consent (every demo account holds it), then flagged by the owner role with ``staff_role``
admin (no application path sets a staff role) and ``demo_account`` (``owner_facts``, D-37). Its TOTP is enrolled by
the seed's normal enrolment step (``accounts.enrol_totp``: the pending secret is sealed by the auth service's own
helper and confirmed through ``POST /api/auth/totp/confirm``); this module never writes a secret.

**The cards** go through the real code path, with one difference: the model is replaced by ``SeededExampleClient``,
a fixed answer written in code below (``SEEDED_ANSWERS``, drafted by hand from the saved excerpts). The staff admin's
run is started with ``start_run``, executed by ``execute_run`` with ``origin=SEEDED_EXAMPLE`` (every check in code
applies: verbatim supporting text, numbers inside quotes, the named-organisation and source rules, the confidence
formula; nothing reaches a model and no ``llm_calls`` row is written, since nothing is called), and approved by the
staff admin signed in to the in-process API (``POST /api/admin/research/candidates/{id}/decision``: the publish
checks, then ``app_moderate_problem``). The cards' sources carry ``excerpt_ref`` ``example:<id>``, so every card says
"Seeded example for the demo (not a live AI result), human-reviewed on <date>" instead of "AI-drafted" (the problem
API's label; ``seeded_example: true`` in the admin and public responses): a seeded card is never presented as a live
AI result.

Idempotent and safe on a used demo (P9's rules): a niche that already has a seeded card of the demo staff admin (any
status: an admin may have rejected it in the app) gets nothing new; a seeded card still awaiting review is approved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.auth import passwords
from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm.client import BatchHandle, BatchItem, BatchPoll
from bridge.llm.errors import LLMConfigError
from bridge.llm.types import CallContext, LLMOutput, Message, Result, TokenUsage
from bridge.models.enums import ConsentPurpose
from bridge.problems.research import synthesis
from bridge.problems.research.pipeline import EXAMPLE_REF_PREFIX, CardOrigin, execute_run, start_run
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import get_catalogue
from bridge.profiles.consents import record_decisions
from bridge.seed.demo.data import DEMO_PASSWORD, DemoStaff
from bridge.seed.demo.runtime import SEED_METHOD, Actors, DemoReport, DemoSeedError, _execute, _one, _user_id_of

SEEDED_EXAMPLE_MODEL: Final = "seeded-example"  # Result.model of the fixed answer: never a provider's model

# Written by hand from the saved excerpts (backend/seed/research_excerpts.yaml), one card per niche. They name no
# organisation (D-45) and use only figures the cited quotes carry; the checks in code verify both on every seed run.
SEEDED_ANSWERS: Final[Mapping[str, Mapping[str, Any]]] = {
    "networks-telecommunications": {
        "title": "Smaller operators struggle with call termination charges",
        "statement": (
            "Smaller mobile operators say the termination rate regime disadvantages them. The regulator's glide path"
            " takes the rate from Sh0.41 to Sh0.3 per minute by March 2029, while the market leader still held 89"
            " percent of mobile money in December 2025. Operators and their customers need cheaper ways to connect"
            " calls and payments across networks."
        ),
        "affected_group": "Smaller mobile operators and their customers",
        "citations": (
            ("ke-tel-001", "share in the mobile money market had slimmed to 89 percent"),
            ("ke-tel-002", "decline from the previous Sh0.41 to Sh0.37"),
            ("ke-tel-004", "the current MTR regime disproportionately disadvantages smaller operators"),
        ),
    },
    "agriculture": {
        "title": "Drought losses squeeze grain farmers and national food stocks",
        "statement": (
            "Crop failure in key grain-growing areas is expected to cut national food production by between 30 and 40"
            " per cent this year. The government plans to import 25 million 90-kilogramme bags of maize, and"
            " subsidised fertiliser sells at KSh 2,000 per 50 kilogram bag. Farmers need better ways to plan planting,"
            " inputs and stock after dry spells."
        ),
        "affected_group": "Grain farmers in drought-hit areas",
        "citations": (
            ("ke-agr-001", "national food production projected to decline by between 30 and 40 per cent"),
            ("ke-agr-002", "import 25 million 90-kilogramme bags of maize"),
            ("ke-agr-003", "farmers will access the fertiliser at KSh 2,000 per 50 kilogram bag"),
        ),
    },
    "health": {
        "title": "Clinics must move claims onto the national digital health system",
        "statement": (
            "Healthcare providers are required to integrate their systems with the national digital health"
            " infrastructure for electronic claims, and all Level 4 public facilities must submit new claims only"
            " through the new platform. Facilities that miss the deadline for the 2026\u20132029 contracting cycle"
            " cannot serve beneficiaries. Smaller providers need simple, affordable ways to integrate and submit"
            " claims correctly."
        ),
        "affected_group": "Clinics and small hospitals",
        "citations": (
            ("ke-hlt-003", "integrate their systems with the national digital health infrastructure"),
            ("ke-hlt-004", "fail to execute new agreements under the 2026\u20132029 contracting cycle"),
            (
                "ke-hlt-005",
                "all Level 4 public healthcare facilities will be required to submit new claims exclusively",
            ),
        ),
    },
    "microfinance-saccos": {
        "title": "SACCOs need affordable cyber security and reporting tools",
        "statement": (
            "Regulated SACCOs held Sh1.21 trillion in assets after a 12.5 percent increase. Their regulator's talks"
            " with deposit-taking SACCOs focused on the quality of regulatory data, financial reporting and"
            " cybersecurity, as it works to protect members' funds in an increasingly technology-driven sector. Many"
            " SACCOs lack affordable tools for both."
        ),
        "affected_group": "Deposit-taking SACCOs and their members",
        "citations": (
            ("ke-sac-001", "total assets held by regulated Saccos to Sh1.21 trillion"),
            ("ke-sac-004", "quality of regulatory data, financial reporting, audit concerns, cybersecurity"),
            ("ke-sac-003", "protecting SACCO members\u2019 funds in an increasingly technology-driven"),
        ),
    },
}


def seeded_answer(niche: str) -> synthesis.ResearchSynthesis:
    card = SEEDED_ANSWERS[niche]
    draft = synthesis.ProblemDraft(
        title=card["title"],
        statement=card["statement"],
        affected_group=card["affected_group"],
        named_orgs=[],
        citations=[synthesis.DraftCitation(excerpt_id=i, supporting_text=t) for i, t in card["citations"]],
    )
    return synthesis.ResearchSynthesis(injection_suspected=False, problems=[draft])


class SeededExampleClient:
    """An ``LLMClient`` that answers the research call with a fixed answer written in code: no model, no provider, no
    ledger row (nothing is called). Only for ``execute_run(origin=SEEDED_EXAMPLE)``, which refuses outside dev and
    test; it answers nothing else."""

    def __init__(self, answer: synthesis.ResearchSynthesis) -> None:
        self._answer = answer

    async def complete[OutputT: LLMOutput](
        self,
        task: str,
        messages: Sequence[Message],
        schema: type[OutputT],
        *,
        ctx: CallContext,
        tools: Sequence[Mapping[str, Any]] | None = None,
        effort: str | None = None,
        cache_breakpoints: Sequence[int] | None = None,
    ) -> Result[OutputT]:
        if task != synthesis.TASK or schema is not synthesis.ResearchSynthesis or tools:
            raise LLMConfigError("the seeded example answers the research call only")
        result = Result(
            parsed=self._answer,
            stop_reason="seeded_example",
            usage=TokenUsage(),
            citations=(),
            model=SEEDED_EXAMPLE_MODEL,
            cost_usd=Decimal(0),
            attempts=0,
            trace_id=ctx.trace_id or "seeded-example",
        )
        return cast(Result[OutputT], result)

    async def batch_submit(
        self, task: str, items: Sequence[BatchItem], schema: type[LLMOutput], *, ctx: CallContext
    ) -> BatchHandle:
        raise LLMConfigError("the seeded example has no batches")

    async def batch_poll[OutputT: LLMOutput](self, handle: BatchHandle, schema: type[OutputT]) -> BatchPoll[OutputT]:
        raise LLMConfigError("the seeded example has no batches")


# ------------------------------------------------------------------------------------------------------ the admin


async def ensure_staff(
    owner: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    staff: DemoStaff,
    report: DemoReport,
) -> None:
    """The staff account (as the app creates a user, with the reminders consent) and, as the owner role, its staff
    role. ``owner_facts`` flags it ``demo_account`` and ``enrol_totp`` enrols its TOTP, as for every demo account."""
    user_id = await _user_id_of(owner, staff.email)
    if user_id is None:
        user_id = uuid7()
        async with factory() as db:
            db.add(
                User(
                    id=user_id,
                    email=staff.email,
                    password_hash=await passwords.hash_password_async(DEMO_PASSWORD),
                    display_name=staff.display_name,
                    locale="en",
                    email_verified_at=clock.utcnow(),
                )
            )
            await db.flush()
            await bind_tenant(db, user_id=user_id)
            await record_decisions(
                db, settings, user_id=user_id, decisions={ConsentPurpose.REMINDERS: True}, source=SEED_METHOD
            )
            await db.commit()
        report.did(f"account {staff.email}")
    changed = await _execute(
        owner,
        "UPDATE users SET staff_role = CAST(:role AS staff_role), updated_at = now()"
        " WHERE id = :id AND staff_role IS DISTINCT FROM CAST(:role AS staff_role)",
        id=user_id,
        role=staff.role.value,
    )
    if changed:
        report.did(f"{staff.email} staff {staff.role.value}")
    report.users[staff.email] = user_id


# ------------------------------------------------------------------------------------------------------- the cards

_SEEDED_CARD: Final = (
    "SELECT p.id, p.status::text AS status FROM problems p JOIN research_runs r ON r.id = p.research_run_id"
    " JOIN niches n ON n.id = r.niche_id WHERE n.slug = :niche AND r.started_by = :admin"
    " AND EXISTS (SELECT 1 FROM problem_sources s WHERE s.problem_id = p.id AND s.excerpt_ref LIKE :prefix)"
    " ORDER BY p.created_at LIMIT 1"
)


async def _create_card(
    factory: async_sessionmaker[AsyncSession], settings: Settings, admin_id: UUID, niche: str
) -> UUID:
    catalogue, policy = get_catalogue(), get_research_policy()
    async with factory() as db:
        await bind_tenant(db, user_id=admin_id)
        run = await start_run(db, user_id=admin_id, niche_slug=niche, country="KE", catalogue=catalogue)
        outcome = await execute_run(
            db,
            run.id,
            client=SeededExampleClient(seeded_answer(niche)),
            settings=settings,
            catalogue=catalogue,
            policy=policy,
            origin=CardOrigin.SEEDED_EXAMPLE,
        )
        if outcome is None or len(outcome.candidates) != 1:
            await db.rollback()
            reasons = None if outcome is None else list(outcome.discarded)
            raise DemoSeedError(f"the seeded {niche} research card failed the checks ({reasons})")
        await db.commit()
        return outcome.candidates[0]


async def seed_research_card(
    owner: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    actors: Actors,
    settings: Settings,
    staff: DemoStaff,
    niche: str,
    report: DemoReport,
) -> None:
    """One approved seeded research card for ``niche`` (see the module docstring)."""
    admin_id = report.users.get(staff.email)
    if admin_id is None:
        raise DemoSeedError(f"no demo staff admin {staff.email}")
    found = await _one(owner, _SEEDED_CARD, niche=niche, admin=admin_id, prefix=f"{EXAMPLE_REF_PREFIX}%")
    if found is not None and found.status != "candidate":
        return  # published, or decided otherwise in the app: left as it is
    problem_id = UUID(str(found.id)) if found is not None else await _create_card(factory, settings, admin_id, niche)
    if found is None:
        report.did(f"research card {niche} (seeded example)")
    actor = await actors.get(staff.email)
    await actor.call("POST", f"/api/admin/research/candidates/{problem_id}/decision", json={"decision": "approve"})
    report.did(f"research card {niche} approved by {staff.email}")


def seeded_niches() -> tuple[str, ...]:
    return tuple(SEEDED_ANSWERS)


__all__ = ["SEEDED_ANSWERS", "SeededExampleClient", "ensure_staff", "seed_research_card", "seeded_niches"]
