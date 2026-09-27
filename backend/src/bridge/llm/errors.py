"""Typed errors of the LLM layer (REQ-LLM-01; ADR-005 decision 3).

Two families: ``LLMBlocked`` (refused before anything reached a model: kill switch, caps, the Tier-2 guard, a missing
consent) and ``LLMCallFailed`` (the model answered but retries were exhausted; the request went to the dead-letter
queue). ``str()`` never carries prompt text or a Tier-2 value, only task and field names, so errors are safe to log.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar, Literal

from bridge.models.enums import ConsentPurpose


class LLMError(Exception):
    """Base class; ``code`` is stable and machine-readable."""

    code: ClassVar[str] = "llm_error"


class LLMConfigError(LLMError):
    """A caller or ``ai/models.yaml`` asked for something the registry does not allow (unknown task, effort on a
    model without effort, tools a task may not use, a schema without ``injection_suspected``)."""

    code = "llm_config"


class LLMUnavailable(LLMError):
    """No adapter can serve the call (no ``ANTHROPIC_API_KEY``); raised at call time, never at import."""

    code = "llm_unavailable"


class LLMProviderError(LLMError):
    """The provider could not be reached or answered with an HTTP error after the SDK's own retries."""

    code = "llm_provider"

    def __init__(self, message: str, *, transient: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.status_code = status_code


# ------------------------------------------------------------------------------------------ refused before the call


class LLMBlocked(LLMError):
    """Refused before any request was sent."""

    code = "llm_blocked"


class LLMKillSwitch(LLMBlocked):
    code = "llm_kill_switch"

    def __init__(self) -> None:
        super().__init__("LLM_KILL_SWITCH is on: every LLM call is refused")


class LLMBudgetExceeded(LLMBlocked):
    """The per-tenant monthly cap or the global daily cap would be exceeded by this call (the hard cap)."""

    code = "llm_budget"

    def __init__(self, scope: Literal["tenant", "global"], *, spent_usd: Decimal, cap_usd: Decimal) -> None:
        super().__init__(f"the {scope} LLM budget is exhausted (spent {spent_usd} of {cap_usd} USD)")
        self.scope = scope
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd


class Tier2NotAllowed(LLMBlocked):
    """A Tier-2 field was passed to a task whose purpose is Tier-1 only (AC-SEC-6)."""

    code = "llm_tier2_not_allowed"

    def __init__(self, task: str, fields: tuple[str, ...]) -> None:
        super().__init__(f"task {task} reads Tier-1 fields only; refused Tier-2 fields {', '.join(fields)}")
        self.task = task
        self.fields = fields


class ConsentRequired(LLMBlocked):
    """A Tier-2 field's owner holds no live consent for the task's purpose (AC-SEC-6)."""

    code = "llm_consent_required"

    def __init__(self, task: str, purpose: ConsentPurpose, fields: tuple[str, ...]) -> None:
        super().__init__(f"task {task} needs a live {purpose.value} consent for Tier-2 fields {', '.join(fields)}")
        self.task = task
        self.purpose = purpose
        self.fields = fields


# ------------------------------------------------------------------------------------------ failed after the call


class LLMCallFailed(LLMError):
    """The model answered, the retry rules were exhausted and the request was dead-lettered."""

    code = "llm_failed"

    def __init__(self, message: str, *, task: str, trace_id: str, dead_letter_id: str | None = None) -> None:
        super().__init__(message)
        self.task = task
        self.trace_id = trace_id
        self.dead_letter_id = dead_letter_id


class LLMRefused(LLMCallFailed):
    code = "llm_refused"


class LLMTruncated(LLMCallFailed):
    code = "llm_max_tokens"


class LLMSchemaError(LLMCallFailed):
    code = "llm_schema"


class LLMUnsupportedStop(LLMCallFailed):
    """A stop reason the layer does not handle yet (``tool_use`` with client tools, ``pause_turn``, context full)."""

    code = "llm_unsupported_stop"
