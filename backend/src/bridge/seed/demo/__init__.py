"""The demo seed: ``python -m bridge.seed --demo`` (P9 ``make demo``; REQ-FND-02, REQ-DIR-02).

Loads ``bridge.seed.demo.data`` on top of the reference data: two demo developers, four fixture organisations with
their seats, four published proposals (Tier 1 and Tier 2, each registered with a certificate id), the problems they
describe or link, and their tags (delivered to the E2 fixtures, held for the E1 and E0 ones). Dev and test only
(``demo_refusal``): staging and production refuse it, and so does an ``APP_ENV`` left to the settings default.

Everything that has an application path goes through it, in process: the accounts through ``create_account`` (what
signup runs), D1 through the phone-code routes with the fake SMS provider, TOTP through ``POST /api/auth/totp/confirm``
(only the random secret of enrolment is replaced by the account's fixed demo secret), members added by the
organisation's owner under Row-Level Security, the Master Enterprise Terms accepted by the signatory under RLS, and
drafts, publishing (which queues the T2.4 registration), pitching and the Evaluation NDA through the API. The rest has
no application path yet and is written as the owner role, as staff would: ``users.demo_account`` (D-37), D2, the
organisations' E1/E2 verification with their domain, niches and county, and the E0 fixture itself. Each party signs
in through the login routes with the demo password and its TOTP code. Engagements beyond ``SUBMITTED`` and reminders
follow when P5 and P6 merge.

Idempotent: every step looks for what it would create (by address, organisation name, proposal title) and skips what
exists, so running it twice changes nothing. A database seeded under other keys (``DATA_ENCRYPTION_KEY``) is refused
with a pointer to ``make demo-reset``.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings
from bridge.seed.demo.accounts import (
    accept_master_terms,
    enrol_totp,
    ensure_developer,
    ensure_org,
    owner_facts,
    raise_to_d2,
    verify_phone,
)
from bridge.seed.demo.data import DEVELOPERS, EXPORTED_PROPOSAL, ORGS, PROPOSALS
from bridge.seed.demo.proposals import ensure_proposal, pitch, record_view
from bridge.seed.demo.runtime import (
    Actors,
    DemoReport,
    DemoRuntime,
    DemoSeedError,
    DemoSeedRefused,
    demo_refusal,
    ensure_demo_allowed,
    in_process_app,
    niche_ids,
    one,
    totp_code,
)

__all__ = [
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
    """Load the demo dataset (idempotent). ``owner_engine`` logs in as bridge_owner, ``app_engine`` as bridge_app."""
    ensure_demo_allowed(settings)
    runtime = runtime or DemoRuntime.from_settings(settings)
    report = DemoReport()
    niches = await niche_ids(owner_engine)
    missing = sorted(({o.niche for o in ORGS} | {p.niche for p in PROPOSALS}) - set(niches))
    if missing:
        raise DemoSeedError(f"niches {missing} are missing: run the reference seed (python -m bridge.seed) first")
    async with in_process_app(settings, app_engine, runtime) as (app, factory), AsyncExitStack() as stack:
        for dev in DEVELOPERS:
            await ensure_developer(owner_engine, factory, settings, dev, report)
        for org in ORGS:
            await ensure_org(owner_engine, factory, settings, org, report)
        await owner_facts(owner_engine, niches, report)
        for email in report.users:
            await enrol_totp(app, owner_engine, factory, settings, email, report)
        actors = Actors(stack, app, owner_engine)  # each signs in (password, then TOTP) on first use
        for dev in DEVELOPERS:
            await verify_phone(owner_engine, actors, dev, runtime.sms_provider, report)
            await raise_to_d2(owner_engine, dev, report)
        for org in ORGS:
            await accept_master_terms(owner_engine, factory, org, report)
        for proposal in PROPOSALS:
            await ensure_proposal(owner_engine, actors, proposal, niches, report)
        for proposal in PROPOSALS:
            await pitch(owner_engine, actors, proposal, report)
        await record_view(owner_engine, actors, settings, report)
    return report


async def exported_cert_id(owner_engine: AsyncEngine) -> str | None:
    """The certificate id of the exported demo proposal (E2E_VERIFY_CERT_ID), or None before the demo seed ran."""
    row = await one(
        owner_engine,
        "SELECT v.cert_id FROM proposals p JOIN users u ON u.id = p.owner_id"
        " JOIN proposal_versions v ON v.id = p.current_version_id"
        " WHERE u.email = :email AND p.title = :title AND p.status = 'published'",
        email=EXPORTED_PROPOSAL.owner,
        title=EXPORTED_PROPOSAL.title,
    )
    return None if row is None else str(row.cert_id)


async def registration_status(owner_engine: AsyncEngine, cert_id: str) -> str | None:
    """How far the T2.4 registration of a certificate got (hashed, signed, timestamped), or None before hashing."""
    row = await one(owner_engine, "SELECT status::text AS status FROM provenance_records WHERE cert_id = :c", c=cert_id)
    return None if row is None else str(row.status)
