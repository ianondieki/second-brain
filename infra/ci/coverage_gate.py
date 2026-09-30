"""Fail the backend job when coverage is below the gate (REQ-FND-01; docs/spec/08 "Testing & CI").

Usage: python3 infra/ci/coverage_gate.py <coverage.json>. Stdlib only.

The report is coverage.py's JSON (``pytest --cov --cov-report=json:coverage.json``; ``[tool.coverage.run]`` in
backend/pyproject.toml measures ``bridge`` with branch coverage). Every figure is statements and branches combined, as
coverage reports ``percent_covered``: (covered lines + covered branches) / (statements + branches). The total must be at
least 85 %, and each of the five security packages (``bridge.auth``, ``bridge.tenancy``, ``bridge.billing``,
``bridge.provenance``, ``bridge.engagements``) at least 95 %, compared exactly (a figure is never rounded up to pass).
It fails closed: a report without branch data, a summary without its counts, or no measured file of one of the five
packages fails the gate.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

TOTAL_MINIMUM = 85
PACKAGE_MINIMUM = 95
PACKAGES = ("auth", "tenancy", "billing", "provenance", "engagements")
ROOT_PACKAGE = "bridge"
WORST_FILES = 5  # the files listed under a package below its minimum, lowest first
COUNTS = ("covered_lines", "num_statements", "covered_branches", "num_branches")


class ReportError(Exception):
    """The file is not a coverage.py JSON report with branch coverage."""


@dataclass(frozen=True, slots=True)
class Figure:
    covered: int  # covered lines + covered branches
    measured: int  # statements + branches

    def __add__(self, other: Figure) -> Figure:
        return Figure(self.covered + other.covered, self.measured + other.measured)

    @property
    def ratio(self) -> Fraction:
        """Percent covered, exactly; a file with nothing to measure is fully covered (as coverage counts it)."""
        return Fraction(100) if self.measured == 0 else Fraction(100 * self.covered, self.measured)

    def meets(self, minimum: int) -> bool:
        return self.ratio >= minimum

    def shown(self) -> str:
        """Two decimals, rounded down, so a figure below the minimum never prints as the minimum."""
        return f"{math.floor(self.ratio * 100) / 100:.2f} %"


def figure_of(summary: Any) -> Figure:
    if not isinstance(summary, Mapping):
        raise ReportError("a summary is not an object")
    counts: dict[str, int] = {}
    for key in COUNTS:
        value = summary.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ReportError(f"a summary has no count {key!r} (was the report made with branch = true?)")
        counts[key] = value
    return Figure(
        counts["covered_lines"] + counts["covered_branches"], counts["num_statements"] + counts["num_branches"]
    )


def package_of(path: str) -> str | None:
    """The package directly under ``bridge`` that holds ``path`` (``auth`` for ``src/bridge/auth/sub/x.py``), or None
    for a module of ``bridge`` itself (``src/bridge/config.py``) or a file outside it."""
    folders = PurePosixPath(path.replace("\\", "/")).parts[:-1]
    if ROOT_PACKAGE not in folders:
        return None
    below = folders[len(folders) - folders[::-1].index(ROOT_PACKAGE) :]  # after the last "bridge" folder
    return below[0] if below else None


@dataclass(frozen=True, slots=True)
class Verdict:
    lines: list[str]  # what the job log shows, one figure per line
    failures: list[str]  # one sentence per figure below its minimum (or package not measured)


def evaluate(report: Any) -> Verdict:
    if not isinstance(report, Mapping):
        raise ReportError("the report is not a JSON object")
    meta, files = report.get("meta"), report.get("files")
    if not isinstance(meta, Mapping) or meta.get("branch_coverage") is not True:
        raise ReportError("the report has no branch data ([tool.coverage.run] branch = true)")
    if not isinstance(files, Mapping):
        raise ReportError("the report lists no files")
    total = figure_of(report.get("totals"))
    by_package: dict[str, dict[str, Figure]] = {name: {} for name in PACKAGES}
    for path, entry in files.items():
        package = package_of(str(path))
        if package in by_package:
            by_package[package][str(path)] = figure_of(entry.get("summary") if isinstance(entry, Mapping) else None)

    lines = ["Coverage gate: statements and branches combined (REQ-FND-01, docs/spec/08)"]
    failures: list[str] = []
    ok = total.meets(TOTAL_MINIMUM)
    lines.append(f"  {'total':<12} {total.shown():>9}  minimum {TOTAL_MINIMUM} %  {'ok' if ok else 'BELOW'}")
    if not ok:
        failures.append(f"total {total.shown()} is below {TOTAL_MINIMUM} %")
    for package in PACKAGES:
        measured = by_package[package]
        if not measured:
            lines.append(f"  {package:<12} {'-':>9}  minimum {PACKAGE_MINIMUM} %  NOT MEASURED")
            failures.append(f"no file of {ROOT_PACKAGE}.{package} was measured")
            continue
        figure = sum(measured.values(), Figure(0, 0))
        ok = figure.meets(PACKAGE_MINIMUM)
        lines.append(f"  {package:<12} {figure.shown():>9}  minimum {PACKAGE_MINIMUM} %  {'ok' if ok else 'BELOW'}")
        if not ok:
            failures.append(f"{package} {figure.shown()} is below {PACKAGE_MINIMUM} %")
            worst = sorted(measured.items(), key=lambda item: (item[1].ratio, item[0]))[:WORST_FILES]
            lines.extend(f"      {path}  {file.shown()}" for path, file in worst if not file.meets(100))
    return Verdict(lines, failures)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 infra/ci/coverage_gate.py <coverage.json>", file=sys.stderr)
        return 2
    try:
        verdict = evaluate(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    except (OSError, ValueError, ReportError) as exc:  # a missing or unreadable report fails the gate
        print(f"::error title=Coverage gate::cannot read {argv[1]}: {exc}")
        return 1
    print("\n".join(verdict.lines))
    for failure in verdict.failures:
        print(f"::error title=Coverage below the gate::{failure}")
    return 1 if verdict.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
