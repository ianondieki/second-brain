"""The demo seed: ``python -m bridge.seed --demo`` (P9 ``make demo``; REQ-FND-02, REQ-DIR-02).

Loads ``bridge.seed.demo.data`` on top of the reference data: two demo developers, four fixture organisations with
their seats, four published proposals (Tier 1 and Tier 2, each registered with a certificate id), the problems they
describe or link, their tags (delivered to the E2 fixtures, held for the E1 and E0 ones) and the tracker at
``SUBMITTED``, ``INTEREST_CONFIRMED``, ``NEGOTIATION`` and ``CLOSED``. Dev and test only
(``demo_refusal``): staging and production refuse it, and so does an ``APP_ENV`` left to the settings default.

Everything that has an application path goes through it, in process: the accounts through ``create_account`` (what
signup runs), D1 through the phone-code routes with the fake SMS provider, TOTP through ``POST /api/auth/totp/confirm``
(only the random secret of enrolment is replaced by the account's fixed demo secret), members added by the
organisation's owner under Row-Level Security, the Master Enterprise Terms accepted by the signatory under RLS, and
drafts, publishing (which queues the T2.4 registration), pitching and the Evaluation NDA through the API. The rest has
no application path yet and is written as the owner role, as staff would: ``users.demo_account`` (D-37), D2, the
organisations' E1/E2 verification with their domain, niches and county, and the E0 fixture itself. The engagements
opened by the Pitch are then driven through the tracker API to a few stages (``bridge.seed.demo.engagements``), each
party signed in with the demo password and its TOTP code. Every account holds the reminders consent (P6). A demo
staff admin (P11) starts one research run per saved-excerpt niche and approves its card
(``bridge.seed.demo.research``): the cards come from a fixed answer written in code through the real checks and
approval, and are labelled seeded examples, never live AI results. Then every demo subject gets its side's free
plan (P14, ``bridge.seed.demo.subscriptions``), and Telco A gets a scout whose first scan matches Brian's untagged
fifth proposal (P10, ``bridge.seed.demo.scouts``). Last come P21's three beats (``bridge.seed.demo.follow_ups``), each
through the API: SACCO B's owner and Amina write three messages on the thread of her engagement with SACCO B, Telco A's
reviewer puts the scout's match on its shortlist, and Amina saves a Discover search of a niche she likes. Last, P22's
Today's five (``bridge.seed.demo.quiz``): two hand-written sets for yesterday and today, checked and stored as a model's
would be, today's approved by the demo staff admin (yesterday's by the owner role), with Amina's attempts on both (a
streak of 2, on the board) and Brian's on today's; no model is called. Then P22's This week
(``bridge.seed.demo.events``): four events posted through the API by Telco A's and SACCO B's reviewers and the staff
admin, three of them published by the staff admin on the queue (Nairobi City, online, Machakos) and one left a draft,
Amina's county and her Remind me on the Nairobi one, and three hand-written trend cards through the checks and
``app_create_trend_candidate``, two of them published by the staff admin; no model is called. Last, P22's Peers and
team up (``bridge.seed.demo.teams``): two more demo developers (Zawadi, Juma) signed up with the others; Amina, Brian
(in her county, two shared niches) and Zawadi (Mombasa, one shared niche) turn Peers on and Juma does not; Amina's
accepted invitation to Brian on P2's problem with a four-message thread, Brian credited on P2, and Zawadi's pending
invitation to Amina, each through the API. Last of all (P23-1), one pass of the embedding job
(``bridge.embeddings.worker``, the configured embedder: the fake in dev and test) as the unbound worker, so Amina's
profile (the only one with the profiling consent) and the readable problems have vectors for Recommended for you; what
it wrote goes to ``DemoReport.embedded``, and a later run writes only what changed since.

Idempotent, and safe on a demo that was used (``make demo`` runs it on every start): every step looks for what it
would create (by address, organisation name, a proposal's first title) and skips what exists, so running it twice
changes nothing. On a database the demo was seeded into before, a step the app refuses because someone used the demo
(a password or second factor changed, a proposal deleted, an engagement taken on or ended) is left as it is with one
line in the report instead of failing the start (``guarded``); only a new database treats refusals as errors. A
database seeded under other keys (``DATA_ENCRYPTION_KEY``) is refused with a pointer to ``make demo-reset``.
"""

from __future__ import annotations

