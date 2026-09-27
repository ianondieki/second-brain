"""REQ-LLM-01 / ADR-005 decision 1: no model id is hard-coded outside ``backend/ai/models.yaml``."""

from __future__ import annotations

import re
from pathlib import Path

import bridge
from bridge.config import get_settings
from bridge.llm import registry

SRC = Path(bridge.__file__).resolve().parent
MODEL_ID = re.compile(r"claude-[a-z0-9]", re.IGNORECASE)
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".md", ".sql", ".j2", ".html"}


def test_no_model_id_under_src_bridge() -> None:
    offenders = []
    for path in SRC.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if MODEL_ID.search(line):
                    offenders.append(f"{path.relative_to(SRC)}:{number}")
    assert offenders == [], f"model ids belong in ai/models.yaml only: {offenders}"


def test_the_registry_holds_the_spec_models() -> None:
    """The three runtime models of docs/spec/09 are registered (and only in the YAML)."""
    ids = set(registry.load(get_settings().llm_models_file).models)
    assert {"claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5"} <= ids
