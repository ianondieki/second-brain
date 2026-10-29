"""Fail when a SARIF result has a CodeQL security severity at or above a threshold (AC-SEC-4).

Usage: python3 infra/ci/sarif_gate.py <sarif dir or file> <threshold, e.g. 7.0>. Stdlib only.
CodeQL puts ``security-severity`` (CVSS-like, 7.0+ = high, 9.0+ = critical) on rule properties.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _rule_score(rule: dict[str, object]) -> float | None:
    score = rule.get("properties", {}).get("security-severity")  # type: ignore[union-attr]
    return None if score is None else float(score)  # type: ignore[arg-type]


def severities(sarif: dict[str, object]) -> list[tuple[str, float, str]]:
    """Every result with a security severity. A result whose rule cannot be resolved (no ``ruleId``, ``rule.id`` or
    valid ``rule.index``) counts as critical (10.0): the gate fails closed rather than skipping it."""
    found: list[tuple[str, float, str]] = []
    for run in sarif.get("runs", []):  # type: ignore[union-attr]
        tool = run.get("tool", {})
        components = [tool.get("driver", {}), *tool.get("extensions", [])]
        by_id: dict[str, float | None] = {}
        for component in components:
            for rule in component.get("rules", []):
                by_id[rule["id"]] = _rule_score(rule)
        for result in run.get("results", []):
            ref = result.get("rule", {})
            rule_id = result.get("ruleId") or ref.get("id")
            score: float | None
            if rule_id in by_id:
                score = by_id[rule_id]
            else:
                index = ref.get("index")
                component_index = ref.get("toolComponent", {}).get("index")
                component = components[component_index + 1] if isinstance(component_index, int) else components[0]
                rules = component.get("rules", [])
                if isinstance(index, int) and 0 <= index < len(rules):
                    rule_id, score = rules[index]["id"], _rule_score(rules[index])
                elif rule_id:
                    score = None  # a rule without metadata: not a security query
                else:
                    rule_id, score = "unresolved-rule", 10.0
            if score is not None:
                location = result.get("locations", [{}])[0].get("physicalLocation", {})
                where = f"{location.get('artifactLocation', {}).get('uri', '?')}:{location.get('region', {}).get('startLine', '?')}"
                found.append((str(rule_id), score, where))
    return found


def main(argv: list[str]) -> int:
    target, threshold = Path(argv[1]), float(argv[2])
    files = sorted(target.glob("*.sarif")) if target.is_dir() else [target]
    blocking = []
    for path in files:
        for rule_id, score, where in severities(json.loads(path.read_text(encoding="utf-8"))):
            if score >= threshold:
                blocking.append(f"{rule_id} ({score}) at {where}")
    for line in blocking:
        print(f"::error title=CodeQL high/critical::{line}")
    print(f"{len(blocking)} result(s) at security severity >= {threshold} in {len(files)} SARIF file(s)")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
