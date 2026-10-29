"""The reminders' numbers from ``backend/config/policy.yaml``, section ``reminders`` (REQ-REM-01, REQ-REM-02;
docs/spec/06 6.11; docs/spec/13 "Other defaults").

The health rules (``bridge.reminders.health``), the nudge, the digest and the dispatcher's start times read these
values; nothing else defines them. Loaded and validated like the tracker's policy (``bridge.engagements.policy``,
which reads the same file): a missing section or value, an unknown key or a value out of range raises
``PolicyError`` at first use, so a typo never becomes a silent default.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError

_TIME: Final = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_RANGES: Final[Mapping[str, tuple[int, int]]] = {
    "due_soon_bd": (0, 10),
    "off_track_after_days": (1, 60),
    "rework_loops_off_track": (1, 10),
    "cold_after_bd": (1, 20),
    "quiet_after_days": (1, 60),
    "upcoming_days": (1, 60),
}
_TIMES: Final = ("developer_send_after", "organisation_send_after")


@dataclass(frozen=True, slots=True)
class ReminderPolicy:
    """``due_soon_bd``: an item due within this many BD with no action is at risk; ``off_track_after_days``: overdue by
    more is off track; ``rework_loops_off_track``: a milestone sent back this many times is off track;
    ``cold_after_bd``: the repo-cold rule; ``quiet_after_days``: "No update from {developer} since {date}";
    ``upcoming_days``: open milestones due within this many days are listed one by one; the send-after times are EAT."""

    due_soon_bd: int
    off_track_after_days: int
    rework_loops_off_track: int
    cold_after_bd: int
    quiet_after_days: int
    upcoming_days: int
    developer_send_after: time
    organisation_send_after: time


def _whole(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PolicyError(f"policy.yaml: {where} must be a whole number from {low} to {high}, got {value!r}")
    return value


def _clock(value: Any, where: str) -> time:
    match = _TIME.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise PolicyError(f"policy.yaml: {where} must be a 24-hour HH:MM time (EAT), got {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def parse_reminder_policy(data: Any) -> ReminderPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("reminders")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'reminders'")
    fields = {*_RANGES, *_TIMES}
    if set(section) != fields:
        raise PolicyError(f"policy.yaml: reminders must have exactly {sorted(fields)}, got {sorted(section)}")
    n = {key: _whole(section[key], f"reminders.{key}", *bounds) for key, bounds in _RANGES.items()}
    return ReminderPolicy(
        due_soon_bd=n["due_soon_bd"],
        off_track_after_days=n["off_track_after_days"],
        rework_loops_off_track=n["rework_loops_off_track"],
        cold_after_bd=n["cold_after_bd"],
        quiet_after_days=n["quiet_after_days"],
        upcoming_days=n["upcoming_days"],
        developer_send_after=_clock(section["developer_send_after"], "reminders.developer_send_after"),
        organisation_send_after=_clock(section["organisation_send_after"], "reminders.organisation_send_after"),
    )


def load_reminder_policy(path: Path = POLICY_FILE) -> ReminderPolicy:
    return parse_reminder_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_reminder_policy() -> ReminderPolicy:
    """The process-wide reminders policy (read once)."""
    return load_reminder_policy()
