"""Shared inputs of the submission assistant's unit tests (REQ-PROP-05)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from bridge.errors import ApiError
from bridge.llm.types import Result, TokenUsage
from bridge.proposals.assistant import DraftText, Owned, TeaserSuggestion

OWNER = UUID("01900000-0000-7000-8000-0000000000c1")
SESSION = UUID("01900000-0000-7000-8000-0000000000e1")
PROPOSAL = UUID("01900000-0000-7000-8000-0000000000f1")
VERSION = UUID("01900000-0000-7000-8000-0000000000f2")
SECRET = "TIER2-SECRET LoRa relays every 90 s"

DRAFT = DraftText(
    Owned(PROPOSAL, OWNER, VERSION),
    tier1={"title": "Cold chain", "problem_statement": "Milk spoils.", "summary": "Alerts when a cooler warms."},
    tier2={"approach": SECRET, "pricing": "KES 25,000 setup"},
)


def answer(**overrides: Any) -> TeaserSuggestion:
    values: dict[str, Any] = {
        "injection_suspected": False,
        "has_suggestion": True,
        "title": "Cold-chain alerts for dairy farmers",
        "summary": "Farmers get an SMS the moment a milk cooler starts to warm, so less milk spoils.",
        "placement": [],
    }
    return TeaserSuggestion.model_validate(values | overrides)


def detail_of(error: ApiError) -> dict[str, Any]:
    detail: dict[str, Any] = error.detail  # type: ignore[assignment]  # ApiError always sets a dict
    return detail


def result(output: TeaserSuggestion) -> Result[TeaserSuggestion]:
    return Result(output, "end_turn", TokenUsage(), (), "m", Decimal(0), 1, "trace-1")
