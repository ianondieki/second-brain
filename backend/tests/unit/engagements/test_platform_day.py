"""REQ-ENG-10 (part): the engagement detail's ``today`` is the day the side-state rules count from: the Nairobi date of
the platform clock (``app_clock_now()``, moved by the dev/test clock where it is on), read with the helper the hold
check uses, so the web app and the API agree on the dates a hold may take."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.policy import get_policy
from bridge.engagements.service import app_now

POLICY = get_policy()


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
    now = await app_now(Clock(real + moved))  # type: ignore[arg-type]
    today = sm.platform_day(now)
    assert today == (real + moved).astimezone(NAIROBI).date()
    # The hold check counts from the same day: the day after is the first resume date it takes, today is refused.
    sm.check_resume_at(today + timedelta(days=1), now, POLICY)
    with pytest.raises(sm.Invalid):
        sm.check_resume_at(today, now, POLICY)


def test_the_day_turns_at_midnight_in_nairobi_not_utc() -> None:
    late_utc = datetime(2026, 10, 2, 21, 30, tzinfo=UTC)  # 00:30 on 3 Oct in Nairobi
    assert sm.platform_day(late_utc).isoformat() == "2026-10-03"
