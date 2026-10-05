"""P21 track C (REQ-PERS-03, REQ-TREND-02, D-57 (7)): the saved-search alerts' code-decided parts. The daily job runs at
04:05 UTC (07:05 in Nairobi), one run at a time, on the shared clock; a notice's title counts and names the search; its
link is Discover with the saved view and filters, written as the web app's ``discoverHref`` writes it; the in-app
dedupe key is per search and Nairobi day; the digest email is off until the person turns it on."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest

from bridge.jobs import saved_searches as jobs
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.matching import saved_search_alerts as alerts
from bridge.matching.trending import NAIROBI
from bridge.models.enums import NotificationChannel
from bridge.notifications.in_app import MAX_LINK_CHARS, is_platform_path
from bridge.notifications.preferences import (
    CATALOGUE,
    SAVED_SEARCH_DIGEST,
    SAVED_SEARCH_MATCH,
    catalogued,
    default_for,
)
from bridge.profiles.models import SavedSearch
from bridge.web_paths import discover_path

SEARCH = UUID("01a10000-0000-7000-8000-000000000001")


def search(**values: Any) -> SavedSearch:
    base: dict[str, Any] = {"id": SEARCH, "name": "Agriculture in Nakuru", "view": "problems"}
    return SavedSearch(**(base | values))


def test_the_job_runs_daily_at_0705_nairobi_one_run_at_a_time() -> None:
    assert "bridge.jobs.saved_searches" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("saved_searches.alert", "notifications", "saved_searches:alert")
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "5 4 * * *"
    assert datetime(2026, 10, 5, 4, 5, tzinfo=UTC).astimezone(NAIROBI).strftime("%H:%M") == "07:05"


async def test_the_task_runs_a_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def run(deps: object, **kwargs: Any) -> alerts.Report:
        calls.append((deps, kwargs))
        return alerts.Report(datetime(2026, 10, 5, 4, 5, tzinfo=UTC))

    monkeypatch.setattr(jobs, "run_alerts", run)
    factory, email = object(), object()
    jobs.use_runtime(jobs.AlertRuntime(factory=factory, email=email))  # type: ignore[arg-type]
    try:
        await jobs.alert(timestamp=0)
    finally:
        jobs.use_runtime(None)
    [(deps, kwargs)] = calls
    assert (deps.factory, deps.email, kwargs) == (factory, email, {})  # the job's own timestamp is ignored
    assert isinstance(jobs.runtime(), jobs.AlertRuntime)
    jobs.use_runtime(None)


@pytest.mark.parametrize(
    ("count", "view", "expected"),
    [
        (1, "problems", "1 new problem matches Agriculture in Nakuru"),
        (3, "problems", "3 new problems match Agriculture in Nakuru"),
        (1, "briefs", "1 new Brief matches Agriculture in Nakuru"),
        (12, "briefs", "12 new Briefs match Agriculture in Nakuru"),
    ],
)
def test_the_title_counts_and_names_the_search(count: int, view: str, expected: str) -> None:
    assert alerts.title(count, view, "Agriculture in Nakuru") == expected


def test_the_link_is_discover_with_the_saved_filters() -> None:
    assert alerts.link(search()) == "/dev/discover"
    assert alerts.link(search(view="briefs")) == "/dev/discover?view=briefs"
    full = search(niche_slug="agriculture", county_code="KE-32", words="cold chain & 100%")
    assert alerts.link(full) == "/dev/discover?niche=agriculture&county=KE-32&words=cold+chain+%26+100%25"
    assert is_platform_path(alerts.link(full))
    long_words = search(view="briefs", niche_slug="agriculture", words="\U0001f33e" * 100)  # 1,200 characters encoded
    assert alerts.link(long_words) == "/dev/discover?view=briefs&niche=agriculture"  # the words do not fit a link
    assert discover_path("problems", niche=None, county=None, words="mbolea") == "/dev/discover?words=mbolea"
    assert len(alerts.link(long_words)) <= MAX_LINK_CHARS


def test_the_in_app_key_is_per_search_and_nairobi_day() -> None:
    assert alerts.in_app_key(SEARCH, date(2026, 10, 5)) == f"saved_search_match:{SEARCH}:2026-10-05"
    # 22:30 UTC on the 4th is 01:30 on the 5th in Nairobi: the day the due list starts from.
    assert alerts.day_start(datetime(2026, 10, 4, 22, 30, tzinfo=UTC)) == datetime(2026, 10, 5, tzinfo=NAIROBI)


def test_the_digest_is_off_until_turned_on_and_the_notice_is_in_app_only() -> None:
    email, in_app = NotificationChannel.EMAIL, NotificationChannel.IN_APP
    assert default_for(SAVED_SEARCH_DIGEST, email) is False
    assert default_for("n17", email) is True  # a kind the catalogue does not list stays on, as before
    digest, notice = catalogued(SAVED_SEARCH_DIGEST, email), catalogued(SAVED_SEARCH_MATCH, in_app)
    assert digest is not None
    assert digest.mutable
    assert notice is not None
    assert not notice.mutable
    assert catalogued(SAVED_SEARCH_MATCH, email) is None
    assert len({(info.kind, info.channel) for info in CATALOGUE}) == len(CATALOGUE)
    assert all(len(info.kind) <= 40 for info in CATALOGUE)  # notification kinds are String(40)
