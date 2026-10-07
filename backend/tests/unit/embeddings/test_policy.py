"""REQ-PERS-02, REQ-EMB-01: the embedding job's per-run cap comes from policy.yaml's ``embeddings`` section, validated
strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.embeddings.policy import (
    EmbeddingsPolicy,
    get_embeddings_policy,
    load_embeddings_policy,
    parse_embeddings_policy,
)
from bridge.engagements.policy import POLICY_FILE, PolicyError


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values() -> None:
    assert load_embeddings_policy() == EmbeddingsPolicy(max_rows_per_run=500)
    assert get_embeddings_policy() is get_embeddings_policy()


@pytest.mark.parametrize(
    ("key", "value"),
    [("max_rows_per_run", 0), ("max_rows_per_run", True), ("max_rows_per_run", 5001), ("max_rows_per_run", "500"),
     ("x", 1)],
)  # fmt: skip
def test_a_bad_or_unknown_value_stops_the_job(key: str, value: object) -> None:
    raw = data()
    raw["embeddings"][key] = value
    with pytest.raises(PolicyError, match="embeddings"):
        parse_embeddings_policy(raw)


def test_a_missing_section_or_version_stops_the_job() -> None:
    raw = data()
    del raw["embeddings"]
    with pytest.raises(PolicyError, match="embeddings"):
        parse_embeddings_policy(raw)
    with pytest.raises(PolicyError, match="version"):
        parse_embeddings_policy({"version": 2})
