"""REQ-ENG-12 / REQ-BD-01: the dev/test clock router and the business-day deadlines it drives.

- Production has no test-clock route (404): the app does not mount it when ``APP_ENV=production`` or when the image
  left the module out, and the backend image leaves it out unless built with ``WITH_DEV_TOOLS=true``.
- In dev and test a signed-in user moves the shared clock forward (``app_set_test_clock``); in staging only staff
  admin may (everyone else 404); a database whose clock is not enabled refuses (409).
- Tracker deadlines are Kenyan business days on that clock: weekends and gazetted holidays are skipped, and the next
  command's times and deadline follow the moved clock.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import bridge.main
from bridge.config import BACKEND_DIR, Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, is_business_day, local_date
from bridge.engagements.policy import get_policy
from bridge.ids import uuid7
from bridge.main import create_app, dev_clock_router
from bridge.models.enums import EngagementState
from bridge.testclock import build_router
from tests.integration.api import make_client, sign_in_as
from tests.integration.engagements.api_world import Tracker, build, deals_on, open_engagement, seats

REPO = BACKEND_DIR.parent
CLOCK = "/api/test-clock"


def production() -> Settings:
    base = get_settings()
    return Settings(
        _env_file=None,
        app_env="production",
        database_url=base.database_url,
        secret_key=base.secret_key,
        data_encryption_key=base.data_encryption_key,
        recovery_code_pepper=base.recovery_code_pepper,
        email_provider="postmark",
        postmark_server_token=SecretStr("pm-test-token-not-real"),
        public_base_url="https://bridge.example",
        cookie_secure=True,
        embedder="bge-m3",
        llm_kill_switch=True,
    )


async def probe(settings: Settings) -> int:
    """GET /api/test-clock without signing in: 404 where the router is not mounted, 401 where it is."""
    app = create_app(settings)
    app.state.session_factory = create_session_factory(create_engine("postgresql+psycopg://probe@localhost/probe"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        return (await client.get(CLOCK)).status_code


async def test_the_production_app_has_no_test_clock_route() -> None:
    settings = production()
    assert await probe(settings) == 404
    assert dev_clock_router(settings) is None
    with pytest.raises(RuntimeError):
        build_router(settings)
    assert await probe(get_settings()) == 401  # the test app mounts it (sign-in required)


async def test_the_router_is_not_mounted_when_the_image_left_the_module_out(monkeypatch: pytest.MonkeyPatch) -> None:
    real = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> object:
        return None if name == bridge.main.TEST_CLOCK_MODULE else real(name, package)

    monkeypatch.setattr("importlib.util.find_spec", find_spec)
    assert dev_clock_router(get_settings()) is None
    assert await probe(get_settings()) == 404


REMOVAL = re.compile(r'^RUN if \[ "\$WITH_DEV_TOOLS" != "true" \]; then rm -rf (\S+(?: \S+)*); fi$', re.MULTILINE)


def image_removals() -> list[str]:
    """The paths the backend image deletes unless built with WITH_DEV_TOOLS=true (backend/Dockerfile)."""
    dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^ARG WITH_DEV_TOOLS=false$", dockerfile, re.MULTILINE)
    removal = REMOVAL.search(dockerfile)
    assert removal is not None
    assert (
        dockerfile.index("COPY src ./src")
        < dockerfile.index("ARG WITH_DEV_TOOLS")
        < dockerfile.index("uv sync --frozen --no-dev &&")
    )
    return removal.group(1).split()


def test_the_backend_image_leaves_the_module_out_unless_asked() -> None:
    removals = image_removals()
    clock_module = Path(bridge.main.__file__).parent / "testclock.py"
    assert clock_module.is_file()  # the path it deletes is the module
    assert str(clock_module.relative_to(BACKEND_DIR)) in removals
    compose = (REPO / "infra" / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert 'WITH_DEV_TOOLS: "true"' in compose


@pytest.fixture
async def clock(owner_engine: AsyncEngine) -> AsyncIterator[None]:
    """The shared test clock enabled for one test, then put back exactly as it was (the owner may; the app only moves
    it forward)."""
    async with owner_engine.begin() as conn:
        enabled, offset = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
        await conn.execute(text("UPDATE test_clock SET enabled = true"))
    try:
        yield
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = :e, clock_offset = :o"), {"e": enabled, "o": offset}
            )


@pytest.mark.usefixtures("clock")
async def test_a_signed_in_user_moves_the_clock_and_deadlines_follow(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    async with make_client(app_engine) as anonymous:
        assert (await anonymous.get(CLOCK)).status_code == 401
    async with seats(app_engine, deals_on(), world) as s:
        before = (await s.dev.get(CLOCK)).json()
        assert before["enabled"] is True
        moved = await s.dev.post(f"{CLOCK}/advance", json={"days": 9, "hours": 1})
        assert moved.status_code == 200, moved.text
        after = moved.json()
        assert after["offset_seconds"] == before["offset_seconds"] + 9 * 86400 + 3600
        assert datetime.fromisoformat(after["now"]) - datetime.fromisoformat(before["now"]) >= timedelta(days=9)
        too_far = await s.dev.post(f"{CLOCK}/advance", json={"days": 366})
        assert (too_far.status_code, too_far.json()["detail"]["code"]) == (422, "test_clock_limit")
        reviewed = await t.ok(s.reviewer, "start-review")
        entered = datetime.fromisoformat(reviewed["stage_entered_at"])
        assert entered >= datetime.fromisoformat(after["now"]) - timedelta(seconds=5)
        async with owner_engine.connect() as conn:
            holidays = {
                d
                for (d,) in await conn.execute(
                    text("SELECT observed_on FROM holidays WHERE country = 'KE' AND observed_on >= :d"),
                    {"d": local_date(entered)},
                )
            }
        expected = sm.stage_deadline(EngagementState.UNDER_REVIEW, entered, holidays, get_policy())
        assert expected is not None
        assert datetime.fromisoformat(reviewed["stage_deadline_at"]) == expected
        assert reviewed["due"]["business_days_left"] == 15


@pytest.mark.usefixtures("clock")
async def test_deadlines_skip_weekends_and_gazetted_holidays(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A holiday inside the SUBMITTED window (10 BD) pushes the deadline one business day later."""
    async with owner_engine.connect() as conn:
        now: datetime = (await conn.execute(text("SELECT app_clock_now()"))).scalar_one()
        existing = {
            d
            for (d,) in await conn.execute(
                text("SELECT observed_on FROM holidays WHERE observed_on >= :d"), {"d": local_date(now)}
            )
        }
    today = local_date(now)
    holiday = add_business_days(today, 3, existing)  # a business day inside the window
    holiday_id = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO holidays (id, country, holiday_on, observed_on, name) VALUES (:id, 'KE', :d, :d, :n)"),
            {"id": holiday_id, "d": holiday, "n": f"P5 test holiday {holiday_id}"},
        )
    try:
        world = await build(owner_engine)
        engagement = await open_engagement(app_engine, world)
        async with seats(app_engine, deals_on(), world) as s:
            detail = await Tracker(engagement).detail(s.dev)
        deadline = local_date(datetime.fromisoformat(detail["stage_deadline_at"]))
        with_holiday = add_business_days(today, 10, existing | {holiday})
        without = add_business_days(today, 10, existing)
        assert deadline == with_holiday
        assert with_holiday > without
        assert is_business_day(deadline, existing | {holiday})
        assert detail["due"]["business_days_left"] == 10
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM holidays WHERE id = :id"), {"id": holiday_id})


async def test_staging_lets_only_staff_admin_move_the_clock(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    staging = get_settings().model_copy(update={"app_env": "staging"})
    world = await build(owner_engine)
    async with make_client(app_engine, staging) as member, make_client(app_engine, staging) as staff:
        await sign_in_as(member, app_engine, world.owner, mfa_verified=True)
        await sign_in_as(staff, app_engine, world.staff, mfa_verified=True)
        assert (await member.get(CLOCK)).status_code == 404
        assert (await member.post(f"{CLOCK}/advance", json={"days": 1})).status_code == 404
        assert (await staff.get(CLOCK)).status_code == 200


async def test_a_database_without_the_clock_enabled_refuses(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        enabled = (await conn.execute(text("SELECT enabled FROM test_clock"))).scalar_one()
        await conn.execute(text("UPDATE test_clock SET enabled = false"))
    try:
        world = await build(owner_engine)
        async with make_client(app_engine) as client:
            await sign_in_as(client, app_engine, world.developer, mfa_verified=True)
            refused = await client.post(f"{CLOCK}/advance", json={"days": 1})
            assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "test_clock_disabled")
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = :e"), {"e": enabled})
