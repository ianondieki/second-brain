"""AC-REM-3 (REQ-REM-01, REQ-REM-02) against PostgreSQL: both reminders fire from the same ``engagements`` and
``milestones`` rows, each read by its own recipient under RLS, and agree on the engagement's health."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.reminders.health import Health
from tests.integration.engagements.tracker import as_app
from tests.integration.reminders.world import DAY_BEFORE_DUE, build


@pytest.mark.parametrize(
    ("now", "health", "said"),
    [
        (DAY_BEFORE_DUE - timedelta(days=30), Health.ON_TRACK, "On track."),
        (DAY_BEFORE_DUE, Health.AT_RISK, "At risk. Milestone 1 “Pilot for one county” is due 31 Mar 2027"),
        (
            DAY_BEFORE_DUE + timedelta(days=10),
            Health.OFF_TRACK,
            "Off track. Milestone 1 “Pilot for one county” was due 31 Mar 2027 and is 9 days overdue",
        ),
    ],
)
async def test_both_reminders_fire_from_the_same_rows_and_agree_on_health(
    owner_engine: AsyncEngine, now: datetime, health: Health, said: str
) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        developer = (await w.nudges(now=now)).of(w.p.developer)
        organisation = (await w.digests([w.p.signatory], now=now)).of(w.p.signatory, w.p.org)
        assert developer is not None
        assert organisation is not None
        assert (developer.status, organisation.status) == ("sent", "sent")
        assert developer.health == organisation.health == {w.engagement: health}
        nudge, digest = w.email.outbox
        assert said in nudge.text
        assert said in digest.text
