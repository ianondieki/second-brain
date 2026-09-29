"""Edges of the tracker API (REQ-ENG-01, REQ-ENG-02, REQ-NOT-04): the organisation's two-step sign-in rules, documents
that do not exist yet, the database's refusals as the backstop, and notifications that have nobody to reach."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.engagements import commands, notify
from bridge.engagements import state_machine as sm
from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    clients,
    db_today,
    deals_on,
    notification_jobs,
    open_engagement,
    run_notifications,
    seats,
    walk_to,
)


async def test_organisation_members_need_two_step_sign_in_for_their_role(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET totp_enabled_at = NULL WHERE id = :u"), {"u": world.reviewer})
    async with clients(app_engine, deals_on(), world.reviewer) as (reviewer,):
        refused = await reviewer.get(t.path())
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "mfa_enrolment_required")
    async with clients(app_engine, deals_on(), world.owner, mfa_verified=False) as (owner,):
        pending = await owner.get(t.path())
        assert (pending.status_code, pending.json()["detail"]["code"]) == (401, "mfa_required")
    async with clients(app_engine, deals_on(), world.viewer) as (viewer,):  # a viewer reads without it
        assert (await viewer.get(t.path())).json()["actions"] == []


async def test_documents_that_do_not_exist_yet_are_404(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    async with seats(app_engine, deals_on(), world) as s:
        for kind in ("mutual_nda", "agreement", "acceptance_certificate"):
            assert (await s.dev.get(t.path(f"/documents/{kind}"))).status_code == 404, kind
        assert (await s.dev.get(t.path("/documents/milestone_confirmation"))).status_code == 404
        assert (await s.dev.get(t.path("/documents/contract"))).status_code == 422
        await walk_to(t, s, world, await db_today(owner_engine), "NEGOTIATION")
        draft = (await s.dev.get(t.path("/documents/agreement"))).json()
        assert draft["intact"] is True  # a draft's own hash; it is recorded once marked final
        assert "IP terms: non_exclusive_licence" in draft["text"]


@pytest.fixture
def failing_start_review(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace start_review's effect with a statement the database refuses (the backstop behind the app's checks)."""
    statements: list[str] = []

    async def effect(step: commands.Step) -> None:
        await step.db.execute(text(statements[0]), {"e": step.engagement.id, "id": uuid7()})

    monkeypatch.setitem(commands.EFFECTS, sm.Command.START_REVIEW, effect)
    return statements


async def test_a_database_refusal_is_the_backstop(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, failing_start_review: list[str]
) -> None:
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    async with seats(app_engine, deals_on(), world) as s:
        # A stale from_state: the chain refuses (check_violation) -> 409.
        failing_start_review.append(
            "INSERT INTO engagement_events (id, engagement_id, actor_user_id, actor_role, command, from_state,"
            " to_state) SELECT :id, :e, app_user_id(), 'reviewer', 'start_review', 'UNDER_REVIEW', 'UNDER_REVIEW'"
        )
        stale = await t.post(s.reviewer, "start-review")
        assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "conflict")
        # An engagement the caller cannot see: the tracker's one refusal -> 404.
        failing_start_review[0] = (
            "INSERT INTO engagement_events (id, engagement_id, actor_role, command, to_state)"
            " VALUES (:id, gen_random_uuid(), 'system', 'x', 'SUBMITTED') RETURNING :e"
        )
        hidden = await t.post(s.reviewer, "start-review")
        assert hidden.status_code == 404
        # Anything else is a bug and is not dressed up as a refusal.
        failing_start_review[0] = "SELECT no_such_function(:e, :id)"
        with pytest.raises(Exception, match="no_such_function"):
            await t.post(s.reviewer, "start-review")
        assert (await t.detail(s.dev))["state"] == "SUBMITTED"


async def test_notifications_reach_only_current_members_and_verified_addresses(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "INTEREST_CONFIRMED")
        await run_notifications(owner_engine, app_engine, engagement, FakeEmailProvider())
        await t.ok(s.dev, "withdraw")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE user_id = :u AND org_id = :o"),
            {"u": world.reviewer, "o": world.org},
        )
    await run_notifications(owner_engine, app_engine, engagement, FakeEmailProvider())
    async with owner_engine.connect() as conn:
        told = set(
            (
                await conn.execute(
                    text("SELECT user_id FROM in_app_notifications WHERE kind = 'engagement.withdrawn' AND link = :l"),
                    {"l": f"/engagements/{engagement}"},
                )
            ).scalars()
        )
    assert told == {world.signatory, world.owner}  # the reviewer left the organisation

    factory = create_session_factory(app_engine)
    settings = get_settings()
    unknown = await notify.deliver(
        factory, FakeEmailProvider(), settings, engagement_id=engagement, event_id=uuid7(), developer_id=world.developer
    )
    assert unknown is True  # nothing to do, nothing to retry

    unverified = await build(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET email_verified_at = NULL WHERE id = :u"), {"u": unverified.developer})
    second = await open_engagement(app_engine, unverified)
    async with seats(app_engine, deals_on(), unverified) as s:
        await walk_to(Tracker(second), s, unverified, today, "INTEREST_CONFIRMED")
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, second, provider)
    assert provider.outbox == []  # EM2 only to a verified address
    assert await notification_jobs(owner_engine, second) == []
