"""Output schemas used by the LLM-layer tests (the synthetic cassettes answer in this shape)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from bridge.llm.cassettes import CassettePlayer
from bridge.llm.demo_fallback import DEMO_TEXT
from bridge.llm.types import LLMOutput

CASSETTES = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes"


class Verdict(LLMOutput):
    verdict: Literal["clean", "hold"]
    reason: str

    @classmethod
    def demo_fallback(cls) -> Self:
        """The safe placeholder of a local run's fallback (D-37): hold for a human, never a clean verdict."""
        return cls(injection_suspected=True, verdict="hold", reason=DEMO_TEXT)


def player(*names: str) -> CassettePlayer:
    return CassettePlayer.from_files(*(CASSETTES / f"{name}.json" for name in names))
