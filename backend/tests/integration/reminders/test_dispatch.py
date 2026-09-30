"""REQ-REM-01, REQ-NOT-06 (AC-MAIL-3) against PostgreSQL: the developer's EM7 through the dispatcher, as the worker
runs it (``bridge_app`` under RLS, one bound session per recipient), inside one rolled-back owner transaction.

Once per Nairobi day and channel; nothing before 07:30 EAT unless forced; quiet when nothing needs the developer;
email only with the reminders consent, a verified address and the preference on, and never to a suppressed address;
the fixed text, marked, whenever the LLM cannot word it; a real account's facts never reach a free provider; the
shared test clock moving a day sends the next one; a failing provider is tried at most 3 times across runs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.engagements.calendar import NAIROBI
from bridge.ids import uuid7
from bridge.llm.deps import build_runtime
from bridge.models.enums import DeliveryStatus
from bridge.notifications.email import DeliveryError, FakeEmailProvider
from bridge.reminders import dispatch
from bridge.reminders.health import Health
from bridge.reminders.nudge import AI_LABEL, WORDING_HEADER
from tests.integration import world as base_world
from tests.integration.engagements import tracker
from tests.integration.engagements.tracker import as_app
from tests.integration.reminders.world import DAY_BEFORE_DUE, build, consent, settings

SENT, QUEUED, FAILED = DeliveryStatus.SENT, DeliveryStatus.QUEUED, DeliveryStatus.FAILED
BOTH_SENT = [("em7", "email", "sent"), ("em7", "in_app", "sent")]


async def test_the_nudge_is_sent_once_per_day(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        dev = w.p.developer
        first = (await w.nudges(now=DAY_BEFORE_DUE)).of(dev)
        assert first is not None
        assert (first.status, first.email, first.in_app, first.email_skipped) == ("sent", SENT, True, None)
        assert first.health == {w.engagement: Health.AT_RISK}
        for hours in (0, 3, 14):  # later runs the same Nairobi day
            again = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(hours=hours))).of(dev)
            assert again is not None
            assert (again.status, again.email) == ("already", SENT)
        assert len(w.email.outbox) == 1
        assert await w.deliveries(dev) == BOTH_SENT
        assert await w.in_app(dev) == [("em7", "Your daily update")]
        assert await w.in_app_links(dev) == ["/dev/engagements"]  # the developer's own portal
        (message,) = w.email.outbox
        assert message.subject == "Your day on Bridge (30 Mar 2027): 1 needs you, 1 at risk"
        assert "Milestone 1 “Pilot for one county” is due 31 Mar 2027" in message.text
        next_day = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(days=1))).of(dev)
        assert next_day is not None
        assert next_day.status == "sent"
        assert len(w.email.outbox) == 2
        assert len(await w.in_app(dev)) == 2


async def test_nothing_is_looked_at_before_half_past_seven_unless_forced(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        early = datetime(2027, 3, 30, 7, 29, tzinfo=NAIROBI)
        report = await w.nudges(now=early)
        assert (report.ran, report.outcomes, report.today.isoformat()) == (False, (), "2027-03-30")
        assert w.email.outbox == []
        assert await w.deliveries(w.p.developer) == []
        forced = (await w.nudges(now=early, force=True)).of(w.p.developer)
        assert forced is not None
        assert forced.status == "sent"
        on_time = (await w.nudges(now=early + timedelta(minutes=1))).of(w.p.developer)
        assert on_time is not None
        assert on_time.status == "already"  # forcing never sends twice
        assert len(w.email.outbox) == 1


async def test_a_day_with_nothing_for_the_developer_is_quiet(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn, until="SUBMITTED")  # the organisation's turn, no deadline, no drafts
        outcome = (await w.nudges(now=DAY_BEFORE_DUE)).of(w.p.developer)
        assert outcome is not None
        assert (outcome.status, outcome.email, outcome.in_app) == ("quiet", None, False)
        assert w.email.outbox == []
        assert await w.deliveries(w.p.developer) == []


async def test_email_needs_the_consent_a_verified_address_and_the_preference(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn, consents=False)
        dev = w.p.developer
        day = DAY_BEFORE_DUE
        outcome = (await w.nudges(now=day)).of(dev)
        assert outcome is not None
        assert (outcome.status, outcome.email, outcome.email_skipped, outcome.in_app) == (
            "sent",
            None,
            "no_consent",
            True,
        )
        assert await w.deliveries(dev) == [("em7", "in_app", "sent")]  # in-app is always on
        await consent(conn, dev, granted=True)
        await tracker.run(
            conn,
            "INSERT INTO notification_preferences (user_id, kind, channel, enabled) VALUES (:u, 'em7', 'email', false)",
            u=dev,
        )
        off = (await w.nudges(now=day + timedelta(days=1))).of(dev)
        assert off is not None
        assert (off.email, off.email_skipped) == (None, "preference_off")
        await tracker.as_owner(conn)
        await tracker.run(conn, "DELETE FROM notification_preferences WHERE user_id = :u", u=dev)
        await tracker.run(conn, "UPDATE users SET email_verified_at = NULL WHERE id = :u", u=dev)
        unverified = (await w.nudges(now=day + timedelta(days=2))).of(dev)
        assert unverified is not None
        assert unverified.email_skipped == "unverified"
        await tracker.as_owner(conn)
        await tracker.run(conn, "UPDATE users SET email_verified_at = now() WHERE id = :u", u=dev)
        await tracker.run(
            conn,
            "INSERT INTO email_suppressions (id, email, reason) SELECT :id, email, 'bounce' FROM users WHERE id = :u",
            id=uuid7(),
            u=dev,
        )
        suppressed = (await w.nudges(now=day + timedelta(days=3))).of(dev)
        assert suppressed is not None
        assert (suppressed.email, suppressed.email_skipped) == (DeliveryStatus.SUPPRESSED, None)
        assert w.email.outbox == []  # four days, never an email
        assert w.email.attempts == 0


async def test_the_fixed_text_is_used_and_marked_when_no_model_words_it(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)  # APP_ENV=test: the fake provider, whose answer is a demo fallback
        outcome = (await w.nudges(now=DAY_BEFORE_DUE)).of(w.p.developer)
        assert outcome is not None
        assert outcome.wording is not None
        assert (outcome.wording.source, outcome.wording.reason) == ("fallback", "demo_fallback:fake_provider")
        (message,) = w.email.outbox
        assert message.headers[WORDING_HEADER] == "fallback"
        assert AI_LABEL not in message.text
        assert message.text.startswith("1 thing needs you today, and 1 engagement needs attention.\n")
        without_llm = dispatch.Deps(w.factory, w.cfg, FakeEmailProvider(), None)
        await tracker.act(conn, w.p.developer)
        report = await dispatch.run_developer_nudges(
            without_llm, now=DAY_BEFORE_DUE + timedelta(days=1), user_ids=[w.p.developer]
        )
        wording = report.outcomes[0].wording
        assert wording is not None
        assert (wording.source, wording.reason) == ("fallback", "not_eligible")


FREE_BASE = "https://free-rem.example/v1"


def no_email_plans(tmp_path: Any) -> Any:
    """A copy of plans.yaml whose developer plans do not include daily email reminders."""
    source = get_settings().plans_file.read_text(encoding="utf-8")
    path = tmp_path / "plans.yaml"
    path.write_text(source.replace("daily_email_reminders: true", "daily_email_reminders: false"), encoding="utf-8")
    return path


def free(tag: str) -> Any:
    return settings(
        llm_provider="free",
        llm_free_1_base_url=FREE_BASE,
        llm_free_1_api_key=SecretStr("sk-rem-key-not-real"),
        llm_free_1_model=f"vendor/rem-{tag}",
        llm_free_1_daily_requests=5,
    )


def chat(body: dict[str, Any]) -> httpx.Response:
    choice = {"index": 0, "message": {"role": "assistant", "content": json.dumps(body)}, "finish_reason": "stop"}
    return httpx.Response(200, json={"choices": [choice], "usage": {"prompt_tokens": 80, "completion_tokens": 20}})


WORDED = {  # the model's choice (ids only): code renders every word
    "injection_suspected": False,
    "opening": "your_day",
    "order": ["n1", "h1"],
    "next_step_variant": "start_with",
}
WORDED_HEADLINE = "Here is your day on Bridge. 1 thing needs you today, and 1 engagement needs attention."


@pytest.mark.parametrize("demo", [False, True])
async def test_only_a_demo_accounts_facts_reach_a_free_provider(owner_engine: AsyncEngine, demo: bool) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.cfg = free(uuid7().hex[-10:])
        w.llm = build_runtime(w.cfg)
        if demo:
            await tracker.as_owner(conn)
            await tracker.run(conn, "UPDATE users SET demo_account = true WHERE id = :u", u=w.p.developer)
        with respx.mock(assert_all_called=False) as router:
            route = router.post(f"{FREE_BASE}/chat/completions").mock(return_value=chat(WORDED))
            outcome = (await w.nudges(now=DAY_BEFORE_DUE)).of(w.p.developer)
        assert outcome is not None
        assert outcome.wording is not None
        (message,) = w.email.outbox
        if demo:
            assert route.call_count == 1
            assert "Tracker Ltd" not in route.calls[0].request.content.decode()  # no organisation text sent
            assert (outcome.wording.source, outcome.wording.headline) == ("model", WORDED_HEADLINE)
            assert message.headers[WORDING_HEADER] == "model"
            assert message.text.startswith(f"{WORDED_HEADLINE}\n{AI_LABEL}\n")
            assert "NEXT STEP\nStart with this: Submit milestone 1 of “RLS proposal” for review by 31 Mar 2027." in (
                message.text
            )
        else:
            assert not route.called
            assert outcome.wording.reason == "demo_fallback:not_demo_data"
            assert message.headers[WORDING_HEADER] == "fallback"


async def test_the_test_clock_moving_a_day_sends_the_next_one(owner_engine: AsyncEngine) -> None:
    """No ``now`` is passed: the dispatcher reads app_clock_now(), which the dev/test clock moves (rolled back)."""
    async with as_app(owner_engine) as conn:
        w = await build(conn, until="SUBMITTED")
        niche = await tracker.run(conn, "SELECT niche_id FROM proposals WHERE id = :p", p=w.p.proposal)
        problem = await tracker.run(
            conn, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=w.p.version
        )
        await tracker.as_owner(conn)
        await base_world.add_proposal(conn, w.p.developer, niche, problem, registered=False)  # a draft: always open
        await tracker.run(conn, "UPDATE test_clock SET enabled = true")
        now = await tracker.run(conn, "SELECT app_clock_now()")
        offset = await tracker.run(conn, "SELECT clock_offset FROM test_clock")
        local = now.astimezone(NAIROBI)
        target = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), NAIROBI) + timedelta(hours=10)
        await tracker.act(conn, w.p.developer)
        await tracker.run(conn, "SELECT app_set_test_clock(:o)", o=offset + (target - now))
        day_one = await w.nudges()
        assert (day_one.today, day_one.outcomes[0].status) == (target.date(), "sent")
        assert (await w.nudges()).outcomes[0].status == "already"
        await tracker.run(conn, "SELECT app_set_test_clock(:o)", o=offset + (target - now) + timedelta(days=1))
        day_two = await w.nudges()
        assert (day_two.today, day_two.outcomes[0].status) == (target.date() + timedelta(days=1), "sent")
        assert [m.subject.split(" (")[1].split(")")[0] for m in w.email.outbox] == [
            f"{d.day} {d:%b %Y}" for d in (target.date(), target.date() + timedelta(days=1))
        ]
        dates = await w.owner_rows(
            "SELECT local_date FROM notification_deliveries WHERE user_id = :u AND channel = 'email'"
            " ORDER BY local_date",
            u=w.p.developer,
        )
        assert [row[0] for row in dates] == [target.date(), target.date() + timedelta(days=1)]


async def test_a_failing_provider_is_tried_once_per_run_and_three_times_in_all(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.email = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451) for _ in range(4)])
        statuses = []
        for minutes in (0, 15, 30, 45):
            outcome = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(minutes=minutes))).of(w.p.developer)
            assert outcome is not None
            statuses.append((outcome.status, outcome.email))
        assert statuses == [("sent", QUEUED), ("sent", QUEUED), ("sent", FAILED), ("already", FAILED)]
        assert w.email.attempts == 3
        assert len(await w.in_app(w.p.developer)) == 1


async def test_a_permanent_failure_is_final_and_a_transient_one_recovers(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.email = FakeEmailProvider([DeliveryError("SMTP 550", transient=False, code=550)])
        first = (await w.nudges(now=DAY_BEFORE_DUE)).of(w.p.developer)
        again = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(minutes=15))).of(w.p.developer)
        assert first is not None
        assert again is not None
        assert (first.email, again.status, w.email.attempts) == (FAILED, "already", 1)
        w.email = FakeEmailProvider([DeliveryError("SMTP 421", transient=True, code=421)])
        day_two = DAY_BEFORE_DUE + timedelta(days=1)
        assert (await w.nudges(now=day_two)).outcomes[0].email == QUEUED
        assert (await w.nudges(now=day_two + timedelta(minutes=15))).outcomes[0].email == SENT
        assert len(w.email.outbox) == 1


async def test_one_recipients_failure_never_stops_the_run(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        real = dispatch.nudge_one

        async def flaky(deps: dispatch.Deps, r: dispatch.Recipient, **kwargs: Any) -> dispatch.Outcome:
            if r.id == w.p.signatory:
                raise RuntimeError("boom")
            return await real(deps, r, **kwargs)

        monkeypatch.setattr(dispatch, "nudge_one", flaky)
        report = await w.nudges([w.p.signatory, w.p.developer], now=DAY_BEFORE_DUE)
        assert {(o.user_id, o.status) for o in report.outcomes} == {(w.p.signatory, "error"), (w.p.developer, "sent")}


async def _demo_on_a_free_slot(w: Any) -> None:
    w.cfg = free(uuid7().hex[-10:])
    w.llm = build_runtime(w.cfg)
    await tracker.as_owner(w.conn)
    await tracker.run(w.conn, "UPDATE users SET demo_account = true WHERE id = :u", u=w.p.developer)


async def _llm_rows(w: Any) -> int:
    rows = await w.owner_rows("SELECT count(*) FROM llm_calls WHERE user_id = :u", u=w.p.developer)
    return int(rows[0][0])


@pytest.mark.parametrize("closed_by", ["no_consent", "preference_off", "unverified", "plan"])
async def test_no_llm_call_when_no_email_will_be_sent(owner_engine: AsyncEngine, closed_by: str, tmp_path: Any) -> None:
    """P6 review MAJOR 2: the facts reach the model only for an email this run sends; the in-app summary never
    needs the model."""
    async with as_app(owner_engine) as conn:
        w = await build(conn, consents=closed_by != "no_consent")
        await _demo_on_a_free_slot(w)
        if closed_by == "preference_off":
            await tracker.run(
                conn,
                "INSERT INTO notification_preferences (user_id, kind, channel, enabled)"
                " VALUES (:u, 'em7', 'email', false)",
                u=w.p.developer,
            )
        elif closed_by == "unverified":
            await tracker.run(conn, "UPDATE users SET email_verified_at = NULL WHERE id = :u", u=w.p.developer)
        elif closed_by == "plan":
            w.cfg = w.cfg.model_copy(update={"plans_file": no_email_plans(tmp_path)})
        with respx.mock(assert_all_called=False) as router:
            route = router.post(f"{FREE_BASE}/chat/completions").mock(return_value=chat(WORDED))
            outcome = (await w.nudges(now=DAY_BEFORE_DUE)).of(w.p.developer)
        assert outcome is not None
        assert (outcome.status, outcome.in_app, outcome.email, outcome.email_skipped) == ("sent", True, None, closed_by)
        assert outcome.wording is None
        assert not route.called
        assert await _llm_rows(w) == 0
        assert w.email.outbox == []


async def test_one_llm_call_per_email_not_per_attempt(owner_engine: AsyncEngine) -> None:
    """P6 review MAJOR 2: a resumed email is sent with the fixed text; the model is asked once per email."""
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        await _demo_on_a_free_slot(w)
        w.email = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451)])
        with respx.mock(assert_all_called=True) as router:
            route = router.post(f"{FREE_BASE}/chat/completions").mock(return_value=chat(WORDED))
            first = (await w.nudges(now=DAY_BEFORE_DUE)).of(w.p.developer)
            second = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(minutes=15))).of(w.p.developer)
            third = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(minutes=30))).of(w.p.developer)
        assert first is not None
        assert second is not None
        assert third is not None
        assert route.call_count == 1
        assert await _llm_rows(w) == 1
        assert (first.email, first.wording and first.wording.source) == (QUEUED, "model")
        assert second.email == SENT
        assert second.wording is not None
        assert (second.wording.source, second.wording.reason) == ("fallback", "retry")
        assert (third.status, third.wording) == ("already", None)
        (message,) = w.email.outbox
        assert message.headers[WORDING_HEADER] == "fallback"
        assert AI_LABEL not in message.text


async def _email_rows(w: Any) -> list[tuple[Any, str, int, str | None]]:
    rows = await w.owner_rows(
        "SELECT local_date, status::text, attempts, last_error FROM notification_deliveries"
        " WHERE user_id = :u AND channel = 'email' ORDER BY local_date",
        u=w.p.developer,
    )
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def test_a_queued_email_with_nothing_left_to_say_is_dead_lettered(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.email = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451)])
        assert (await w.nudges(now=DAY_BEFORE_DUE)).outcomes[0].email == QUEUED
        milestone = await tracker.run(conn, "SELECT id FROM milestones WHERE engagement_id = :e", e=w.engagement)
        await tracker.act(conn, w.p.developer)
        for step in ("IN_PROGRESS", "SUBMITTED_FOR_REVIEW"):  # the developer submits: nothing needs them now
            await tracker.run(
                conn, "UPDATE milestones SET state = CAST(:s AS milestone_state) WHERE id = :id", s=step, id=milestone
            )
        quiet = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(minutes=15))).of(w.p.developer)
        assert quiet is not None
        assert (quiet.status, quiet.email) == ("quiet", FAILED)
        assert [row[1:] for row in await _email_rows(w)] == [("failed", 1, "withdrawn: nothing to send any more")]
        assert w.email.attempts == 1


async def test_a_queued_email_whose_channel_closed_is_dead_lettered(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.email = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451)])
        assert (await w.nudges(now=DAY_BEFORE_DUE)).outcomes[0].email == QUEUED
        await consent(conn, w.p.developer, granted=False)  # the developer withdraws the reminders consent
        closed = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(minutes=15))).of(w.p.developer)
        assert closed is not None
        assert (closed.status, closed.email, closed.email_skipped) == ("already", FAILED, "no_consent")
        assert [row[1:] for row in await _email_rows(w)] == [("failed", 1, "withdrawn: no_consent")]
        assert w.email.attempts == 1


async def test_a_past_days_queued_email_is_swept_never_sent_late(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        w.email = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451)])
        assert (await w.nudges(now=DAY_BEFORE_DUE)).outcomes[0].email == QUEUED
        next_day = (await w.nudges(now=DAY_BEFORE_DUE + timedelta(days=1))).of(w.p.developer)
        assert next_day is not None
        assert next_day.email == SENT
        day, following = DAY_BEFORE_DUE.date(), DAY_BEFORE_DUE.date() + timedelta(days=1)
        assert await _email_rows(w) == [
            (day, "failed", 1, "expired: its day passed"),
            (following, "sent", 1, None),
        ]
        assert w.email.attempts == 2
