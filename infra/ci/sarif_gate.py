"""Fail when a SARIF result has a CodeQL security severity at or above a threshold (AC-SEC-4).

Usage: python3 infra/ci/sarif_gate.py <sarif dir or file> <threshold, e.g. 7.0>. Stdlib only.
CodeQL puts ``security-severity`` (CVSS-like, 7.0+ = high, 9.0+ = critical) on rule properties.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def severities(sarif: dict[str, object]) -> list[tuple[str, float, str]]:
    found: list[tuple[str, float, str]] = []
    for run in sarif.get("runs", []):  # type: ignore[union-attr]
        rules: dict[str, float] = {}
        driver = run.get("tool", {}).get("driver", {})
        for rule in [*driver.get("rules", []), *(r for ext in run.get("tool", {}).get("extensions", []) for r in ext.get("rules", []))]:
            score = rule.get("properties", {}).get("security-severity")
            if score is not None:
                rules[rule["id"]] = float(score)
        for result in run.get("results", []):
            rule_id = result.get("ruleId", "")
            if rule_id in rules:
                location = result.get("locations", [{}])[0].get("physicalLocation", {})
                where = f"{location.get('artifactLocation', {}).get('uri', '?')}:{location.get('region', {}).get('startLine', '?')}"
                found.append((rule_id, rules[rule_id], where))
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
