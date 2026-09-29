"""The demo seed on a demo that was used (P9 review MAJOR; REQ-FND-02): ``make demo`` runs the seed on every start.

Given a demo seeded with the feature flags off (as CI's stack once ran it) and then on, when people use it in the app
(the Telco A reviewer starts review of Brian's P3 and the signatory declines it, Amina changes her password, Brian
turns two-step sign-in off) and the demo starts again, then the seed step (``python -m bridge.seed --demo``) exits 0,
adds nothing and changes nothing they did: each engagement it did not open in that run is left where it is, with one
line in the report. Own database: the actions end engagements for good.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.auth.passwords import verify_password
from bridge.config import Settings, get_settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.integrations.sms import FakeSmsProvider
from bridge.notifications.email import FakeEmailProvider
from bridge.seed import __main__ as seed_command
from bridge.seed.demo import DemoReport, DemoRuntime, seed_demo
from bridge.seed.demo.data import AMINA, BRIAN, P1, P2, P3, SACCO_B, TELCO_A, VIEWED
from bridge.seed.demo.runtime import in_process_app, signed_in
from bridge.seed.reference import SEED_TABLES, seed_all
from bridge.storage.objects import InMemoryObjectStore
from bridge.storage.scanner import FakeScanner
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic

NEW_PASSWORD = "amina-changed-it-in-the-app"
TELCO_REVIEWER, TELCO_SIGNATORY = TELCO_A.seats[1].email, TELCO_A.seats[0].email


@pytest.fixture(scope="module")
def used_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_demo_used_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def owner(used_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(used_url, "bridge_owner")
    async with engine.begin() as conn:
        await seed_all(conn, get_settings())
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def app(used_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(used_url, "bridge_app")
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


def flags(on: bool) -> Settings:
    update = {"feature_tier2_enabled": on, "feature_deals_enabled": on}
    return get_settings().model_copy(update=update)


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def engagement(owner: AsyncEngine, report: DemoReport, proposal: str, org: str) -> Any:
    found = await rows(
        owner,
        "SELECT id, state::text AS state, lock_version FROM engagements WHERE proposal_id = :p AND org_id = :o",
        p=report.proposals[proposal],
        o=report.orgs[org],
    )
    return found[0]


@pytest.fixture(scope="module")
async def seeded(owner: AsyncEngine, app: AsyncEngine, runtime: DemoRuntime) -> tuple[DemoReport, DemoReport]:
    off = await seed_demo(flags(False), owner_engine=owner, app_engine=app, runtime=runtime)
    on = await seed_demo(flags(True), owner_engine=owner, app_engine=app, runtime=runtime)
    return off, on


async def test_with_the_flags_off_the_seed_stops_before_deal_steps_and_says_so(
    seeded: tuple[DemoReport, DemoReport],
) -> None:
    off, _ = seeded
    assert off.notes == [
        "Tier-2 view skipped: FEATURE_TIER2_ENABLED is off",
        f"{P1.key} with {SACCO_B.legal_name} stopped at CONTACT_MADE: FEATURE_DEALS_ENABLED is off",
        f"{P2.key} with {TELCO_A.legal_name} stopped at CONTACT_MADE: FEATURE_DEALS_ENABLED is off",
    ]


async def test_a_later_run_tops_up_but_never_drives_an_engagement_it_did_not_just_open(
    seeded: tuple[DemoReport, DemoReport], owner: AsyncEngine
) -> None:
    _, on = seeded
    assert on.created == [f"Tier-2 view of {P1.key} by {VIEWED[2].email}"]
    assert on.notes == [
        f"{P1.key} with {SACCO_B.legal_name} left at CONTACT_MADE (the seed only drives a new engagement)",
        f"{P2.key} with {TELCO_A.legal_name} left at CONTACT_MADE (the seed only drives a new engagement)",
    ]
    assert (await engagement(owner, on, P2.key, TELCO_A.legal_name)).state == "CONTACT_MADE"


async def test_the_seed_step_exits_0_and_changes_nothing_people_did_in_the_app(
    seeded: tuple[DemoReport, DemoReport],
    owner: AsyncEngine,
    app: AsyncEngine,
    runtime: DemoRuntime,
    used_url: URL,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = seeded[1]
    p3 = await engagement(owner, report, P3.key, TELCO_A.legal_name)
    assert p3.state == "SUBMITTED"
    async with in_process_app(flags(True), app, runtime) as (demo_app, _):
        path = f"/api/engagements/{p3.id}"
        async with signed_in(demo_app, owner, TELCO_REVIEWER) as reviewer:  # the advertised walk-through
            lock = (await reviewer.call("GET", path)).json()["lock_version"]
            await reviewer.call("POST", f"{path}/start-review", json={"lock_version": lock})
        async with signed_in(demo_app, owner, TELCO_SIGNATORY) as signatory:
            lock = (await signatory.call("GET", path)).json()["lock_version"]
            await signatory.call("POST", f"{path}/decline", json={"lock_version": lock, "reason": "NOT_PRIORITY"})
        async with signed_in(demo_app, owner, AMINA.email) as amina:
            body = {"current_password": "bridge-demo-2026", "new_password": NEW_PASSWORD}
            await amina.call("POST", "/api/auth/password", json=body, expect=(204,))
        async with signed_in(demo_app, owner, BRIAN.email) as brian:
            await brian.call("POST", "/api/auth/totp/disable", expect=(204,))
    before = await rows(
        owner,
        "SELECT (SELECT count(*) FROM engagement_events) AS events, (SELECT count(*) FROM proposals) AS proposals,"
        " (SELECT count(*) FROM tags) AS tags, (SELECT count(*) FROM audit_events) AS audit",
    )

    captured: list[DemoReport] = []
    owner_url = used_url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    settings = flags(True).model_copy(update={"database_owner_url": SecretStr(owner_url)})

    async def reference_seed(url: str, given: Settings) -> tuple[dict[str, int], None]:
        return dict.fromkeys(SEED_TABLES, 1), None

    async def demo_seed(url: str, given: Settings) -> DemoReport:
        # The command runs in its own thread and event loop (asyncio.run, as from the shell): engines of that loop.
        seed_owner, seed_app = role_engine(used_url, "bridge_owner"), role_engine(used_url, "bridge_app")
        try:
            captured.append(await seed_demo(given, owner_engine=seed_owner, app_engine=seed_app, runtime=runtime))
        finally:
            await seed_owner.dispose()
            await seed_app.dispose()
        return captured[-1]

    monkeypatch.setattr(seed_command, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_command, "run", reference_seed)
    monkeypatch.setattr(seed_command, "run_demo", demo_seed)
    assert await asyncio.to_thread(seed_command.main, ["--demo"]) == 0  # make demo's migrate step comes up
    again = captured[0]
    assert again.created == []
    assert f"{P3.key} with {TELCO_A.legal_name} left at DECLINED (the seed only drives a new engagement)" in again.notes
    assert "demo: already seeded (nothing to add)" in capsys.readouterr().out

    after = await rows(
        owner,
        "SELECT (SELECT count(*) FROM engagement_events) AS events, (SELECT count(*) FROM proposals) AS proposals,"
        " (SELECT count(*) FROM tags) AS tags, (SELECT count(*) FROM audit_events) AS audit",
    )
    assert after == before  # no event, proposal, tag or audit event added: nobody was even signed in
    assert (await engagement(owner, report, P3.key, TELCO_A.legal_name)).state == "DECLINED"
    amina_row = await rows(owner, "SELECT password_hash FROM users WHERE email = :e", e=AMINA.email)
    assert verify_password(amina_row[0].password_hash, NEW_PASSWORD)
    brian_row = await rows(owner, "SELECT totp_enabled_at, totp_secret_enc FROM users WHERE email = :e", e=BRIAN.email)
    assert tuple(brian_row[0]) == (None, None)  # left off