from collections.abc import Awaitable
from contextlib import AsyncExitStack

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.config import Settings
from bridge.embeddings.worker import EmbeddingsRuntime, run_embeddings
from bridge.seed.demo.accounts import (
    accept_master_terms,
    enrol_totp,
    ensure_developer,
    ensure_org,
    owner_facts,
    raise_to_d2,
    verify_phone,
)
from bridge.seed.demo.data import (
    DEVELOPERS,
    ENGAGEMENTS,
    EXPORTED_PROPOSAL,
    ORGS,
    PEER_DEVELOPERS,
    PROPOSALS,
    STAFF,
    STAFF_ADMIN,
    DemoDeveloper,
    all_accounts,
)
from bridge.seed.demo.engagements import drive
from bridge.seed.demo.events import DEMO_EVENTS, ensure_event, ensure_trends
from bridge.seed.demo.follow_ups import ensure_saved_search, ensure_shortlisted, ensure_thread
from bridge.seed.demo.proposals import ensure_proposal, pitch, record_view
from bridge.seed.demo.queues import seed_queues
from bridge.seed.demo.quiz import PLAYS, ensure_play, ensure_sets, has_profile
from bridge.seed.demo.research import ensure_staff, seed_research_card, seeded_niches
from bridge.seed.demo.runtime import (
    Actors,
    DemoKeysChanged,
    DemoReport,
    DemoRuntime,
    DemoSeedError,
    DemoSeedRefused,
    _niche_ids,
    _one,
    demo_refusal,
    ensure_demo_allowed,
    guarded,
    in_process_app,
    totp_code,
)
from bridge.seed.demo.scouts import SCOUTED, ensure_scout
from bridge.seed.demo.subscriptions import seed_demo_subscriptions
from bridge.seed.demo.teams import ensure_contributor, ensure_peers, ensure_pending_invitation, ensure_team
from bridge.seed.demo.trending import seed_trending

__all__ = [
    "DemoKeysChanged",
    "DemoReport",
    "DemoRuntime",
    "DemoSeedError",
    "DemoSeedRefused",
    "demo_refusal",
    "ensure_demo_allowed",
    "exported_cert_id",
    "registration_status",
    "seed_demo",
    "totp_code",
]


async def seed_demo(
    settings: Settings, *, owner_engine: AsyncEngine, app_engine: AsyncEngine, runtime: DemoRuntime | None = None
) -> DemoReport:
    """Load the demo dataset (idempotent). ``owner_engine`` logs in as bridge_owner, ``app_engine`` as bridge_app.

    The steps run in the order the module docstring tells, ending with P21's beats (the message thread on Amina's
    engagement with SACCO B, Telco A's shortlist entry after its scout, whose match it is, and Amina's saved search)
    and P22's Today's five (the two sets, then each attempt), This week (the events, then the trend cards) and Peers
    and team up (the profiles, the team, the contributor, the pending invitation)."""
    ensure_demo_allowed(settings)
    runtime = runtime or DemoRuntime.from_settings(settings)
    report = DemoReport()
    niches = await _niche_ids(owner_engine)
    missing = sorted(({o.niche for o in ORGS} | {p.niche for p in PROPOSALS} | set(seeded_niches())) - set(niches))
    if missing:
        raise DemoSeedError(f"niches {missing} are missing: run the reference seed (python -m bridge.seed) first")
    strict = not await _seeded_before(owner_engine)  # a new database: every refusal is an error
    async with in_process_app(settings, app_engine, runtime) as (app, factory), AsyncExitStack() as stack:

        async def step(what: str, awaitable: Awaitable[None]) -> None:
            await guarded(report, strict=strict, what=what, step=awaitable)

        for dev in (*DEVELOPERS, *PEER_DEVELOPERS):
            await step(dev.email, ensure_developer(owner_engine, factory, settings, dev, report))
        for org in ORGS:
            await step(org.legal_name, ensure_org(owner_engine, factory, settings, org, report))
        for staff in STAFF:
            await step(staff.email, ensure_staff(owner_engine, factory, settings, staff, report))
        await step("owner-role facts", owner_facts(owner_engine, niches, report))
        for email in list(report.users):
            await step(f"TOTP of {email}", enrol_totp(app, owner_engine, factory, settings, email, report))
        actors = Actors(stack, app, owner_engine)  # each signs in (password, then TOTP) on first use
        for dev in DEVELOPERS:
            if dev.email in report.users:
                await step(f"{dev.email} verification", _verify(owner_engine, actors, dev, runtime, report))
        for org in ORGS:
            await step(f"{org.legal_name} terms", accept_master_terms(owner_engine, factory, org, report))
        for proposal in PROPOSALS:
            if proposal.owner in report.users:
                await step(proposal.key, ensure_proposal(owner_engine, actors, proposal, niches, report))
        for proposal in PROPOSALS:
            await step(f"{proposal.key} pitch", pitch(owner_engine, actors, proposal, report))
        await step("Tier-2 view", record_view(owner_engine, actors, settings, report))
        for plan in ENGAGEMENTS:
            await step(f"{plan.proposal} with {plan.org}", drive(owner_engine, actors, settings, plan, report))
        if STAFF_ADMIN.email in report.users:
            for niche in seeded_niches():
                card = seed_research_card(owner_engine, factory, actors, settings, STAFF_ADMIN, niche, report)
                await step(f"research card {niche}", card)
        await step("trending and liked niches", seed_trending(owner_engine, actors, niches, report))
        await step("free plans", _free_plans(owner_engine, settings))
        if SCOUTED.owner in report.users:
            await step(SCOUTED.key, ensure_proposal(owner_engine, actors, SCOUTED, niches, report))
        mail = runtime.email_provider
        await step("Telco A scout", ensure_scout(owner_engine, actors, factory, settings, mail, niches, report))
        await step("staff queues", seed_queues(owner_engine, actors, factory, niches, report))
        await step("message thread", ensure_thread(owner_engine, actors, report))
        await step("Telco A shortlist", ensure_shortlisted(owner_engine, actors, report))
        await step("saved search", ensure_saved_search(owner_engine, actors, report))
        await step("quiz sets", ensure_sets(owner_engine, actors, report))
        fresh = {play.email: not await has_profile(owner_engine, report.users.get(play.email)) for play in PLAYS}
        for play in PLAYS:
            attempt = ensure_play(owner_engine, actors, play, fresh[play.email], report)
            await step(f"quiz attempt of {play.email} ({play.day})", attempt)
        for event in DEMO_EVENTS:
            await step(f"event {event.key}", ensure_event(owner_engine, actors, event, report))
        await step("trend cards", ensure_trends(owner_engine, actors, report))
        await step("peers", ensure_peers(owner_engine, actors, niches, report))
        await step("team-up", ensure_team(owner_engine, actors, report))
        await step("contributor", ensure_contributor(owner_engine, actors, report))
        await step("pending team-up", ensure_pending_invitation(owner_engine, actors, report))
        await step("embeddings", _embeddings(settings, factory, report))
    return report


