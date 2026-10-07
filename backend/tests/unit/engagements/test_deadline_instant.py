"""REQ-TRACK-03 (P23-3): the instant a deadline window closes, for the countdown in days, hours and minutes.

A tracker step's deadline and a Brief's "Proposals by" day both run to the end of their day in Africa/Nairobi (EAT,
UTC+3, no daylight saving): the window closes at 23:59:59.999999 local, sent in UTC with a ``Z``. ``due_at`` sits
beside the business days (``due_on``, ``business_days_left``, ``overdue``) and ``deadline_at`` beside the Brief's
``deadline`` (null when it has none, and derived from it, never set apart from it). Both are always sent and stay
optional in the generated web types, so clients adopt them at their own pace.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import pytest

from bridge.engagements.calendar import NAIROBI, closes_at
from bridge.engagements.schemas import DueOut
from bridge.models.enums import BriefStatus, BriefVisibility, ModerationState, ProblemStatus
from bridge.openapi import render
from bridge.problems.brief_rules import facts
from bridge.problems.brief_schemas import BriefFacts, BriefOut

DUE_ON = date(2026, 10, 16)
CLOSES = datetime(2026, 10, 16, 20, 59, 59, 999_999, tzinfo=UTC)


def test_a_day_closes_at_its_last_microsecond_in_nairobi() -> None:
    closed = closes_at(DUE_ON)
    assert closed == CLOSES
    assert closed.utcoffset() == timedelta(0)  # sent in UTC
    assert closed.astimezone(NAIROBI).time() == time.max
    assert closed + timedelta(microseconds=1) == datetime.combine(date(2026, 10, 17), time(), tzinfo=NAIROBI)


def test_a_timestamp_is_not_a_day() -> None:
    with pytest.raises(TypeError, match="calendar date"):
        closes_at(datetime(2026, 10, 16, 12, tzinfo=UTC))


def test_due_sends_the_instant_in_utc_with_a_z() -> None:
    due = DueOut(due_on=DUE_ON, due_at=closes_at(DUE_ON), business_days_left=7, overdue=False)
    assert due.model_dump(mode="json") == {
        "due_on": "2026-10-16",
        "due_at": "2026-10-16T20:59:59.999999Z",
        "business_days_left": 7,
        "overdue": False,
    }


def test_the_briefs_deadline_instant_is_derived_from_its_day() -> None:
    open_one = facts(None, None, DUE_ON, status=BriefStatus.PUBLISHED, today=date(2026, 10, 16))
    assert open_one.model_dump(mode="json")["deadline_at"] == "2026-10-16T20:59:59.999999Z"
    assert (open_one.open, open_one.ended) == (True, None)  # the deadline day itself is open
    past = facts(None, None, DUE_ON, status=BriefStatus.PUBLISHED, today=date(2026, 10, 17))
    assert (past.deadline_at, past.ended) == (CLOSES, "past_deadline")
    none = facts(None, None, None, status=BriefStatus.PUBLISHED, today=date(2026, 10, 17))
    assert none.deadline_at is None
    stray = BriefFacts(org=None, budget_band=None, deadline=None, deadline_at=CLOSES)
    assert stray.deadline_at is None  # never apart from the deadline it is derived from


def test_the_organisations_brief_carries_the_instant_too() -> None:
    brief = BriefOut(
        id=UUID("01a0f070-0000-7000-8000-000000000001"),
        title="Rural towers lose power at night",
        statement="Our rural base stations drop off the network.",
        affected_group=None,
        niche=None,
        country="KE",
        county_code=None,
        visibility=BriefVisibility.PUBLIC,
        budget_band=None,
        deadline=DUE_ON,
        status=BriefStatus.PUBLISHED,
        problem_status=ProblemStatus.PUBLISHED,
        moderation_state=ModerationState.CLEAR,
        state="published",
        proposal_count=0,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        published_at=None,
    )
    assert brief.deadline_at == CLOSES
    assert BriefOut.model_validate(brief.model_dump() | {"deadline": None}).deadline_at is None


def _schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(render())["components"]["schemas"][name]
    return schema


def test_the_instants_are_documented_and_optional_in_the_web_types() -> None:
    due = _schema("DueOut")
    assert due["properties"]["due_at"]["type"] == "string"  # never null
    assert due["properties"]["due_at"]["format"] == "date-time"
    assert "due_at" not in due["required"]
    assert set(due["required"]) == {"due_on", "business_days_left", "overdue"}
    for name in ("BriefFacts", "BriefOut"):
        brief = _schema(name)
        instant = brief["properties"]["deadline_at"]
        assert {"format": "date-time", "type": "string"} in instant["anyOf"]
        assert "default" not in instant
        assert "deadline_at" not in brief.get("required", [])
        assert "Africa/Nairobi" in instant["description"]
