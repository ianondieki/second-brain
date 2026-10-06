"""REQ-DEV-02 (D-61; P22 card B; N26, N27): the reminder windows on the Nairobi clock, the N26 email's content (the
title, when, where and the two calendar links, never the description; escaped and unlinkable) and the job
``events.remind`` (every 15 minutes, one run at a time, on the installed runtime, its own timestamp ignored)."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, time
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

import pytest

from bridge.config import get_settings
from bridge.engagements.calendar import NAIROBI
from bridge.events import reminders
from bridge.jobs import events as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.notifications.email import FakeEmailProvider
from bridge.web_paths import dev_event_path

EVENT_ID = UUID("01927f00-0000-7000-8000-000000000002")


def at(day: int, clock: time) -> datetime:
    return datetime(2026, 10, day, clock.hour, clock.minute, tzinfo=NAIROBI)


def row(**changes: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": EVENT_ID,
        "title": "Rust <night> at github.com",
        "description": "Secret plans for the evening.",
        "starts_at": at(14, time(18, 0)),
        "ends_at": at(14, time(20, 30)),
        "updated_at": datetime(2026, 10, 6, tzinfo=UTC),
        "online": False,
        "venue": "iHub",
        "county_name": "Nairobi City",
        "join_url": None,
        "link": None,
    }
    return SimpleNamespace(**(values | changes))


def test_the_windows() -> None:
    starts = at(14, time(18, 0))
    assert reminders.n26_window(starts) == (at(13, time(18, 0)), at(14, time(0, 0)))
    early = at(14, time(0, 30))  # starting just after midnight: the evening before still, until midnight
    assert reminders.n26_window(early) == (at(13, time(18, 0)), at(14, time(0, 0)))
    assert reminders.n27_window(starts, at(14, time(20, 30))) == (at(14, time(8, 0)), at(14, time(20, 30)))
    assert reminders.n27_window(starts, at(16, time(17, 0))) == (at(14, time(8, 0)), at(15, time(0, 0)))
    # Early events: two hours before they start (from that day's midnight at the earliest), still until they end.
    assert reminders.n27_window(at(14, time(5, 0)), at(14, time(7, 0))) == (at(14, time(3, 0)), at(14, time(7, 0)))
    assert reminders.n27_window(at(14, time(7, 0)), at(14, time(9, 0))) == (at(14, time(5, 0)), at(14, time(9, 0)))
    assert reminders.n27_window(at(14, time(1, 0)), at(14, time(2, 0))) == (at(14, time(0, 0)), at(14, time(2, 0)))
    assert reminders.n27_window(at(14, time(10, 0)), at(14, time(11, 0)))[0] == at(14, time(8, 0))


def test_when_and_where_for_people() -> None:
    assert reminders.when(at(14, time(18, 0)), at(14, time(20, 30))) == (
        "Wednesday 14 October, 18:00 to 20:30 (Nairobi time)"
    )
    assert reminders.when(at(14, time(9, 0)), at(16, time(17, 0))) == (
        "Wednesday 14 October 09:00 to Friday 16 October 17:00 (Nairobi time)"
    )
    assert reminders.place(row()) == "iHub, Nairobi City"
    assert reminders.place(row(online=True, venue=None, county_name=None, join_url="https://x.example/j")) == "Online"


LINK = re.compile(r"https?://[^\s\"'<>]+")


def decoded_links(body: str) -> list[tuple[str, dict[str, list[str]]]]:
    """Every link of an email body, unescaped and percent-decoded, with its decoded query."""
    found = []
    for raw in LINK.findall(body):
        link = html.unescape(raw)
        found.append((unquote(link), parse_qs(urlsplit(link).query)))
    return found


@pytest.mark.parametrize(
    "event",
    [
        row(link="https://poster.example/rust-night"),
        row(online=True, venue=None, county_name=None, join_url="https://poster.example/join", link=None),
    ],
)
def test_no_link_of_the_n26_email_carries_the_description_or_a_poster_address(event: SimpleNamespace) -> None:
    rendered = reminders.render_n26(event, base_url="https://wazo.example", product="Wazo")
    for body in (rendered.text, rendered.html):
        links = decoded_links(body)
        assert len(links) >= 2  # the Google link and the calendar file at least
        for link, query in links:
            words = link + " " + " ".join(v for values in query.values() for v in values)
            assert "Secret plans" not in words
            assert "poster.example" not in words
        [google] = [query for link, query in links if link.startswith("https://calendar.google.com/")]
        assert "details" not in google
        assert google["location"] == ["Online" if event.online else "iHub, Nairobi City"]
        assert google["text"] == [event.title]


def test_the_n26_email_states_when_and_where_and_the_calendar_links_only() -> None:
    rendered = reminders.render_n26(row(), base_url="https://wazo.example/", product="Wazo")
    assert rendered.subject == "Tomorrow: Rust <night> at github\N{ONE DOT LEADER}com"
    for part in (rendered.text, rendered.html):
        assert "Wednesday 14 October, 18:00 to 20:30 (Nairobi time)" in part
        assert "iHub, Nairobi City" in part
        assert "Secret plans" not in part
    assert f"https://wazo.example/api/events/{EVENT_ID}/calendar.ics" in rendered.text
    assert "https://calendar.google.com/calendar/render?action=TEMPLATE" in rendered.text
    assert "&lt;night&gt;" in rendered.html
    assert "<night>" not in rendered.html
    assert 'data-cta="google-calendar"' in rendered.html
    assert reminders.n26_key(EVENT_ID, EVENT_ID).startswith("n26:email:")
    assert reminders.n27_key(EVENT_ID, EVENT_ID).startswith("n27:in_app:")
    assert dev_event_path(EVENT_ID) == f"/dev/events/{EVENT_ID}"


def test_the_job_runs_every_15_minutes_one_run_at_a_time() -> None:
    assert "bridge.jobs.events" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("events.remind", "reminders", "events:remind")
    assert task.configure(task_kwargs={"timestamp": 0}).job.lock == "events:remind"
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "*/15 * * * *"


async def test_the_task_runs_a_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def run(deps: reminders.Deps, **kwargs: Any) -> reminders.Report:
        calls.append((deps, kwargs))
        return reminders.Report(datetime.now(UTC), 0)

    monkeypatch.setattr(jobs, "run_event_reminders", run)
    mail, factory = FakeEmailProvider(), object()
    jobs.use_runtime(reminders.EventReminderRuntime(get_settings(), factory=factory, email=mail))  # type: ignore[arg-type]
    try:
        await jobs.remind(timestamp=0)
    finally:
        jobs.use_runtime(None)
    [(deps, kwargs)] = calls
    assert (deps.factory, deps.email, kwargs) == (factory, mail, {})  # the job's own timestamp is ignored
    assert isinstance(jobs.runtime(), reminders.EventReminderRuntime)
    assert jobs.runtime() is jobs.runtime()
    jobs.use_runtime(None)


def test_the_runtime_builds_its_parts_once() -> None:
    runtime = reminders.EventReminderRuntime(get_settings())
    deps = runtime.deps()
    assert runtime.deps().factory is deps.factory
    assert runtime.deps().email is deps.email
    assert deps.settings is get_settings()
