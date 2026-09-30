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

from bridge.auth import totp
from bridge.auth.crypto import decode_key, decrypt
from bridge.auth.models import User
from bridge.auth.passwords import verify_password
from bridge.config import Settings, get_settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.db import create_session_factory
from bridge.demo import __main__ as demo_command
from bridge.engagements import notify
from bridge.integrations.sms import FakeSmsProvider
from bridge.models.enums import EngagementState
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
    ENGAGEMENTS,
    NGO_D,
    ORGS,
    P1,
    P2,
    P3,
    P4,
    PROPOSALS,
    SACCO_B,
    STAFF_ADMIN,
    TELCO_A,
    VIEWED,
    all_accounts,
    totp_secret,
)
from bridge.seed.demo.research import SEEDED_ANSWERS
from bridge.seed.demo.runtime import in_process_app, signed_in
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
    "signal_events",
    "developer_niches",
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
    """What make demo runs with: APP_ENV test here (dev there) and both feature flags on."""
    flags = {"feature_tier2_enabled": True, "feature_deals_enabled": True}
    return get_settings().model_copy(update={**flags, **update})


@pytest.fixture(scope="module")
async def seeded(
    owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> tuple[DemoReport, DemoReport, DemoReport]:
    """The demo seed as make demo runs it (both flags on), three times: the three reports."""
    first = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    second = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    third = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    return first, second, third


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def counts(engine: AsyncEngine) -> dict[str, int]:
    return {table: int((await rows(engine, f"SELECT count(*) FROM {table}"))[0][0]) for table in TABLES}


# ------------------------------------------------------------------------------------------------ idempotency


async def test_running_the_demo_seed_again_changes_nothing(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    first, second, third = seeded
    assert first.created, "the first run seeds"
    assert first.notes == []
    assert (second.created, second.notes, third.created, third.notes) == ([], [], [], [])
    assert (third.users, third.orgs, third.proposals, third.cert_ids) == (
        first.users,
        first.orgs,
        first.proposals,
        first.cert_ids,
    )
    before = await counts(owner)
    again = await seed_demo(demo_settings(), owner_engine=owner, app_engine=app, runtime=runtime)
    assert again.created == []
    assert again.notes == []
    assert await counts(owner) == before


@pytest.mark.parametrize("app_env", ["production", "staging"])
async def test_staging_and_production_refuse_the_demo_seed_and_write_nothing(
    seeded: tuple[DemoReport, DemoReport, DemoReport],
    owner: AsyncEngine,
    app: AsyncEngine,
    runtime: DemoRuntime,
    app_env: str,
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
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine
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
    seeded: tuple[DemoReport, DemoReport, DemoReport], app: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """The seed itself signed every party in with the password and a TOTP code (the engagements need both); here each
    enrolled secret is the demo one and the helper's current code verifies against it (codes are single use, so the
    check ignores the spent counter)."""
    key = decode_key(get_settings().data_encryption_key.get_secret_value())
    async with create_session_factory(app)() as db:
        for email, _, _ in all_accounts():
            user = (await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).scalar_one()
            row = await db.get(User, user)
            assert row is not None
            assert row.totp_secret_enc is not None
            assert verify_password(row.password_hash, DEMO_PASSWORD), email
            stored = decrypt(key, row.totp_secret_enc, row.id.bytes).decode("ascii")
            assert stored == totp_secret(email)
            code = totp_code(email)
            wrong = code[:-1] + str((int(code[-1]) + 1) % 10)
            assert totp.verify(stored, code, last_counter=None).ok, email
            assert not totp.verify(stored, wrong, last_counter=None).ok, email
            assert row.totp_last_counter is not None  # a code was spent: enrolment and the seed's sign-ins
    assert demo_command.main(["totp", TELCO_A.seats[0].email]) == 0
    assert capsys.readouterr().out.strip() == totp_code(TELCO_A.seats[0].email)
    assert demo_command.main(["totp"]) == 0
    listing = capsys.readouterr().out
    assert all(email in listing for email, _, _ in all_accounts())
    assert demo_command.main(["totp", "someone@else.example"]) == 2


async def test_a_database_seeded_under_other_keys_is_refused_with_the_reset_pointer(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    other = SecretStr("b3RoZXItZGF0YS1rZXktMDEyMzQ1Njc4OWFiY2RlZjA=")  # base64 of 32 other bytes
    with pytest.raises(DemoSeedError, match="demo-reset"):
        await seed_demo(demo_settings(data_encryption_key=other), owner_engine=owner, app_engine=app, runtime=runtime)


async def test_the_developers_are_d1_and_d2_through_the_phone_flow(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine
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
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine
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
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine
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
    seeded: tuple[DemoReport, DemoReport, DemoReport],
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
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, runtime: DemoRuntime
) -> None:
    report = seeded[0]
    tags = {
        (key, org): status
        for proposal in PROPOSALS
        for key in [proposal.key]
        for org, status in await rows(
            owner,
            "SELECT o.legal_name, t.status::text || CASE WHEN t.closed_at IS NULL THEN '' ELSE ' (closed)' END"
            " FROM tags t JOIN organizations o ON o.id = t.org_id WHERE t.proposal_id = :p",
            p=report.proposals[proposal.key],
        )
    }
    assert tags == {
        (P1.key, SACCO_B.legal_name): "delivered",
        (P2.key, TELCO_A.legal_name): "delivered (closed)",  # the tag closes with its CLOSED engagement
        (P3.key, COUNTY_C.legal_name): "held_pending_verification",
        (P3.key, NGO_D.legal_name): "held_unclaimed",
        (P3.key, TELCO_A.legal_name): "delivered",
        (P4.key, SACCO_B.legal_name): "delivered",
    }
    grants = await rows(owner, "SELECT count(*) FROM disclosure_grants WHERE status = 'active'")
    assert grants[0][0] == 4  # a CLOSED engagement keeps its organisation's access
    assert isinstance(runtime.email_provider, FakeEmailProvider)
    for developer in (AMINA, BRIAN):
        receipts = [m for m in runtime.email_provider.outbox if m.to == developer.email and m.tag == "em1"]
        assert len(receipts) == 2, developer.email  # one EM1 per Pitch that delivered


async def test_the_engagements_reach_their_stages_through_the_tracker(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    report = seeded[0]
    for plan in ENGAGEMENTS:
        found = (
            await rows(
                owner,
                "SELECT id, state::text AS state FROM engagements WHERE proposal_id = :p AND org_id = :o",
                p=report.proposals[plan.proposal],
                o=report.orgs[plan.org],
            )
        )[0]
        assert found.state == plan.target.value, plan
        chain = await rows(
            owner,
            "SELECT seq, command, to_state::text AS to_state FROM engagement_events WHERE engagement_id = :e"
            " ORDER BY seq",
            e=found.id,
        )
        assert [e.seq for e in chain] == list(range(1, len(chain) + 1))
        assert chain[0].to_state == "SUBMITTED"
        assert chain[-1].to_state == plan.target.value
    closed = next(p for p in ENGAGEMENTS if p.target == EngagementState.CLOSED)
    signed = await rows(
        owner,
        "SELECT s.document_kind::text, s.party::text, s.step_up_method::text FROM signatures s"
        " JOIN engagements e ON e.id = s.engagement_id WHERE e.proposal_id = :p",
        p=report.proposals[closed.proposal],
    )
    assert set(signed) == {
        (kind, party, "totp")
        for kind in ("mutual_nda", "agreement", "acceptance_certificate")
        for party in ("developer", "org")
    }
    paid = await rows(
        owner,
        "SELECT r.amount_kes_minor, r.confirmed_amount_kes_minor FROM payment_records r"
        " JOIN engagements e ON e.id = r.engagement_id WHERE e.proposal_id = :p",
        p=report.proposals[closed.proposal],
    )
    total = sum(m.amount_kes_minor for m in closed.milestones)
    assert [tuple(r) for r in paid] == [(total, total)]
    em2 = await rows(
        owner,
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t AND args->>'developer_id' = :d",
        t=notify.TASK,
        d=str(report.users[BRIAN.email]),
    )
    assert em2[0][0] >= 1  # INTEREST_CONFIRMED queued EM2 for Brian (the worker sends it to Mailpit)


async def test_a_fixture_reviewer_has_opened_p1_so_who_has_seen_it_is_not_empty(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine
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


# ---------------------------------------------------------------------------------------------------- research


async def test_the_staff_admin_approved_one_seeded_research_card_per_niche(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P11: a demo staff admin (staff_role admin, demo account, TOTP through the enrolment path) ran one research run
    per saved-excerpt niche on the fixed seeded answers and approved each card through the admin API. The cards cite
    the saved excerpts as seeded examples, no model was called, and the public card says it is a seeded example."""
    report = seeded[0]
    admin = report.users[STAFF_ADMIN.email]
    [staff] = await rows(
        owner,
        "SELECT staff_role::text AS role, demo_account, totp_enabled_at IS NOT NULL AS totp FROM users WHERE id = :id",
        id=admin,
    )
    assert (staff.role, staff.demo_account, staff.totp) == ("admin", True, True)
    cards = await rows(
        owner,
        "SELECT p.id, n.slug::text AS niche, p.status::text AS status, p.moderation_state::text AS moderation,"
        " p.moderator_id, p.ai_generated, r.status::text AS run, r.candidates, r.demo_fallback, r.searches, r.fetches,"
        " (SELECT array_agg(s.excerpt_ref ORDER BY s.excerpt_ref) FROM problem_sources s WHERE s.problem_id = p.id)"
        " AS refs FROM problems p JOIN research_runs r ON r.id = p.research_run_id JOIN niches n ON n.id = r.niche_id"
        " WHERE r.started_by = :admin",
        admin=admin,
    )
    assert sorted(c.niche for c in cards) == sorted(SEEDED_ANSWERS)
    for card in cards:
        assert (card.status, card.moderation, card.ai_generated) == ("published", "clear", True)
        assert card.moderator_id == admin
        assert (card.run, card.candidates, card.demo_fallback, card.searches, card.fetches) == (
            "completed",
            1,
            False,
            0,
            0,
        )
        assert card.refs == [f"example:{i}" for i, _ in sorted(SEEDED_ANSWERS[card.niche]["citations"])]
    calls = await rows(owner, "SELECT count(*) FROM llm_calls WHERE trace_id LIKE 'research:%'")
    assert calls[0][0] == 0  # nothing was called: the answers are the seed's own
    async with (
        in_process_app(demo_settings(), app, runtime) as (demo_app, _),
        signed_in(demo_app, owner, AMINA.email) as amina,
    ):
        shown = (await amina.call("GET", f"/api/problems/{cards[0].id}")).json()
    assert shown["seeded_example"] is True
    assert shown["ai_generated"] is False  # written in code, not by a model (P11 review minor d)
    assert shown["label"].startswith("Seeded example for the demo (not a live AI result), human-reviewed on ")
    assert "AI-drafted" not in shown["label"]
    assert len(shown["citations"]) == 3


# ---------------------------------------------------------------------------------------------------- trending


async def test_discover_and_recommendations_have_something_to_show(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P12: liked niches for both developers and Amina's profiling consent through the app, simulated signals from
    pseudonyms of no account; P2's problem trends with its project beside it, and both developers get explained
    recommendations (Amina's personalised, Brian's not)."""
    report = seeded[0]
    liked = await rows(
        owner,
        "SELECT u.email, count(*) AS n FROM developer_niches d JOIN users u ON u.id = d.user_id"
        " WHERE d.kind = 'liked' GROUP BY u.email",
    )
    assert {r.email: r.n for r in liked} == {AMINA.email: 3, BRIAN.email: 3}
    consents = await rows(
        owner,
        "SELECT u.email, c.granted, c.source FROM consents c JOIN users u ON u.id = c.user_id"
        " WHERE c.purpose = 'profiling'",
    )
    assert [(c.email, c.granted, c.source) for c in consents] == [(AMINA.email, True, "settings")]
    hashes = await rows(owner, "SELECT count(*) FROM signal_events WHERE kind IN ('scout_match', 'org_interest')")
    assert hashes[0][0] > 100
    async with (
        in_process_app(demo_settings(), app, runtime) as (demo_app, _),
        signed_in(demo_app, owner, AMINA.email) as amina,
        signed_in(demo_app, owner, BRIAN.email) as brian,
    ):
        trending = (await amina.call("GET", "/api/discover/trending")).json()
        mine = (await amina.call("GET", "/api/me/recommendations")).json()
        his = (await brian.call("GET", "/api/me/recommendations")).json()
    p2 = str(report.proposals[P2.key])
    [project] = [p for p in trending["projects"] if p["proposal"]["id"] == p2]
    assert project["trend"]["trending"] is True
    [problem] = [p for p in trending["problems"] if p["problem"]["id"] == project["problem"]["id"]]
    assert problem["trend"]["trending"] is True
    assert "4 companies scouting" in problem["trend"]["badge"]
    assert p2 in problem["project_ids"]
    assert (mine["personalised"], his["personalised"]) == (True, False)
    assert mine["items"]
    assert his["items"]
    assert all(i["why"] and i["pursuit"]["reasons"] for i in [*mine["items"], *his["items"]])


def test_every_proposal_owner_and_pitched_organisation_is_in_the_dataset() -> None:
    developers = {AMINA.email, BRIAN.email}
    names = {org.legal_name for org in ORGS}
    for proposal in PROPOSALS:
        assert proposal.owner in developers
        assert set(proposal.pitch_to) <= names
        assert (proposal.new_problem is None) != (proposal.links_problem_of is None)


async def test_the_clock_helper_moves_the_shared_clock_forward_only_where_enabled(
    seeded: tuple[DemoReport, DemoReport, DemoReport],
    owner: AsyncEngine,
    demo_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Last in the module: it moves the module database's clock (and puts it back as the owner)."""
    owner_url = demo_url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    settings = get_settings().model_copy(update={"database_owner_url": SecretStr(owner_url)})
    monkeypatch.setattr(demo_command, "get_settings", lambda: settings)
    try:
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "2", "--hours", "3"]) == 0
        assert "offset 2 days, 3:00:00" in capsys.readouterr().out
        offset = await rows(owner, "SELECT extract(epoch FROM clock_offset) FROM test_clock")
        assert int(offset[0][0]) == (2 * 24 + 3) * 3600
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "400"]) == 1  # at most 366 days
        unchanged = await rows(owner, "SELECT extract(epoch FROM clock_offset) FROM test_clock")
        assert int(unchanged[0][0]) == (2 * 24 + 3) * 3600  # the refused move left the offset as it was
        async with owner.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = false"))
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "1"]) == 1  # not where disabled
        assert "did not move" in capsys.readouterr().err
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = interval '0'"))
