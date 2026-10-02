"""The tracker's numbers from ``backend/config/policy.yaml`` (REQ-ENG-01, REQ-BD-01; docs/spec/13 "Other defaults").

The state machine cites these values by key; nothing else defines a deadline. Loading validates every value and
fails closed (``PolicyError``) on a missing stage, an unknown key or a number out of range, so a typo never becomes a
silent default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bridge.config import BACKEND_DIR
from bridge.models.enums import EngagementState

POLICY_FILE = BACKEND_DIR / "config" / "policy.yaml"

# The open main-path states: each has a policy entry (IN_IMPLEMENTATION's is empty: its deadlines are per milestone).
STAGE_KEYS = (
    EngagementState.ORG_INTEREST,
    EngagementState.SUBMITTED,
    EngagementState.UNDER_REVIEW,
    EngagementState.INTEREST_CONFIRMED,
    EngagementState.CONTACT_MADE,
    EngagementState.NDA_PENDING,
    EngagementState.NDA_SIGNED,
    EngagementState.NEGOTIATION,
    EngagementState.AGREEMENT_SIGNING,
    EngagementState.IN_IMPLEMENTATION,
    EngagementState.DELIVERED,
    EngagementState.SIGN_OFF,
    EngagementState.PAYMENT_FINAL,
)
_STAGE_FIELDS = frozenset({"due_bd", "expire_bd", "escalate_bd", "auto_confirm_bd", "remind_bd"})
# The stages an engagement expires from when nobody acts (docs/spec/06 6.9; the expiry job, REQ-ENG-10): each needs
# expire_bd, no other stage may carry one (nothing would read it), and it never falls before the stage's deadline.
EXPIRING_STAGES = (
    EngagementState.ORG_INTEREST,
    EngagementState.SUBMITTED,
    EngagementState.UNDER_REVIEW,
    EngagementState.INTEREST_CONFIRMED,
)
_MAX_BD = 60
_MAX_HOLD_DAYS = 60  # docs/spec/06 6.9 side branches: ON_HOLD resumes at most 60 days ahead


class PolicyError(ValueError):
    """policy.yaml is missing a value, has an unknown key or a value out of range."""


@dataclass(frozen=True, slots=True)
class StagePolicy:
    due_bd: int | None = None
    expire_bd: int | None = None
    escalate_bd: int | None = None
    auto_confirm_bd: int | None = None
    remind_bd: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TrackerPolicy:
    stages: Mapping[EngagementState, StagePolicy]
    contact_by_max_bd: int
    review_window_bd_default: int
    review_window_bd_max: int
    milestone_reminder_bd: int
    milestone_escalation_bd: int
    max_milestones: int
    deemed_acceptance_days_max: int
    exclusivity_max_chars: int
    decline_other_min_chars: int
    decline_other_max_chars: int
    on_hold_max_days: int  # a hold's resume date is at most this many calendar days after the day it starts

    def stage(self, state: EngagementState) -> StagePolicy:
        """The policy of an open main-path stage; an empty one for any other state (no deadline)."""
        return self.stages.get(state, StagePolicy())


def _bd(value: Any, where: str, *, low: int = 1, high: int = _MAX_BD) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PolicyError(f"policy.yaml: {where} must be a whole number from {low} to {high}, got {value!r}")
    return value


def _section(data: Mapping[str, Any], name: str, fields: set[str]) -> Mapping[str, Any]:
    section = data.get(name)
    if not isinstance(section, Mapping):
        raise PolicyError(f"policy.yaml: missing section {name!r}")
    if set(section) != fields:
        raise PolicyError(f"policy.yaml: {name} must have exactly {sorted(fields)}, got {sorted(section)}")
    return section


def _stage(name: str, raw: Any) -> StagePolicy:
    if not isinstance(raw, Mapping):
        raise PolicyError(f"policy.yaml: stages.{name} must be a mapping")
    unknown = set(raw) - _STAGE_FIELDS
    if unknown:
        raise PolicyError(f"policy.yaml: stages.{name} has unknown keys {sorted(unknown)}")
    values = {key: _bd(raw[key], f"stages.{name}.{key}") for key in _STAGE_FIELDS - {"remind_bd"} if key in raw}
    remind = raw.get("remind_bd", [])
    if not isinstance(remind, list):
        raise PolicyError(f"policy.yaml: stages.{name}.remind_bd must be a list")
    return StagePolicy(**values, remind_bd=tuple(_bd(v, f"stages.{name}.remind_bd") for v in remind))


def parse_policy(data: Any) -> TrackerPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, Mapping) or set(raw_stages) != {s.value for s in STAGE_KEYS}:
        raise PolicyError(f"policy.yaml: stages must list exactly {[s.value for s in STAGE_KEYS]}")
    stages = {EngagementState(name): _stage(name, raw) for name, raw in raw_stages.items()}
    for state, stage in stages.items():
        if state is not EngagementState.IN_IMPLEMENTATION and stage.due_bd is None:
            raise PolicyError(f"policy.yaml: stages.{state.value}.due_bd is required")
        if (stage.expire_bd is not None) != (state in EXPIRING_STAGES):
            raise PolicyError(
                f"policy.yaml: expire_bd is required on {[s.value for s in EXPIRING_STAGES]} and only there"
                f" (stages.{state.value})"
            )
        if stage.expire_bd is not None and stage.due_bd is not None and stage.expire_bd < stage.due_bd:
            raise PolicyError(f"policy.yaml: stages.{state.value}.expire_bd is before its due_bd")
    contact = _section(data, "contact", {"contact_by_max_bd"})
    milestones = _section(
        data,
        "milestones",
        {"review_window_bd_default", "review_window_bd_max", "reminder_bd", "escalation_bd", "max_per_agreement"},
    )
    agreement = _section(data, "agreement", {"deemed_acceptance_days_max", "exclusivity_max_chars"})
    decline = _section(data, "decline", {"other_min_chars", "other_max_chars"})
    on_hold = _section(data, "on_hold", {"max_days"})
    policy = TrackerPolicy(
        stages=stages,
        contact_by_max_bd=_bd(contact["contact_by_max_bd"], "contact.contact_by_max_bd"),
        review_window_bd_default=_bd(milestones["review_window_bd_default"], "milestones.review_window_bd_default"),
        review_window_bd_max=_bd(milestones["review_window_bd_max"], "milestones.review_window_bd_max"),
        milestone_reminder_bd=_bd(milestones["reminder_bd"], "milestones.reminder_bd"),
        milestone_escalation_bd=_bd(milestones["escalation_bd"], "milestones.escalation_bd"),
        max_milestones=_bd(milestones["max_per_agreement"], "milestones.max_per_agreement", high=50),
        # The database's CHECKs bound these: deemed acceptance 0-90 days, exclusivity 500 characters.
        deemed_acceptance_days_max=_bd(
            agreement["deemed_acceptance_days_max"], "agreement.deemed_acceptance_days_max", high=90
        ),
        exclusivity_max_chars=_bd(agreement["exclusivity_max_chars"], "agreement.exclusivity_max_chars", high=500),
        decline_other_min_chars=_bd(decline["other_min_chars"], "decline.other_min_chars", high=200),
        decline_other_max_chars=_bd(decline["other_max_chars"], "decline.other_max_chars", high=4000),
        on_hold_max_days=_bd(on_hold["max_days"], "on_hold.max_days", high=_MAX_HOLD_DAYS),
    )
    if policy.review_window_bd_default > policy.review_window_bd_max:
        raise PolicyError("policy.yaml: milestones.review_window_bd_default exceeds review_window_bd_max")
    if policy.decline_other_min_chars > policy.decline_other_max_chars:
        raise PolicyError("policy.yaml: decline.other_min_chars exceeds other_max_chars")
    return policy


def load_policy(path: Path = POLICY_FILE) -> TrackerPolicy:
    return parse_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_policy() -> TrackerPolicy:
    """The process-wide policy (read once)."""
    return load_policy()
