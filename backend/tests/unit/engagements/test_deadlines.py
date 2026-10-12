"""REQ-ENG-13 (docs/platform/tasks/P27.md track A, acceptance 1, the unit half): the deadlines' window, the Nairobi
day boundary, business days over a weekend and a holiday, ``overdue`` at the very instant, the calendar entry of one
deadline (DTSTART at due_at, 15 minutes, "<title> — due", a stable UID, the tracker's absolute URL; an event spans its
own start and end) and the feed's capability token (32 random bytes, base64url without padding, only its SHA-256
kept, anything else in the URL refused before the database is asked)."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from bridge.engagements import deadlines, feeds
from bridge.engagements import state_machine as sm
from bridge.engagements.deadlines import Item, Viewer, Window
from bridge.engagements.schemas import DeadlineKind
from bridge.errors import ApiError
from bridge.models.enums import EngagementParty

ENGAGEMENT = UUID("01927f00-0000-7000-8000-0000000000e1")
EVENT = UUID("01927f00-0000-7000-8000-0000000000e2")
ORG = UUID("01927f00-0000-7000-8000-0000000000e3")
MASHUJAA = date(2026, 10, 20)  # Tuesday, an observed holiday
FRIDAY = date(2026, 10, 16)
MONDAY = date(2026, 10, 12)
EAT_MIDNIGHT_SAT = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)  # 00:00 on Saturday 17 Oct in Nairobi


def stage(due_at: datetime, *, kind: DeadlineKind = DeadlineKind.STAGE, mine: bool = True) -> Item:
    return Item(
        kind=kind,
        item_id=ENGAGEMENT,
        title="Under review: Smart irrigation",
        context="Telco A",
        href=f"/dev/engagements/{ENGAGEMENT}",
        due_at=due_at,
        mine=mine,
        engagement_id=ENGAGEMENT,
    )


def event(starts_at: datetime) -> Item:
    return Item(
        kind=DeadlineKind.EVENT,
        item_id=EVENT,
        title="Nairobi AI meetup",
        context="Telco A",
        href=f"/dev/events/{EVENT}",
        due_at=starts_at,
        mine=True,
        engagement_id=None,
        ends_at=starts_at + timedelta(hours=2),
    )


# ------------------------------------------------------------------------------------------------------- the window


def test_the_default_window_is_every_overdue_item_and_the_next_90_days() -> None:
    assert deadlines.window(MONDAY, None, None) == Window(start=None, end=MONDAY + timedelta(days=90))


def test_an_explicit_window_and_a_start_alone() -> None:
    assert deadlines.window(MONDAY, date(2026, 10, 1), date(2026, 10, 31)) == Window(
        date(2026, 10, 1), date(2026, 10, 31)
    )
    assert deadlines.window(MONDAY, date(2026, 11, 1), None) == Window(date(2026, 11, 1), date(2027, 1, 30))
    assert deadlines.window(MONDAY, None, date(2026, 10, 31)) == Window(None, date(2026, 10, 31))


@pytest.mark.parametrize(
    ("start", "end"),
    [(date(2026, 10, 31), date(2026, 10, 1)), (date(2026, 1, 1), date(2027, 1, 3)), (None, date(2027, 10, 14))],
)
def test_a_reversed_or_overlong_window_is_refused(start: date | None, end: date) -> None:
    with pytest.raises(ApiError) as refused:
        deadlines.window(MONDAY, start, end)
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == "invalid_range"


def test_overdue_items_stay_in_the_default_window_only() -> None:
    now = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    late = deadlines.build(stage(sm.end_of_day(date(2026, 9, 1))), now=now, holidays=frozenset())
    soon = deadlines.build(stage(sm.end_of_day(date(2026, 10, 30))), now=now, holidays=frozenset())
    far = deadlines.build(stage(sm.end_of_day(date(2027, 1, 30))), now=now, holidays=frozenset())
    past_event = deadlines.build(event(datetime(2026, 10, 1, 6, 0, tzinfo=UTC)), now=now, holidays=frozenset())
    default = deadlines.window(MONDAY, None, None)
    assert [deadlines.in_window(d, default, MONDAY) for d in (late, soon, far, past_event)] == [
        True,
        True,
        False,
        False,
    ]
    october = deadlines.window(MONDAY, date(2026, 10, 1), date(2026, 10, 31))
    assert [deadlines.in_window(d, october, MONDAY) for d in (late, soon, far, past_event)] == [
        False,
        True,
        False,
        True,
    ]


# ------------------------------------------------------------------------------------- the Nairobi day and the clock


def test_a_stage_deadline_falls_on_its_nairobi_day_and_is_overdue_one_instant_later() -> None:
    due_at = sm.end_of_day(FRIDAY)  # 23:59:59 EAT = 20:59:59 UTC
    at = deadlines.build(stage(due_at), now=due_at, holidays=frozenset())
    assert (at.out.due_on, at.out.due_at, at.out.overdue) == (
        FRIDAY,
        datetime(2026, 10, 16, 20, 59, 59, tzinfo=UTC),
        False,
    )
    after = deadlines.build(stage(due_at), now=EAT_MIDNIGHT_SAT, holidays=frozenset())
    assert after.out.overdue is True
    assert after.out.business_days_left == 0  # Saturday in Nairobi: no business day between Friday and today
    assert after.out.due_at.tzinfo is UTC


def test_an_event_just_after_midnight_in_nairobi_is_on_the_nairobi_day() -> None:
    starts = datetime(2026, 10, 16, 21, 30, tzinfo=UTC)  # 00:30 on Saturday 17 Oct in Nairobi, Friday in UTC
    built = deadlines.build(event(starts), now=datetime(2026, 10, 18, 9, 0, tzinfo=UTC), holidays=frozenset())
    assert built.out.due_on == date(2026, 10, 17)
    assert built.out.overdue is False  # an event is never "missed"


def test_business_days_left_skip_the_weekend_and_a_holiday() -> None:
    now = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)  # Friday morning in Nairobi
    due = sm.end_of_day(date(2026, 10, 22))  # Thursday: Mon 19, (Tue 20 Mashujaa), Wed 21, Thu 22
    assert deadlines.build(stage(due), now=now, holidays=frozenset({MASHUJAA})).out.business_days_left == 3
    assert deadlines.build(stage(due), now=now, holidays=frozenset()).out.business_days_left == 4


def test_the_key_and_the_outward_fields() -> None:
    built = deadlines.build(
        stage(sm.end_of_day(FRIDAY), kind=DeadlineKind.ANSWER, mine=False), now=EAT_MIDNIGHT_SAT, holidays=frozenset()
    )
    assert built.out.key == f"answer:{ENGAGEMENT}"
    assert (built.out.kind, built.out.mine, built.out.engagement_id) == (DeadlineKind.ANSWER, False, ENGAGEMENT)


def test_the_viewer_party_and_sort_order() -> None:
    assert Viewer(ENGAGEMENT).party is EngagementParty.DEVELOPER
    assert Viewer(ENGAGEMENT, ORG).party is EngagementParty.ORG
    now = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    later = deadlines.build(stage(sm.end_of_day(FRIDAY)), now=now, holidays=frozenset())
    sooner = deadlines.build(event(datetime(2026, 10, 14, 6, 0, tzinfo=UTC)), now=now, holidays=frozenset())
    assert deadlines.ordered([later, sooner]) == [sooner, later]


# ---------------------------------------------------------------------------------------------- the calendar entry


def test_a_deadline_is_a_15_minute_entry_at_its_instant() -> None:
    built = deadlines.build(stage(sm.end_of_day(FRIDAY)), now=EAT_MIDNIGHT_SAT, holidays=frozenset())
    entry = deadlines.calendar_entry(built, base_url="https://wazo.example/", stamp=EAT_MIDNIGHT_SAT)
    assert entry.uid == f"stage-{ENGAGEMENT}@wazo.example"
    assert (entry.starts_at, entry.ends_at - entry.starts_at) == (built.out.due_at, timedelta(minutes=15))
    assert entry.summary == "Under review: Smart irrigation — due"
    assert entry.description == "Telco A"
    assert entry.url == f"https://wazo.example/dev/engagements/{ENGAGEMENT}"
    assert entry.transparent is True
    assert entry.location is None


def test_an_event_entry_spans_the_event() -> None:
    starts = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    built = deadlines.build(event(starts), now=EAT_MIDNIGHT_SAT, holidays=frozenset())
    entry = deadlines.calendar_entry(built, base_url="https://wazo.example", stamp=EAT_MIDNIGHT_SAT)
    assert (entry.starts_at, entry.ends_at) == (starts, starts + timedelta(hours=2))
    assert entry.summary == "Nairobi AI meetup"
    assert entry.uid == f"event-{EVENT}@wazo.example"  # the event's own file's UID: one entry in a calendar
    assert entry.transparent is False


# --------------------------------------------------------------------------------------------------- feed tokens


def test_a_new_token_is_32_random_bytes_in_base64url_and_only_its_hash_is_kept() -> None:
    token, digest = feeds.new_token()
    raw = base64.urlsafe_b64decode(token + "=")
    assert len(token) == 43
    assert "=" not in token
    assert len(raw) == 32
    assert digest == hashlib.sha256(raw).digest()
    assert feeds.token_hash(token) == digest
    assert feeds.new_token()[0] != token


@pytest.mark.parametrize(
    "token",
    ["", "short", "A" * 42, "A" * 44, "A" * 42 + "=", "A" * 42 + "+", "A" * 42 + "/", "A" * 42 + "B", "Ä" * 43],
)
def test_anything_but_a_canonical_token_is_refused_before_the_database(token: str) -> None:
    assert feeds.token_hash(token) is None


def test_the_feed_url_is_absolute() -> None:
    assert feeds.feed_url("https://wazo.example/", "tok") == "https://wazo.example/api/calendar/tok.ics"
