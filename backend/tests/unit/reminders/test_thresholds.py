"""REQ-REM-01, REQ-REM-02: the reminders' health thresholds and send times live in ``backend/config/policy.yaml``
(section ``reminders``), next to the tracker's deadlines, loaded and validated like P5's tracker policy: a missing
value, an unknown key or a value out of range stops the app (``PolicyError``), never a silent default. The rules read
the loaded values."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import time
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError, load_policy
from bridge.reminders.health import Health, assess, quiet_since, repo_cold
from bridge.reminders.nudge import DeveloperFacts, compose_nudge
from bridge.reminders.org_digest import OrgFacts, compose_digest
from bridge.reminders.thresholds import ReminderPolicy, get_reminder_policy, load_reminder_policy, parse_reminder_policy
from tests.unit.reminders.builders import MONDAY, NO_HOLIDAYS, M, days, engagement, milestone, user_id

SPEC = ReminderPolicy(
    due_soon_bd=2,
    off_track_after_days=7,
    rework_loops_off_track=2,
    cold_after_bd=3,
    quiet_after_days=5,
    upcoming_days=14,
    developer_send_after=time(7, 30),
    organisation_send_after=time(8, 30),
)


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_shipped_policy_has_the_spec_thresholds() -> None:
    """docs/spec/06 6.11: due within 2 BD, overdue >7 days, rework loop >= 2, cold after 3 BD; 07:30 and 08:30 EAT."""
    assert load_reminder_policy() == SPEC
    assert get_reminder_policy() is get_reminder_policy()
    assert load_policy().stage  # the tracker's loader still reads the same file


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: d.pop("reminders"), "missing section 'reminders'"),
        (lambda d: d["reminders"].pop("due_soon_bd"), "must have exactly"),
        (lambda d: d["reminders"].update(colour="red"), "must have exactly"),
        (lambda d: d["reminders"].update(due_soon_bd=-1), "reminders.due_soon_bd"),
        (lambda d: d["reminders"].update(off_track_after_days=0), "reminders.off_track_after_days"),
        (lambda d: d["reminders"].update(quiet_after_days=True), "reminders.quiet_after_days"),
        (lambda d: d["reminders"].update(upcoming_days=400), "reminders.upcoming_days"),
        (lambda d: d["reminders"].update(developer_send_after="7:30am"), "reminders.developer_send_after"),
        (lambda d: d["reminders"].update(organisation_send_after="25:00"), "reminders.organisation_send_after"),
        (lambda d: d["reminders"].update(developer_send_after=730), "reminders.developer_send_after"),
        (lambda d: d.update(version=2), "version 1"),
    ],
)
def test_a_broken_reminders_section_is_refused(change: Any, match: str) -> None:
    data = raw()
    change(data)
    with pytest.raises(PolicyError, match=match):
        parse_reminder_policy(data)


def test_the_rules_read_the_loaded_thresholds() -> None:
    strict = replace(SPEC, due_soon_bd=4, quiet_after_days=10, upcoming_days=40)
    in_three = engagement(milestones=(milestone(days(3)),))  # Thursday from Monday: 3 business days
    assert assess(in_three, MONDAY, NO_HOLIDAYS).health is Health.ON_TRACK
    assert assess(in_three, MONDAY, NO_HOLIDAYS, strict).health is Health.AT_RISK
    late = engagement(milestones=(milestone(days(-8)),))
    lenient = replace(SPEC, off_track_after_days=10, rework_loops_off_track=3)
    assert assess(late, MONDAY, NO_HOLIDAYS, lenient).health is Health.AT_RISK
    looped = engagement(milestones=(milestone(days(30), rework_loops=2),))
    assert assess(looped, MONDAY, NO_HOLIDAYS, lenient).health is Health.ON_TRACK
    cold = engagement(repo_linked=True, last_repo_activity_on=days(-7))
    assert repo_cold(cold, MONDAY, NO_HOLIDAYS) is not None
    assert repo_cold(cold, MONDAY, NO_HOLIDAYS, replace(SPEC, cold_after_bd=6)) is None
    quiet = engagement(last_developer_update_on=days(-6))
    assert quiet_since(quiet, MONDAY) == days(-6)
    assert quiet_since(quiet, MONDAY, strict) is None
    far = engagement(milestones=(milestone(days(30), M.PLANNED),))
    nudge = compose_nudge(DeveloperFacts(user_id(), MONDAY, (far,)), NO_HOLIDAYS, strict)
    assert nudge.needs_you[0].startswith("Milestone 1")  # listed one by one within 40 days
    assert compose_nudge(DeveloperFacts(user_id(), MONDAY, (far,)), NO_HOLIDAYS).needs_you[0].startswith("“")
    digest = compose_digest(OrgFacts(far.org_id, "Org", MONDAY, "daily", (far,)), NO_HOLIDAYS, strict)
    assert "Milestones due: milestone 1" in digest.entries[0].line
