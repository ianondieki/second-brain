"""REQ-UX-05 (P25-B, D-67): the activity calendar's rules without a database.

Given the platform clock and a number of weeks, when the calendar is made, then its days are Africa/Nairobi's (21:00
UTC starts the next day), it covers ``weeks`` x 7 days ending today, every day is listed oldest first (0 where nothing
happened), each kind of the caller's side is listed in a fixed order (staff get the developer's), rows of another kind
or outside the range are left out, and each kind is read only where the caller is the actor.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from bridge.me import activity
from bridge.me.caller import Caller
from bridge.me.schemas import ActivityKind

USER = UUID(int=1)
DIALECT = create_engine("postgresql+psycopg://").dialect  # nothing connects
TODAY = date(2026, 10, 8)


@pytest.mark.parametrize(
    ("moment", "day"),
    [
        (datetime(2026, 10, 7, 20, 59, 59, tzinfo=UTC), date(2026, 10, 7)),
        (datetime(2026, 10, 7, 21, 0, 0, tzinfo=UTC), date(2026, 10, 8)),
        (datetime(2026, 10, 8, 20, 59, 59, tzinfo=UTC), date(2026, 10, 8)),
        (datetime(2026, 12, 31, 21, 30, tzinfo=UTC), date(2027, 1, 1)),
    ],
)
def test_a_day_is_nairobis_and_21_00_utc_starts_the_next(moment: datetime, day: date) -> None:
    assert activity.nairobi_day(moment) == day


@pytest.mark.parametrize(("weeks", "days"), [(1, 7), (26, 182), (52, 364)])
def test_the_range_is_weeks_of_days_ending_today(weeks: int, days: int) -> None:
    first, last = activity.window(TODAY, weeks)
    assert last == TODAY
    assert (last - first).days + 1 == days


def test_the_range_runs_from_the_first_nairobi_midnight_to_the_one_after_today() -> None:
    start, end = activity.bounds(date(2026, 10, 2), TODAY)
    assert start == datetime(2026, 10, 1, 21, tzinfo=UTC)
    assert end == datetime(2026, 10, 8, 21, tzinfo=UTC)


def test_every_day_is_listed_oldest_first_with_its_count() -> None:
    first, last = activity.window(TODAY, 1)
    rows = [
        ("message_sent", TODAY, 2),
        ("engagement_step", TODAY, 1),
        ("quiz_answered", first, 1),
        ("team_message", TODAY - timedelta(days=3), 4),
    ]
    found = activity.calendar("developer", first, last, rows)
    assert found.from_ == first
    assert (found.to, found.timezone) == (TODAY, "Africa/Nairobi")
    assert [(d.date, d.count) for d in found.days] == [
        (date(2026, 10, 2), 1),
        (date(2026, 10, 3), 0),
        (date(2026, 10, 4), 0),
        (date(2026, 10, 5), 4),
        (date(2026, 10, 6), 0),
        (date(2026, 10, 7), 0),
        (date(2026, 10, 8), 3),
    ]
    assert [(k.kind, k.count) for k in found.kinds] == [
        ("version_registered", 0),
        ("proposal_published", 0),
        ("engagement_step", 1),
        ("message_sent", 2),
        ("quiz_answered", 1),
        ("team_message", 4),
    ]
    assert found.total == 8


def test_a_dense_range_keeps_every_day() -> None:
    first, last = activity.window(TODAY, 26)
    rows = [("brief_posted", first + timedelta(days=n), n + 1) for n in range(182)]
    found = activity.calendar("org", first, last, rows)
    assert [d.count for d in found.days] == list(range(1, 183))
    assert found.total == sum(range(1, 183))
    assert {k.kind: k.count for k in found.kinds}["brief_posted"] == found.total


def test_rows_of_another_kind_or_outside_the_range_are_left_out() -> None:
    first, last = activity.window(TODAY, 1)
    rows = [
        ("quiz_answered", TODAY, 5),  # a developer's kind, not an organisation member's
        ("proposal_opened", first - timedelta(days=1), 2),
        ("proposal_opened", last + timedelta(days=1), 2),
        ("proposal_opened", TODAY, 1),
    ]
    found = activity.calendar("org", first, last, rows)
    assert [(k.kind, k.count) for k in found.kinds] == [
        ("proposal_opened", 1),
        ("engagement_step", 0),
        ("message_sent", 0),
        ("brief_posted", 0),
    ]
    assert found.total == 1


def test_staff_count_the_developers_kinds() -> None:
    assert activity.KINDS["staff"] == activity.DEVELOPER_KINDS
    assert [k.kind for k in activity.calendar("staff", TODAY, TODAY, []).kinds] == list(activity.DEVELOPER_KINDS)


def test_the_calendar_serialises_its_first_day_as_from() -> None:
    dumped = activity.calendar("developer", TODAY, TODAY, []).model_dump(mode="json", by_alias=True)
    assert set(dumped) == {"from", "to", "timezone", "days", "kinds", "total"}
    assert (dumped["from"], dumped["to"]) == ("2026-10-08", "2026-10-08")


ACTORS = {
    "version_registered": "proposals.owner_id = %(owner_id_1)s::UUID",
    "proposal_published": "proposals.owner_id = %(owner_id_1)s::UUID",
    "engagement_step": "engagement_events.actor_user_id = %(actor_user_id_1)s::UUID",
    "message_sent": "engagement_messages.sender_user_id = %(sender_user_id_1)s::UUID",
    "quiz_answered": "quiz_attempts.user_id = %(user_id_1)s::UUID",
    "team_message": "team_messages.sender_user_id = %(sender_user_id_1)s::UUID",
    "proposal_opened": "document_views.viewer_user_id = %(viewer_user_id_1)s::UUID",
    "brief_posted": "problems.created_by = %(created_by_1)s::UUID",
}


@pytest.mark.parametrize("kind", sorted(ACTORS))
def test_each_kind_reads_only_the_callers_own_rows(kind: ActivityKind) -> None:
    statement = activity.kind_statement(kind, Caller(USER, "developer"))
    compiled = statement.compile(dialect=DIALECT)
    assert ACTORS[kind] in str(compiled)
    assert USER in compiled.params.values()


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="no activity kind"):
        activity.kind_statement("nothing", Caller(USER, "developer"))  # type: ignore[arg-type]


def test_the_counts_group_by_the_nairobi_day_of_each_action() -> None:
    start, end = activity.bounds(TODAY, TODAY)
    statement = activity.counts_statement(Caller(USER, "org"), start, end)
    text = " ".join(str(statement.compile(dialect=DIALECT)).split())
    assert "CAST(timezone('Africa/Nairobi', actions.at) AS DATE)" in text
    assert text.endswith("GROUP BY actions.kind, CAST(timezone('Africa/Nairobi', actions.at) AS DATE)")
    assert text.count("UNION ALL") == len(activity.ORG_KINDS) - 1
