"""REQ-SCOUT-02 (Express interest from a match, REQ-ENG-04 stage 0): the match detail's ``today`` is the platform
clock's Nairobi day, read as the engagement detail's is, so the form's default contact-by date is one
``check_contact_by`` accepts, whatever the dev/test clock says."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.policy import get_policy
from bridge.matching.matches import platform_today
from bridge.matching.schemas import MatchDetail


class Clock:
    """A session whose ``SELECT app_clock_now()`` answers ``now`` (the shared clock, moved or not)."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    async def execute(self, *_: Any) -> Any:
        now = self.now

        class Result:
            def scalar_one(self) -> datetime:
                return now

        return Result()


@pytest.mark.parametrize("moved", [timedelta(0), timedelta(days=30)])
async def test_today_is_the_platform_clocks_nairobi_day(moved: timedelta) -> None:
    real = datetime.now(UTC)
    today = await platform_today(Clock(real + moved))  # type: ignore[arg-type]
    assert today == (real + moved).astimezone(NAIROBI).date()
    # Express interest's check counts from the same day: today itself is a contact-by date it takes.
    sm.check_contact_by(today, real + moved, frozenset(), get_policy())


def test_today_is_optional_in_the_published_schema() -> None:
    schema = MatchDetail.model_json_schema(mode="serialization")
    assert "today" not in schema.get("required", [])
    assert "default" not in schema["properties"]["today"]