async def _embeddings(settings: Settings, factory: async_sessionmaker[AsyncSession], report: DemoReport) -> None:
    """P23-1: one pass of the embedding job (idempotent: the hashes say what is fresh)."""
    run = await run_embeddings(EmbeddingsRuntime(settings, factory=factory).deps())
    if run.unavailable:
        report.notes.append("embeddings: the configured embedder cannot run here; recommendations use keywords")
    for table in run.tables:
        if table.rows:
            report.embedded[table.table] = table.rows


async def _free_plans(owner_engine: AsyncEngine, settings: Settings) -> None:
    """P14: every demo subject without a live subscription gets its side's free plan (bought plans are kept)."""
    async with owner_engine.begin() as conn:
        await seed_demo_subscriptions(conn, settings)


async def _seeded_before(owner_engine: AsyncEngine) -> bool:
    """Whether any demo account exists already: then the demo may have been used, and the run only tops it up."""
    emails = [email for email, _, _ in all_accounts()]
    return await _one(owner_engine, "SELECT 1 FROM users WHERE email = ANY(:emails) LIMIT 1", emails=emails) is not None


async def _verify(
    owner: AsyncEngine, actors: Actors, dev: DemoDeveloper, runtime: DemoRuntime, report: DemoReport
) -> None:
    await verify_phone(owner, actors, dev, runtime.sms_provider, report)
    await raise_to_d2(owner, dev, report)


async def exported_cert_id(owner_engine: AsyncEngine) -> str | None:
    """The certificate id of the exported demo proposal (E2E_VERIFY_CERT_ID), or None before the demo seed ran."""
    row = await _one(
        owner_engine,
        "SELECT v.cert_id FROM proposals p JOIN users u ON u.id = p.owner_id"
        " JOIN proposal_versions v ON v.id = p.current_version_id"
        " WHERE u.email = :email AND p.status = 'published' AND EXISTS (SELECT 1 FROM proposal_versions f"
        " WHERE f.proposal_id = p.id AND f.version_no = 1 AND f.title = :title)",
        email=EXPORTED_PROPOSAL.owner,
        title=EXPORTED_PROPOSAL.title,
    )
    return None if row is None else str(row.cert_id)


async def registration_status(owner_engine: AsyncEngine, cert_id: str) -> str | None:
    """How far the T2.4 registration of a certificate got (hashed, signed, timestamped), or None before hashing."""
    row = await _one(
        owner_engine, "SELECT status::text AS status FROM provenance_records WHERE cert_id = :c", c=cert_id
    )
    return None if row is None else str(row.status)
