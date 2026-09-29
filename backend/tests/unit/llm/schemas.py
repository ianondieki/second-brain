"""Output schemas used by the LLM-layer tests (the synthetic cassettes answer in this shape)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from bridge.llm.cassettes import CassettePlayer
from bridge.llm.types import LLMOutput

CASSETTES = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes"


class Verdict(LLMOutput):
    verdict: Literal["clean", "hold"]
    reason: str


def player(*names: str) -> CassettePlayer:
    return CassettePlayer.from_files(*(CASSETTES / f"{name}.json" for name in names))
