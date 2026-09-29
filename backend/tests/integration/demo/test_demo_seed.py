"""The demo seed (P9 ``make demo``; REQ-FND-02, REQ-DIR-02): ``python -m bridge.seed --demo`` on its own database.

Given the reference data, when the demo seed runs (twice), then: nothing changes the second time; every demo account
is flagged ``demo_account`` (D-37) with the reminders consent and TOTP on its fixed demo secret, whose helper codes
verify; the developers are D1 and D2; the fixture organisations carry their levels, seats and (E2) the signatory's
Master Enterprise Terms; the proposals are published with a certificate id each, their problems described or linked,
their registration queued and completed by the real T2.4 steps; E2 fixtures get delivered tags (a ``SUBMITTED``
engagement each), E1 and E0 held ones; the exported certificate id is P1's. Staging, production and an unset
``APP_ENV`` write nothing. The database is the module's own (the seed's rows would disturb the directory tests'
counts in the shared session database).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.auth.models import User
from bridge.auth.passwords import verify_password
from bridge.auth.service import check_second_factor
from bridge.config import Settings, get_settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.db import create_session_factory
from bridge.demo import __main__ as demo_command
from bridge.integrations.sms import FakeSmsProvider
from bridge.notifications.email import FakeEmailProvider
from bridge.provenance import service as provenance
from bridge.provenance.signing import LocalSigner, register_public_key
from bridge.provenance.tsa import TsaClient
from bridge.seed.demo import (
    DemoReport,
    DemoRuntime,
    DemoSeedError,
    DemoSeedRefused,
    exported_cert_id,
    registration_status,
    seed_demo,
    totp_code,
)
from bridge.seed.demo.data import (
    AMINA,
    BRIAN,
    COUNTY_C,
    DEMO_PASSWORD,
    NGO_D,
    ORGS,
    P1,
    P2,
    P3,
    P4,
    PROPOSALS,
    SACCO_B,
    TELCO_A,
    VIEWED,
    all_accounts,
)
from bridge.seed.reference import seed_all
from bridge.storage.objects import InMemoryObjectStore
from bridge.storage.scanner import FakeScanner
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.openssl_tsa import LocalTsa

TABLES = (
    "users",
    "organizations",
    "memberships",
    "developer_profiles",
    "consents",
    "legal_acceptances",
    "proposals",
    "proposal_versions",
    "problems",
    "tags",
    "engagements",
    "disclosure_grants",
    "nda_acceptances",
    "document_views",
    "procrastinate_jobs",
)


@pytest.fixture(scope="module")
def demo_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_demo_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def owner(demo_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(demo_url, "bridge_owner")
    async with engine.begin() as conn:
        await seed_all(conn, get_settings())
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def app(demo_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(demo_url, "bridge_app")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
def runtime() -> DemoRuntime:
    return DemoRuntime(
        email_provider=FakeEmailProvider(),
        sms_provider=FakeSmsProvider(),
        key_wrapper=LocalKeyWrapper(os.urandom(32)),
        object_store=InMemoryObjectStore(),
        scanner=FakeScanner(),
    )


def demo_settings(**update: Any) -> Settings:
    return get_settings().model_copy(update={"feature_tier2_enabled": True, **update})


@pytest.fixture(scope="module")
async def seeded(owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime) -> tuple[DemoReport, DemoReport]:
    """The demo seed, run twice: (first report, second report)."""
    first = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    second = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    return first, second


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def counts(engine: AsyncEngine) -> dict[str, int]:
    return {table: int((await rows(engine, f"SELECT count(*) FROM {table}"))[0][0]) for table in TABLES}


# ------------------------------------------------------------------------------------------------ idempotency


async def test_running_the_demo_seed_again_changes_nothing(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    first, second = seeded
    assert first.created, "the first run seeds"
    assert second.created == []
    assert (second.users, second.orgs, second.proposals, second.cert_ids) == (
        first.users,
        first.orgs,
        first.proposals,
        first.cert_ids,
    )
    before = await counts(owner)
    third = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    assert third.created == []
    assert await counts(owner) == before


@pytest.mark.parametrize("app_env", ["production", "staging"])
async def test_staging_and_production_refuse_the_demo_seed_and_write_nothing(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime, app_env: str
) -> None:
    before = await counts(owner)
    with pytest.raises(DemoSeedRefused, match=f"APP_ENV={app_env}"):
        await seed_demo(demo_settings(app_env=app_env), owner_engine=owner, app_engine=app, runtime=runtime)
    assert await counts(owner) == before


async def test_an_app_env_left_to_the_default_refuses_the_demo_seed(
    owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    settings = demo_settings()
    unset = type(settings).model_construct(_fields_set=set(settings.model_fields_set) - {"app_env"}, **dict(settings))
    before = await counts(owner)
    with pytest.raises(DemoSeedRefused, match="APP_ENV is not set"):
        await seed_demo(unset, owner_engine=owner, app_engine=app, runtime=runtime)
    assert await counts(owner) == before


# ---------------------------------------------------------------------------------------------------- accounts


async def test_every_demo_account_is_flagged_demo_with_reminders_and_totp(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    emails = [email for email, _, _ in all_accounts()]
    found = await rows(
        owner,
        "SELECT u.email::text, u.demo_account, u.totp_enabled_at IS NOT NULL AS totp,"
        " u.email_verified_at IS NOT NULL AS verified,"
        " (SELECT c.granted FROM consents c WHERE c.user_id = u.id AND c.purpose = 'reminders'"
        "  ORDER BY c.created_at DESC, c.id DESC LIMIT 1) AS reminders"
        " FROM users u WHERE u.email = ANY(:emails)",
        emails=emails,
    )
    assert sorted(r.email for r in found) == sorted(emails)
    assert all(r.demo_account and r.totp and r.verified and r.reminders for r in found), found
    others = await rows(owner, "SELECT count(*) FROM users WHERE demo_account AND NOT (email = ANY(:e))", e=emails)
    assert others[0][0] == 0


async def test_the_demo_password_signs_in_and_the_totp_helper_codes_verify(
    seeded: tuple[DemoReport, DemoReport], app: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = get_settings()
    later = time.time() + 30  # the next window: enrolment spent the current one (replay protection)
    async with create_session_factory(app)() as db:
        for email, _, _ in all_accounts():
            user = (await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).scalar_one()
            row = await db.get(User, user)
            assert row is not None
            assert verify_password(row.password_hash, DEMO_PASSWORD), email
            code = totp_code(email, at=later)
            wrong = code[:-1] + str((int(code[-1]) + 1) % 10)
            assert not check_second_factor(settings, row, wrong), email
            assert check_second_factor(settings, row, code), email
        await db.rollback()  # the spent counters stay unspent for the next test
    assert demo_command.main(["totp", TELCO_A.seats[0].email]) == 0
    assert capsys.readouterr().out.strip() == totp_code(TELCO_A.seats[0].email)
    assert demo_command.main(["totp"]) == 0
    listing = capsys.readouterr().out
    assert all(email in listing for email, _, _ in all_accounts())
    assert demo_command.main(["totp", "someone@else.example"]) == 2


async def test_a_database_seeded_under_other_keys_is_refused_with_the_reset_pointer(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    other = SecretStr("b3RoZXItZGF0YS1rZXktMDEyMzQ1Njc4OWFiY2RlZjA=")  # base64 of 32 other bytes
    with pytest.raises(DemoSeedError, match="demo-reset"):
        await seed_demo(demo_settings(data_encryption_key=other), owner_engine=owner, app_engine=app, runtime=runtime)


async def test_the_developers_are_d1_and_d2_through_the_phone_flow(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    levels = dict(
        await rows(
            owner,
            "SELECT u.email::text, p.verification_level::text FROM developer_profiles p"
            " JOIN users u ON u.id = p.user_id WHERE u.email IN (:a, :b)",
            a=AMINA.email,
            b=BRIAN.email,
        )
    )
    assert levels == {AMINA.email: "d2", BRIAN.email: "d1"}
    verified = await rows(owner, "SELECT count(*) FROM phone_verifications WHERE verified_at IS NOT NULL")
    assert verified[0][0] == 2  # D1 came through the phone-code flow, once per developer


# ------------------------------------------------------------------------------------------------ organisations


async def test_the_fixture_organisations_have_their_levels_seats_and_terms(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    report = seeded[0]
    for org in ORGS:
        assert org.legal_name.endswith("(fixture)")
        found = (
            await rows(
                owner,
                "SELECT legal_name, verification::text AS level, verified_domain::text AS domain, county_code,"
                " (SELECT array_agg(n.slug::text) FROM org_niches o JOIN niches n ON n.id = o.niche_id"
                "  WHERE o.org_id = organizations.id) AS niches"
                " FROM organizations WHERE id = :id",
                id=report.orgs[org.legal_name],
            )
        )[0]
        assert (found.legal_name, found.level, found.domain, found.county_code, found.niches) == (
            org.legal_name,
            org.verification.value,
            org.domain,
            org.county,
            [org.niche],
        )
        members = {
            email: sorted(roles)
            for email, roles in await rows(
                owner,
                "SELECT u.email::text, m.roles::text[] FROM memberships m JOIN users u ON u.id = m.user_id"
                " WHERE m.org_id = :org AND m.status = 'active'",
                org=report.orgs[org.legal_name],
            )
        }
        seats = ([org.owner] if org.owner else []) + list(org.seats)
        assert members == {seat.email: sorted(r.value for r in seat.roles) for seat in seats}
    terms = await rows(
        owner,
        "SELECT o.legal_name, u.email::text FROM legal_acceptances a JOIN organizations o ON o.id = a.org_id"
        " JOIN users u ON u.id = a.user_id"
        " WHERE a.legal_template_id = app_current_legal_template('master_enterprise_terms')",
    )
    assert sorted(terms) == sorted(
        [(TELCO_A.legal_name, TELCO_A.seats[0].email), (SACCO_B.legal_name, SACCO_B.seats[0].email)]
    )


# ---------------------------------------------------------------------------------------------------- proposals


async def test_the_proposals_are_published_with_certificates_and_problems(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    report = seeded[0]
    assert set(report.cert_ids) == {p.key for p in PROPOSALS}
    assert len(set(report.cert_ids.values())) == len(PROPOSALS)
    for proposal in PROPOSALS:
        found = (
            await rows(
                owner,
                "SELECT p.status::text AS status, p.moderation_state::text AS moderation, v.cert_id, v.status::text AS"
                " version, u.email::text AS owner, (SELECT array_agg(pr.title) FROM proposal_problems pp"
                " JOIN problems pr ON pr.id = pp.problem_id WHERE pp.proposal_version_id = v.id) AS problems"
                " FROM proposals p JOIN proposal_versions v ON v.id = p.current_version_id"
                " JOIN users u ON u.id = p.owner_id WHERE p.id = :id",
                id=report.proposals[proposal.key],
            )
        )[0]
        assert (found.status, found.moderation, found.version, found.owner) == (
            "published",
            "clear",
            "registered",
            proposal.owner,
        )
        assert found.cert_id == report.cert_ids[proposal.key]
        source = proposal if proposal.new_problem else next(p for p in PROPOSALS if p.key == proposal.links_problem_of)
        assert source.new_problem is not None
        assert found.problems == [source.new_problem.title]
    assert P4.links_problem_of == P1.key
    queued = await rows(owner, "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t", t=provenance.TASK_HASH)
    assert queued[0][0] == len(PROPOSALS)  # publishing queued each registration once, however often the seed ran


async def test_the_exported_certificate_registers_through_the_real_pipeline(
    seeded: tuple[DemoReport, DemoReport],
    owner: AsyncEngine,
    app: AsyncEngine,
    runtime: DemoRuntime,
    demo_url: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cert_id = await exported_cert_id(owner)
    assert cert_id == seeded[0].cert_ids[P1.key]
    assert await registration_status(owner, cert_id) is None  # queued, not yet run (the worker's job)

    signer = LocalSigner(os.urandom(32))
    async with owner.begin() as conn:
        await register_public_key(conn, signer)
    local_tsa = LocalTsa.create(tmp_path)
    tsa = TsaClient([local_tsa.endpoint("http://tsa.test/tsr")], transport=local_tsa.transport())
    version, owner_id = (
        await rows(
            owner,
            "SELECT v.id, p.owner_id FROM proposal_versions v JOIN proposals p ON p.id = v.proposal_id"
            " WHERE v.cert_id = :c",
            c=cert_id,
        )
    )[0]
    factory = create_session_factory(app)
    async with factory() as session:
        wrapper, store = runtime.key_wrapper, runtime.object_store
        assert await provenance.hash_manifest(session, version, owner_id, wrapper=wrapper, store=store)
    async with factory() as session:
        assert await provenance.sign_manifest(session, version, owner_id, signer=signer)
    assert await registration_status(owner, cert_id) == "signed"

    owner_url = demo_url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    settings = get_settings().model_copy(update={"database_owner_url": SecretStr(owner_url)})
    monkeypatch.setattr(demo_command, "get_settings", lambda: settings)
    # The command runs its own event loop (asyncio.run), as from a shell: give it a thread without one.
    assert await asyncio.to_thread(demo_command.main, ["cert-id", "--wait", "5"]) == 0
    assert capsys.readouterr().out.strip() == cert_id

    async with factory() as session:
        assert await provenance.timestamp_manifest(session, version, owner_id, tsa=tsa)
    assert await registration_status(owner, cert_id) == "timestamped"


# ------------------------------------------------------------------------------------------------------- pitch


async def test_e2_fixtures_get_delivered_tags_and_the_others_held_ones(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine, runtime: DemoRuntime
) -> None:
    report = seeded[0]
    tags = {
        (key, org): status
        for proposal in PROPOSALS
        for key in [proposal.key]
        for org, status in await rows(
            owner,
            "SELECT o.legal_name, t.status::text FROM tags t JOIN organizations o ON o.id = t.org_id"
            " WHERE t.proposal_id = :p",
            p=report.proposals[proposal.key],
        )
    }
    assert tags == {
        (P1.key, SACCO_B.legal_name): "delivered",
        (P2.key, TELCO_A.legal_name): "delivered",
        (P3.key, COUNTY_C.legal_name): "held_pending_verification",
        (P3.key, NGO_D.legal_name): "held_unclaimed",
    }
    engagements = await rows(
        owner,
        "SELECT o.legal_name, e.state::text FROM engagements e JOIN organizations o ON o.id = e.org_id",
    )
    assert sorted(engagements) == [(SACCO_B.legal_name, "SUBMITTED"), (TELCO_A.legal_name, "SUBMITTED")]
    grants = await rows(owner, "SELECT count(*) FROM disclosure_grants WHERE status = 'active'")
    assert grants[0][0] == 2
    assert isinstance(runtime.email_provider, FakeEmailProvider)
    receipts = [m for m in runtime.email_provider.outbox if m.to == AMINA.email and m.tag == "em1"]
    assert len(receipts) == 2  # one EM1 per pitch that delivered


async def test_a_fixture_reviewer_has_opened_p1_so_who_has_seen_it_is_not_empty(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    proposal, org, reviewer = VIEWED
    report = seeded[0]
    views = await rows(
        owner,
        "SELECT u.email::text FROM document_views d JOIN users u ON u.id = d.viewer_user_id"
        " WHERE d.proposal_id = :p AND d.org_id = :o",
        p=report.proposals[proposal.key],
        o=report.orgs[org.legal_name],
    )
    assert [v[0] for v in views] == [reviewer.email]


async def test_without_the_tier2_flag_the_view_is_skipped_and_said(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    again = await seed_demo(
        demo_settings(feature_tier2_enabled=False), owner_engine=owner, app_engine=app, runtime=runtime
    )
    assert again.created == []
    assert again.notes == ["Tier-2 view skipped: FEATURE_TIER2_ENABLED is off"]


def test_every_proposal_owner_and_pitched_organisation_is_in_the_dataset() -> None:
    developers = {AMINA.email, BRIAN.email}
    names = {org.legal_name for org in ORGS}
    for proposal in PROPOSALS:
        assert proposal.owner in developers
        assert set(proposal.pitch_to) <= names
        assert (proposal.new_problem is None) != (proposal.links_problem_of is None)
