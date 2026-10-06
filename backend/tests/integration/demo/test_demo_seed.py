"""The demo seed (P9 ``make demo``; REQ-FND-02, REQ-DIR-02): ``python -m bridge.seed --demo`` on its own database.

Given the reference data, when the demo seed runs (twice), then: nothing changes the second time; every demo account
is flagged ``demo_account`` (D-37) with the reminders consent and TOTP on its fixed demo secret, whose helper codes
verify; the developers are D1 and D2; the fixture organisations carry their levels, seats and (E2) the signatory's
Master Enterprise Terms; the proposals are published with a certificate id each, their problems described or linked,
their registration queued and completed by the real T2.4 steps; E2 fixtures get delivered tags (a ``SUBMITTED``
engagement each), E1 and E0 held ones; the exported certificate id is P1's; P21's beats (a thread on Amina's
engagement with SACCO B, a shortlist entry at Telco A, a saved search of Amina's) are made through the API once, and
P22's Today's five has two seeded sets (yesterday and today) with Amina's two attempts and Brian's one, no model called.
Staging, production and an unset ``APP_ENV`` write nothing. The database is the module's own (the seed's rows would
disturb the directory tests' counts in the shared session database).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import date, timedelta
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
from bridge.engagements import message_notify, notify
from bridge.integrations.sms import FakeSmsProvider
from bridge.models.enums import EngagementState
from bridge.notifications.email import FakeEmailProvider
from bridge.proposals.sanitise import contact_codes
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
    SAVED_SEARCH,
    STAFF_ADMIN,
    STAFF_MODERATOR,
    TELCO_A,
    THREAD,
    VIEWED,
    all_accounts,
    totp_secret,
)
from bridge.seed.demo.events import DEMO_EVENTS, PUBLISHED_TRENDS, SEEDED_TRENDS
from bridge.seed.demo.follow_ups import SHORTLISTED
from bridge.seed.demo.queues import CLAIMED, HELD
from bridge.seed.demo.quiz import SEEDED_SETS, nairobi_today
from bridge.seed.demo.research import SEEDED_ANSWERS
from bridge.seed.demo.runtime import in_process_app, signed_in
from bridge.seed.demo.scouts import SCOUT_KEYWORDS, SCOUT_NICHE, SCOUTED
from bridge.seed.demo.trending import LIKED
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
    "engagement_messages",
    "org_shortlist",
    "saved_searches",
    "quiz_sets",
    "quiz_questions",
    "quiz_attempts",
    "quiz_profiles",
    "events",
    "event_reminders",
    "trend_cards",
    "trend_card_sources",
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


def quiz_lines(today: date) -> list[str]:
    """What the first run of the quiz steps reports (P22)."""
    yesterday = (today - timedelta(days=1)).isoformat()
    return [
        f"quiz set {yesterday} (seeded)",
        f"quiz set {yesterday} approved (a past day, by the owner role)",
        f"quiz set {today.isoformat()} (seeded)",
        f"quiz set {today.isoformat()} approved by {STAFF_ADMIN.email}",
        f"quiz attempt of {AMINA.email} on {yesterday}",
        f"quiz attempt of {AMINA.email} on {today.isoformat()}",
        f"quiz attempt of {BRIAN.email} on {today.isoformat()}",
    ]


def this_week_lines() -> list[str]:
    """What the first run of This week's steps reports (P22 track B), after the quiz's."""
    admin = STAFF_ADMIN.email
    lines = []
    for event in DEMO_EVENTS:
        lines.append(f"event {event.key}: {event.title}")
        if event.publish:
            lines.append(f"event {event.key} published by {admin}")
        if event.reminded_by is not None:
            lines.append(f"county of {event.reminded_by}: {event.county}")
            lines.append(f"reminder of {event.reminded_by} on {event.key}")
    for trend in SEEDED_TRENDS:
        lines.append(f"trend card {trend.topic_slug}: {trend.title}")
        if trend.topic_slug in PUBLISHED_TRENDS:
            lines.append(f"trend card {trend.topic_slug} published by {admin}")
    return lines


async def counts(engine: AsyncEngine) -> dict[str, int]:
    return {table: int((await rows(engine, f"SELECT count(*) FROM {table}"))[0][0]) for table in TABLES}


# ------------------------------------------------------------------------------------------------ idempotency


async def test_running_the_demo_seed_again_changes_nothing(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    first, second, third = seeded
    assert first.created, "the first run seeds"
    week = len(this_week_lines())
    assert first.created[-10 - week : -7 - week] == [  # P21's beats, then P22's quiz and This week, last
        f"thread of {THREAD.proposal} with {THREAD.org}: {len(THREAD.messages)} messages",
        f"shortlist of {SHORTLISTED[1].legal_name}: {SHORTLISTED[0].key} by {SHORTLISTED[2].email}",
        f"saved search of {SAVED_SEARCH.owner}: {SAVED_SEARCH.name}",
    ]
    assert first.created[-7 - week : -week] == quiz_lines(await nairobi_today(owner))
    assert first.created[-week:] == this_week_lines()
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
    # P10's scout step publishes one more (bridge.seed.demo.scouts), P15's queues one held for moderation (.queues).
    published = (*PROPOSALS, SCOUTED, HELD)
    assert set(report.cert_ids) == {p.key for p in published}
    assert len(set(report.cert_ids.values())) == len(published)
    for proposal in published:
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
            "held" if proposal is HELD else "clear",
            "registered",
            proposal.owner,
        )
        assert found.cert_id == report.cert_ids[proposal.key]
        source = proposal if proposal.new_problem else next(p for p in PROPOSALS if p.key == proposal.links_problem_of)
        assert source.new_problem is not None
        assert found.problems == [source.new_problem.title]
    assert P4.links_problem_of == P1.key
    queued = await rows(owner, "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t", t=provenance.TASK_HASH)
    assert queued[0][0] == len(published)  # publishing queued each registration once, however often the seed ran


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


# ------------------------------------------------------------------------------------------------------ scouts


async def test_telco_a_has_a_scout_whose_first_scan_matched_the_untagged_proposal(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """M2 walkthrough step 1 (P10): Telco A's weekly scout, made through the API by its owner, matched Brian's
    untagged fifth proposal (and nothing else) in one in-process scan, rules only; its reviewer got the EM3 digest
    once however often the seed ran, and the signatory may express interest from the match at once."""
    report = seeded[0]
    org, reviewer = report.orgs[TELCO_A.legal_name], TELCO_A.seats[1].email
    assert TELCO_A.owner is not None
    [scout] = await rows(
        owner,
        "SELECT id, created_by, frequency::text AS frequency, niches, include_keywords, recipients, paused_at"
        " FROM scout_agents WHERE org_id = :o",
        o=org,
    )
    niche = (await rows(owner, "SELECT id FROM niches WHERE slug = :s", s=SCOUT_NICHE))[0].id
    assert (scout.created_by, scout.frequency, scout.niches, scout.paused_at) == (
        report.users[TELCO_A.owner.email],
        "weekly",
        [niche],
        None,
    )
    assert (scout.include_keywords, scout.recipients) == (list(SCOUT_KEYWORDS), [report.users[reviewer]])
    scout_runs = await rows(
        owner, "SELECT trigger::text, status::text, matched_count FROM agent_runs WHERE scout_id = :s", s=scout.id
    )
    assert [tuple(r) for r in scout_runs] == [("weekly", "completed", 1)]  # the first scan only
    [match] = await rows(
        owner,
        "SELECT id, proposal_id, score, rule_breakdown, rationale_demo_fallback, digest_sent_at FROM agent_matches"
        " WHERE scout_id = :s",
        s=scout.id,
    )
    assert (match.proposal_id, match.score, match.rationale_demo_fallback) == (report.proposals[SCOUTED.key], 90, False)
    assert (match.rule_breakdown["why_source"], match.rule_breakdown["why_reason"]) == ("code", "not_eligible")
    assert match.digest_sent_at is not None
    assert SCOUTED.pitch_to == ()
    assert await rows(owner, "SELECT id FROM tags WHERE proposal_id = :p", p=match.proposal_id) == []
    assert isinstance(runtime.email_provider, FakeEmailProvider)
    digests = [m for m in runtime.email_provider.outbox if m.tag == "em3"]
    assert [m.to for m in digests] == [reviewer]
    assert SCOUTED.title in digests[0].text
    async with (
        in_process_app(demo_settings(), app, runtime) as (demo_app, _),
        signed_in(demo_app, owner, TELCO_A.seats[0].email) as signatory,
    ):
        page = (await signatory.call("GET", f"/api/orgs/{org}/matches/{match.id}")).json()
    assert (page["available"], page["engagement_id"]) == (True, None)
    assert page["interest"] == {"allowed": True, "reason": None}


# ------------------------------------------------------------------------------------------------ staff queues


async def test_each_staff_queue_has_an_item_for_the_demo_moderator_and_admin(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """M2 walkthrough step 6 (P15): the demo staff moderator (TOTP through the enrolment path) finds Amina's held P6
    in the moderation queue, filed by the pre-screen when she published it through the API, and may approve or reject
    it; the demo staff admin finds County C's E2 claim, written by its owner under RLS, in the claims queue with its
    review SLA. The moderator has no claims queue."""
    report = seeded[0]
    [staff] = await rows(
        owner,
        "SELECT staff_role::text AS role, demo_account, totp_enabled_at IS NOT NULL AS totp FROM users WHERE id = :id",
        id=report.users[STAFF_MODERATOR.email],
    )
    assert (staff.role, staff.demo_account, staff.totp) == ("moderator", True, True)
    assert HELD.pitch_to == ()
    async with in_process_app(demo_settings(), app, runtime) as (demo_app, _):
        async with signed_in(demo_app, owner, STAFF_MODERATOR.email) as moderator:
            cases = (await moderator.call("GET", "/api/admin/moderation/cases")).json()["items"]
            await moderator.call("GET", "/api/admin/claims", expect=(403,))
        async with signed_in(demo_app, owner, STAFF_ADMIN.email) as admin:
            claims = (await admin.call("GET", "/api/admin/claims")).json()
    [held] = [case for case in cases if case["subject_id"] == str(report.proposals[HELD.key])]
    assert (held["subject_type"], held["subject_state"], held["reasons"], held["source"]) == (
        "proposal",
        "held",
        ["names_real_org_negative"],
        "regex",
    )
    assert (held["flagged_fields"], held["actions"], held["blocked"]) == (
        ["problem_statement"],
        ["approve", "reject"],
        None,
    )
    problems = [case["preview"]["title"] for case in cases if case["subject_type"] == "problem"]
    described = [p.new_problem.title for p in (*PROPOSALS, SCOUTED, HELD) if p.new_problem is not None]
    assert sorted(problems) == sorted(described)  # every developer-reported problem waits for review, once
    assert CLAIMED.owner is not None
    [claim] = claims["items"]
    assert (claim["org"]["legal_name"], claim["claimant"]["display_name"]) == (
        CLAIMED.legal_name,
        CLAIMED.owner.display_name,
    )
    assert (claim["domain"], claim["level"], claim["status"], claim["dispute_case_id"]) == (
        CLAIMED.domain,
        "e2",
        "pending_review",
        None,
    )
    assert claims["review_sla_bd"] == 2
    assert claim["sla"]["overdue"] is False
    assert 0 < claim["sla"]["business_days_left"] <= 2  # filed today (2 left), or yesterday if midnight passed
    [filed] = await rows(owner, "SELECT count(*) FROM org_claims")
    assert filed[0] == 1  # the re-runs filed nothing more


# ------------------------------------------------------------------------------------------------------ P21 beats


async def test_amina_and_sacco_b_have_an_open_thread_with_a_reply_waiting(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P21 (REQ-ENG-11): SACCO B's owner, its named contact, and Amina wrote on the thread of her P1 engagement through
    the API, alternating and in order, once however often the seed ran; each post was audited and queued its N18 job
    (the worker writes the bell rows and the email). Amina reads the thread open, the owner's two messages unread."""
    report = seeded[0]
    assert SACCO_B.owner is not None
    assert (THREAD.proposal, THREAD.org, P1.owner) == (P1.key, SACCO_B.legal_name, AMINA.email)
    [engagement] = await rows(
        owner,
        "SELECT id, state::text AS state FROM engagements WHERE proposal_id = :p AND org_id = :o",
        p=report.proposals[THREAD.proposal],
        o=report.orgs[THREAD.org],
    )
    assert engagement.state == EngagementState.NEGOTIATION.value
    david, amina = report.users[SACCO_B.owner.email], report.users[AMINA.email]
    posted = await rows(
        owner,
        "SELECT sender_user_id, sender_party::text AS party, body FROM engagement_messages WHERE engagement_id = :e"
        " ORDER BY created_at, id",
        e=engagement.id,
    )
    bodies = [message.body for message in THREAD.messages]
    assert [tuple(m) for m in posted] == [
        (david, "org", bodies[0]),
        (amina, "developer", bodies[1]),
        (david, "org", bodies[2]),
    ]
    assert all(contact_codes(body) == [] for body in bodies)  # D-57 (8) holds at every stage
    others = await rows(owner, "SELECT count(*) FROM engagement_messages WHERE engagement_id <> :e", e=engagement.id)
    assert others[0][0] == 0
    audited = await rows(
        owner,
        "SELECT actor_user_id FROM audit_events WHERE action = 'engagement.message_posted' AND subject_id = :e",
        e=engagement.id,
    )
    assert sorted(str(a.actor_user_id) for a in audited) == sorted(str(u) for u in (david, amina, david))
    queued = await rows(
        owner,
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t AND args->>'engagement_id' = :e",
        t=message_notify.TASK,
        e=str(engagement.id),
    )
    assert queued[0][0] == len(bodies)
    async with (
        in_process_app(demo_settings(), app, runtime) as (demo_app, _),
        signed_in(demo_app, owner, AMINA.email) as developer,
    ):
        thread = (await developer.call("GET", f"/api/engagements/{engagement.id}/messages")).json()
    assert (thread["status"], thread["can_post"], thread["unread"]) == ("open", True, 2)
    assert [(item["mine"], item["body"]) for item in thread["items"]] == [
        (False, bodies[0]),
        (True, bodies[1]),
        (False, bodies[2]),
    ]


