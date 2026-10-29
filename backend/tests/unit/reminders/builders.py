"""Fact builders for the reminder tests (frozen dates: 2026-10-05 is a Monday)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

from bridge.models.enums import EngagementParty, EngagementState, MilestoneState
from bridge.reminders.health import EngagementFact, MilestoneFact

DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
S, M = EngagementState, MilestoneState
MONDAY = date(2026, 10, 5)
BASE_URL = "https://bridge.example.test"
NO_HOLIDAYS: frozenset[date] = frozenset()


def days(n: int) -> date:
    return MONDAY + timedelta(days=n)


def milestone(due: date, state: MilestoneState = M.IN_PROGRESS, **kwargs: Any) -> MilestoneFact:
    values: dict[str, Any] = {"seq": 1, "deliverable": "Pilot for one county", "due_on": due, "state": state}
    values.update(kwargs)
    return MilestoneFact(**values)


def engagement(state: EngagementState = S.IN_IMPLEMENTATION, **kwargs: Any) -> EngagementFact:
    values: dict[str, Any] = {
        "id": uuid4(),
        "org_id": uuid4(),
        "state": state,
        "title": "Solar cold rooms",
        "org_name": "Telco A (fixture)",
        "developer_name": "Wanjiru",
        "created_on": days(-60),
        "entered_on": days(-20),
        "stage_deadline_on": None,
        "awaiting": frozenset({DEV}),
    }
    values.update(kwargs)
    return EngagementFact(**values)


def user_id() -> UUID:
    return uuid4()
