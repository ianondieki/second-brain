"""REQ-LLM-01 / REQ-EMB-01 / ADR-005 decision 1: no model id is hard-coded outside ``backend/ai/models.yaml``: not a
Claude id, not a Hugging Face ``BAAI/`` id, not any id the registry holds."""

from __future__ import annotations

import re
from pathlib import Path

import bridge
from bridge.config import get_settings
from bridge.llm import registry

SRC = Path(bridge.__file__).resolve().parent
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".md", ".sql", ".j2", ".html"}


def patterns() -> list[re.Pattern[str]]:
    reg = registry.load(get_settings().llm_models_file)
    ids = [*reg.models, reg.embeddings.model]
    return [
        re.compile(r"claude-[a-z0-9]", re.IGNORECASE),
        re.compile(r"BAAI/", re.IGNORECASE),
        *(re.compile(re.escape(model_id), re.IGNORECASE) for model_id in ids),
    ]


def test_no_model_id_under_src_bridge() -> None:
    offenders = []
    checks = patterns()
    for path in SRC.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if any(check.search(line) for check in checks):
                    offenders.append(f"{path.relative_to(SRC)}:{number}")
    assert offenders == [], f"model ids belong in ai/models.yaml only: {offenders}"


def test_the_registry_holds_the_spec_models() -> None:
    """The runtime models of docs/spec/09 and the embedding model of ADR-005 are registered (only in the YAML)."""
    reg = registry.load(get_settings().llm_models_file)
    assert {"claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5-5"} <= set(reg.models)
    assert reg.embeddings.model == "BAAI/bge-m3"