async def test_telco_a_reviewer_shortlisted_the_scouts_match(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P21 (REQ-REPO-02): Telco A's reviewer, who gets the scout's digest, put its match on the organisation's
    shortlist through the API, once (one row, one ``shortlist.added`` event); every member reads who added it."""
    report = seeded[0]
    proposal, org, reviewer = SHORTLISTED
    assert (proposal, org, reviewer) == (SCOUTED, TELCO_A, TELCO_A.seats[1])
    org_id, proposal_id, reviewer_id = (
        report.orgs[org.legal_name],
        report.proposals[proposal.key],
        report.users[reviewer.email],
    )
    entries = await rows(owner, "SELECT org_id, proposal_id, added_by FROM org_shortlist")
    assert [tuple(e) for e in entries] == [(org_id, proposal_id, reviewer_id)]
    audited = await rows(
        owner, "SELECT org_id, actor_user_id, subject_id FROM audit_events WHERE action = 'shortlist.added'"
    )
    assert [tuple(a) for a in audited] == [(org_id, reviewer_id, proposal_id)]
    async with (
        in_process_app(demo_settings(), app, runtime) as (demo_app, _),
        signed_in(demo_app, owner, TELCO_A.seats[2].email) as finance,  # a member without a Tier-2 role reads it
    ):
        listed = (await finance.call("GET", f"/api/orgs/{org_id}/shortlist")).json()
    [item] = listed["items"]
    assert (item["proposal_id"], item["available"], item["title"]) == (str(proposal_id), True, proposal.title)
    assert (item["added_by_id"], item["added_by_name"]) == (str(reviewer_id), reviewer.display_name)


async def test_amina_has_a_saved_search_whose_view_lists_seeded_problems(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P21 (REQ-PERS-03): Amina saved, through the API and once, a Problems search of a niche she likes, alerts on and
    never alerted yet; Discover lists seeded problems for it (P1's among them), so opening it is never empty."""
    report = seeded[0]
    assert SAVED_SEARCH.owner == AMINA.email
    assert SAVED_SEARCH.niche in LIKED[AMINA.email]
    found = await rows(
        owner, "SELECT user_id, name, view, niche_slug, county_code, words, alerts, last_alerted_at FROM saved_searches"
    )
    assert [tuple(f) for f in found] == [
        (report.users[AMINA.email], SAVED_SEARCH.name, "problems", SAVED_SEARCH.niche, None, None, True, None)
    ]
    async with (
        in_process_app(demo_settings(), app, runtime) as (demo_app, _),
        signed_in(demo_app, owner, AMINA.email) as amina,
    ):
        saved = (await amina.call("GET", "/api/me/saved-searches")).json()
        shown = (await amina.call("GET", "/api/discover/trending", params={"niche": SAVED_SEARCH.niche})).json()
    assert [(s["name"], s["view"], s["niche"], s["alerts"]) for s in saved["items"]] == [
        (SAVED_SEARCH.name, SAVED_SEARCH.view, SAVED_SEARCH.niche, True)
    ]
    assert P1.new_problem is not None
    assert P1.new_problem.title in {p["problem"]["title"] for p in shown["problems"]}


async def test_todays_five_has_two_seeded_sets_and_three_attempts(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P22 (REQ-DEV-01; card test A8): yesterday's and today's sets are seeded, hand-written (the checks in code
    passed), today's approved by the demo staff admin through the API (audited) and yesterday's by the owner role
    (the API approves no set of a past day), once however often the seed ran; Amina
    finished both (4 and 5 of 5: a streak of 2, on the board), Brian today's (3 of 5, not on the board); no model was
    called."""
    report = seeded[0]
    today = await nairobi_today(owner)
    yesterday = today - timedelta(days=1)
    admin, amina, brian = (report.users[e] for e in (STAFF_ADMIN.email, AMINA.email, BRIAN.email))
    sets = await rows(
        owner, "SELECT id, quiz_date, status, origin, decided_by, llm_trace_id FROM quiz_sets ORDER BY quiz_date"
    )
    assert [tuple(s)[1:] for s in sets] == [
        (yesterday, "approved", "seeded", None, None),  # a past day's set: the owner role approves it
        (today, "approved", "seeded", admin, None),
    ]
    for found, written in zip(sets, (SEEDED_SETS["yesterday"], SEEDED_SETS["today"]), strict=True):
        questions = await rows(
            owner,
            "SELECT prompt, answer, source_id FROM quiz_questions WHERE set_id = :s ORDER BY position",
            s=found.id,
        )
        assert [tuple(q) for q in questions] == [(q.prompt, q.answer, q.source_id) for q in written]
    decided = await rows(owner, "SELECT actor_user_id FROM audit_events WHERE action = 'quiz.set_decided'")
    assert [d.actor_user_id for d in decided] == [admin]
    attempts = await rows(
        owner,
        "SELECT a.user_id, s.quiz_date, a.score FROM quiz_attempts a JOIN quiz_sets s ON s.id = a.set_id"
        " ORDER BY s.quiz_date, a.score DESC",
    )
    assert [tuple(a) for a in attempts] == [(amina, yesterday, 4), (amina, today, 5), (brian, today, 3)]
    profiles = await rows(
        owner, "SELECT user_id, current_streak, best_streak, last_played_on, leaderboard_opt_in FROM quiz_profiles"
    )
    assert sorted(tuple(p) for p in profiles) == sorted([(amina, 2, 2, today, True), (brian, 1, 1, today, False)])
    assert await rows(owner, "SELECT id FROM llm_calls WHERE trace_id LIKE 'quiz:%'") == []
    async with in_process_app(demo_settings(), app, runtime) as (demo_app, _):
        async with signed_in(demo_app, owner, AMINA.email) as developer:
            played = (await developer.call("GET", "/api/me/quiz/today")).json()
            board = (await developer.call("GET", "/api/me/quiz/leaderboard")).json()
        async with signed_in(demo_app, owner, BRIAN.email) as other:
            brians = (await other.call("GET", "/api/me/quiz/leaderboard")).json()
    assert (played["attempt"]["score"], played["streak"], played["leaderboard_opt_in"]) == (
        5,
        {"current": 2, "best": 2},
        True,
    )
    same_week = yesterday.isocalendar()[:2] == today.isocalendar()[:2]  # on a Monday, yesterday was last week's
    assert [(r["rank"], r["points"], r["you"]) for r in board["rows"]] == [(1, 9 if same_week else 5, True)]
    assert brians["me"] == {"points": 3, "rank": 2, "opted_in": False, "played": True}


async def test_this_week_has_events_a_reminder_and_trend_cards(
    seeded: tuple[DemoReport, DemoReport, DemoReport], owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime
) -> None:
    """P22 (REQ-DEV-02; card test B7's data): four events posted through the API (Telco A's in Nairobi City, the staff
    admin's online one and SACCO B's in Machakos published by the demo staff admin on the version read, SACCO B's
    online draft on the queue), once however often the seed ran; Amina in Nairobi City with her Remind me on the
    Nairobi one; three hand-written trend cards stored through app_create_trend_candidate with no generating call,
    two published by the staff admin; no model called. Amina's strip shows the Nairobi and online events, not
    Machakos, and a trend labelled a seeded example; Brian (no county) sees the online one."""
    report = seeded[0]
    admin, amina = report.users[STAFF_ADMIN.email], report.users[AMINA.email]
    events = await rows(
        owner,
        "SELECT e.id, e.title, e.org_id, e.status, e.county_code, e.online, e.created_by FROM events e ORDER BY title",
    )
    by_title = {event.title: event for event in events}
    assert len(events) == len(DEMO_EVENTS)
    for plan in DEMO_EVENTS:
        found = by_title[plan.title]
        assert (found.status, found.county_code, found.online) == (
            "published" if plan.publish else "draft",
            plan.county,
            plan.county is None,
        )
        assert found.org_id == (None if plan.org is None else report.orgs[plan.org])
        assert found.created_by == report.users[plan.poster]
    decided = await rows(owner, "SELECT actor_user_id, payload FROM audit_events WHERE action = 'event.decided'")
    assert [(d.actor_user_id, d.payload["decision"]) for d in decided] == [(admin, "publish")] * 3
    nairobi = by_title[DEMO_EVENTS[0].title]
    reminders = await rows(owner, "SELECT user_id, event_id FROM event_reminders")
    assert [tuple(r) for r in reminders] == [(amina, nairobi.id)]
    assert (await rows(owner, "SELECT county_code FROM developer_profiles WHERE user_id = :u", u=amina))[0][0] == (
        "KE-30"
    )
    cards = await rows(owner, "SELECT id, title, topic_slug, status, llm_trace_id FROM trend_cards ORDER BY title")
    assert sorted((c.topic_slug, c.status, c.llm_trace_id) for c in cards) == [
        ("databases", "published", None),
        ("kenya-ict", "candidate", None),
        ("security", "published", None),
    ]
    refs = await rows(owner, "SELECT DISTINCT excerpt_ref FROM trend_card_sources ORDER BY excerpt_ref")
    assert [r.excerpt_ref for r in refs] == ["tr-dat-002", "tr-ke-002", "tr-sec-001"]
    trend_decisions = await rows(owner, "SELECT actor_user_id FROM audit_events WHERE action = 'trend.card_decided'")
    assert [d.actor_user_id for d in trend_decisions] == [admin, admin]
    assert await rows(owner, "SELECT id FROM llm_calls WHERE trace_id LIKE 'trends:%'") == []
    async with in_process_app(demo_settings(), app, runtime) as (demo_app, _):
        async with signed_in(demo_app, owner, AMINA.email) as developer:
            strip = (await developer.call("GET", "/api/me/week")).json()
        async with signed_in(demo_app, owner, BRIAN.email) as other:
            his = (await other.call("GET", "/api/me/week")).json()
    shown = {event["title"]: event for event in strip["events"]}
    assert set(shown) == {DEMO_EVENTS[0].title, DEMO_EVENTS[1].title}
    assert (shown[DEMO_EVENTS[0].title]["reminder"], shown[DEMO_EVENTS[1].title]["organiser"]) == (True, "Platform")
    assert strip["reminders_email"] in {"on", "unverified"}
    assert strip["trend"]["seeded_example"] is True
    assert strip["trend"]["title"] in {t.title for t in SEEDED_TRENDS if t.topic_slug in PUBLISHED_TRENDS}
    assert [event["title"] for event in his["events"]] == [DEMO_EVENTS[1].title]


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
    monkeypatch.setattr(demo_command, "_app_engine", lambda _: role_engine(demo_url, "bridge_app"))
    try:
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "2", "--hours", "3"]) == 0
        moved = capsys.readouterr().out
        assert "offset 2 days, 3:00:00" in moved
        assert "tracker clock: 0 engagement(s) expired, 0 hold(s) resumed" in moved  # nothing is due yet
        offset = await rows(owner, "SELECT extract(epoch FROM clock_offset) FROM test_clock")
        assert int(offset[0][0]) == (2 * 24 + 3) * 3600
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "400"]) == 1  # at most 366 days
        unchanged = await rows(owner, "SELECT extract(epoch FROM clock_offset) FROM test_clock")
        assert int(unchanged[0][0]) == (2 * 24 + 3) * 3600  # the refused move left the offset as it was
        # A month on, the pass expires at once what nobody moved: Brian's pitch to Telco A (SUBMITTED, 20 BD) and
        # SACCO B's approval of Brian's other proposal (INTEREST_CONFIRMED, 10 BD); negotiation does not expire.
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "30"]) == 0
        assert "tracker clock: 2 engagement(s) expired, 0 hold(s) resumed" in capsys.readouterr().out
        ended = await rows(owner, "SELECT state::text, end_reason::text FROM engagements WHERE state = 'EXPIRED'")
        assert sorted(tuple(row) for row in ended) == [("EXPIRED", "CONTACT_NOT_MADE"), ("EXPIRED", "NO_REVIEW")]
        async with owner.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = false"))
        assert await asyncio.to_thread(demo_command.main, ["clock", "--days", "1"]) == 1  # not where disabled
        assert "did not move" in capsys.readouterr().err
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = interval '0'"))
