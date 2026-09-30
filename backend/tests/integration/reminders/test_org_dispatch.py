"""REQ-REM-02 against PostgreSQL: the organisation's progress digest through the dispatcher, as the worker runs it.

Only members who opted in (the reminders consent) receive it, once per organisation and period: weekly on the
default plan (one per ISO week), daily on a plan with ``progress_digest: daily``; nothing before 08:30 EAT; the email
can be switched off while the in-app summary stays; a removed member and a quiet organisation get nothing; no LLM is
ever called for it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements.calendar import NAIROBI
from bridge.ids import uuid7
from bridge.models.enums import DeliveryStatus
from bridge.notifications.email import DeliveryError, FakeEmailProvider
from bridge.reminders import dispatch
from bridge.reminders.health import Health
from tests.integration.engagements import tracker
from tests.integration.engagements.tracker import as_app
from tests.integration.reminders.world import DAY_BEFORE_DUE, build, consent

TUESDAY = DAY_BEFORE_DUE  # 30 March 2027, 09:00 EAT
NEXT_MONDAY = TUESDAY + timedelta(days=6)


async def test_opted_in_members_get_one_weekly_digest_per_iso_week(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)  # the signatory opted in; the viewer and the owner did not
        p = w.p
        report = await w.digests([p.signatory, p.viewer, p.owner], now=TUESDAY)
        signatory, viewer, owner = (report.of(user, p.org) for user in (p.signatory, p.viewer, p.owner))
        assert signatory is not None
        assert (signatory.status, signatory.email, signatory.in_app) == ("sent", DeliveryStatus.SENT, True)
        assert signatory.health == {w.engagement: Health.AT_RISK}
        assert viewer is not None
        assert owner is not None
        assert (viewer.status, owner.status) == ("not_opted_in", "not_opted_in")
        (message,) = w.email.outbox
        assert message.subject == "Tracker Ltd: weekly progress digest, week of 29 Mar 2027"
        assert "“RLS proposal” by Developer (Implementation): At risk." in message.text
        assert "No update from Developer since " in message.text
        wednesday = (await w.digests([p.signatory], now=TUESDAY + timedelta(days=1))).of(p.signatory, p.org)
        assert wednesday is not None
        assert wednesday.status == "already"
        monday = (await w.digests([p.signatory], now=NEXT_MONDAY)).of(p.signatory, p.org)
        assert monday is not None
        assert monday.status == "sent"
        assert len(w.email.outbox) == 2
        periods = await w.owner_rows(
            "SELECT local_date, org_id FROM notification_deliveries WHERE user_id = :u AND channel = 'email'"
            " ORDER BY local_date",
            u=p.signatory,
        )
        assert [tuple(row) for row in periods] == [(date(2027, 3, 29), p.org), (date(2027, 4, 5), p.org)]
        assert [kind for kind, _ in await w.in_app(p.signatory)] == ["em7_org", "em7_org"]
        assert await w.in_app_links(p.signatory) == [f"/org/engagements?org={p.org}"] * 2  # this organisation's list


async def test_a_daily_plan_sends_the_digest_each_day(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        await tracker.as_owner(conn)
        plan = await tracker.run(conn, "SELECT id FROM plans WHERE code = 'org_starter'")
        if plan is None:
            plan = uuid7()
            await tracker.run(
                conn,
                "INSERT INTO plans (id, code, side, name, price_kes_minor, interval, limits)"
                " VALUES (:id, 'org_starter', 'org', 'Starter', 1500000, 'month', '{}')",
                id=plan,
            )
        await tracker.run(
            conn,
            "INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start)"
            " VALUES (:id, :org, :plan, 'active', now())",
            id=uuid7(),
            org=w.p.org,
            plan=plan,
        )
        for day in range(2):
            outcome = (await w.digests([w.p.signatory], now=TUESDAY + timedelta(days=day))).of(w.p.signatory, w.p.org)
            assert outcome is not None
            assert outcome.status == "sent"
        assert [m.subject for m in w.email.outbox] == [
            "Tracker Ltd: progress digest, 30 Mar 2027",
            "Tracker Ltd: progress digest, 31 Mar 2027",
        ]


async def test_nothing_is_looked_at_before_half_past_eight(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        early = datetime(2027, 3, 30, 8, 29, tzinfo=NAIROBI)
        assert (await w.digests([w.p.signatory], now=early)).ran is False
        assert (await w.digests([w.p.signatory], now=early, force=True)).ran is True
        assert len(w.email.outbox) == 1


async def test_the_email_can_be_switched_off_while_the_in_app_digest_stays(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        await tracker.as_owner(conn)
        await tracker.run(
            conn,
            "INSERT INTO notification_preferences (user_id, kind, channel, enabled)"
            " VALUES (:u, 'em7_org', 'email', false)",
            u=w.p.signatory,
        )
        outcome = (await w.digests([w.p.signatory], now=TUESDAY)).of(w.p.signatory, w.p.org)
        assert outcome is not None
        assert (outcome.status, outcome.email, outcome.email_skipped, outcome.in_app) == (
            "sent",
            None,
            "preference_off",
            True,
        )
        assert w.email.outbox == []


async def test_a_removed_member_and_a_quiet_organisation_get_nothing(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        await consent(conn, w.p.other_member)  # a member of another organisation, with no engagement
        await tracker.as_owner(conn)
        await tracker.run(
            conn,
            "UPDATE memberships SET status = 'removed' WHERE user_id = :u AND org_id = :o",
            u=w.p.signatory,
            o=w.p.org,
        )
        report = await w.digests([w.p.signatory, w.p.other_member], now=TUESDAY)
        assert report.of(w.p.signatory, w.p.org) is None
        quiet = report.of(w.p.other_member, w.p.other_org)
        assert quiet is not None
        assert (quiet.status, quiet.in_app) == ("quiet", False)
        assert w.email.outbox == []


async def test_the_digest_never_calls_an_llm(owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the organisation's digest must not use an LLM")

    monkeypatch.setattr(dispatch, "word_nudge", refuse)
    monkeypatch.setattr(dispatch, "routed_client", refuse)
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        outcome = (await w.digests([w.p.signatory], now=TUESDAY)).of(w.p.signatory, w.p.org)
        assert outcome is not None
        assert (outcome.status, outcome.email) == ("sent", DeliveryStatus.SENT)


async def test_one_members_failure_never_stops_the_run(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        await consent(conn, w.p.other_member)
        real = dispatch.digest_one

        async def flaky(deps: dispatch.Deps, r: dispatch.Recipient, org_id: Any, **kwargs: Any) -> dispatch.Outcome:
            if r.id == w.p.signatory:
                raise RuntimeError("boom")
            return await real(deps, r, org_id, **kwargs)

        monkeypatch.setattr(dispatch, "digest_one", flaky)
        report = await w.digests([w.p.signatory, w.p.other_member], now=TUESDAY)
        assert {(o.user_id, o.status) for o in report.outcomes} == {
            (w.p.signatory, "error"),
            (w.p.other_member, "quiet"),
        }


async def test_a_past_weeks_queued_digest_is_swept_never_sent_late(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.email = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451)])
        first = (await w.digests([w.p.signatory], now=TUESDAY)).of(w.p.signatory, w.p.org)
        assert first is not None
        assert first.email == DeliveryStatus.QUEUED
        monday = (await w.digests([w.p.signatory], now=NEXT_MONDAY)).of(w.p.signatory, w.p.org)
        assert monday is not None
        assert monday.email == DeliveryStatus.SENT
        rows = await w.owner_rows(
            "SELECT local_date, status::text, last_error FROM notification_deliveries"
            " WHERE user_id = :u AND channel = 'email' ORDER BY local_date",
            u=w.p.signatory,
        )
        assert [tuple(row) for row in rows] == [
            (date(2027, 3, 29), "failed", "expired: its day passed"),
            (date(2027, 4, 5), "sent", None),
        ]
