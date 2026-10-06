"""REQ-DEV-03 (the 0011 security review's MINOR 1): what a party is told of why a thread closed, and the N28/N29
notices' words and 30-minute windows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from bridge.notifications.in_app import MAX_TITLE_CHARS
from bridge.teams.notices import ACCEPTED_TITLE, BUCKET_SECONDS, INVITED_TITLE, bucket, fit, message_key
from bridge.teams.threads import shown_reason
from bridge.web_paths import team_thread_path


def test_a_block_is_blocked_for_the_blocker_and_ended_for_the_other() -> None:
    assert shown_reason(None, i_blocked=False) is None
    assert shown_reason("left", i_blocked=False) == "left"
    assert shown_reason("left", i_blocked=True) == "left"
    assert shown_reason("blocked", i_blocked=True) == "blocked"
    assert shown_reason("blocked", i_blocked=False) == "ended"


def test_one_n29_key_per_thread_recipient_and_half_hour() -> None:
    thread, user = UUID(int=1), UUID(int=2)
    start = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
    assert bucket(start) == bucket(start + timedelta(seconds=BUCKET_SECONDS - 1))
    assert bucket(start + timedelta(minutes=30)) == bucket(start) + 1
    assert message_key(thread, user, start) == f"n29:{thread}:{user}:{bucket(start)}"
    assert team_thread_path(thread) == f"/dev/teams/{thread}"


def test_titles_fit_the_bell() -> None:
    assert fit(INVITED_TITLE, handle="dev-amina") == "Team-up invitation from dev-amina"
    assert (
        fit(ACCEPTED_TITLE, handle="dev-brian", problem="Tower\nsites") == "dev-brian accepted: team up on Tower sites"
    )
    long = fit(ACCEPTED_TITLE, handle="dev-brian", problem="x" * 400)
    assert len(long) == MAX_TITLE_CHARS
    assert long.endswith("…")
