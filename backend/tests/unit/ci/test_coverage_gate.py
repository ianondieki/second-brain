"""REQ-FND-01, docs/spec/08 "Testing & CI": the coverage gate (infra/ci/coverage_gate.py) and its place in pr.yml.

Coverage is at least 85 % overall and 95 % in ``auth``, ``tenancy``, ``billing``, ``provenance`` and ``engagements``,
statements and branches combined (coverage's ``percent_covered``). The gate runs as the sarif gate does, as a script
on a report, so these tests run it the same way (a subprocess on a JSON file).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
GATE = REPO / "infra" / "ci" / "coverage_gate.py"
PACKAGES = ("auth", "tenancy", "billing", "provenance", "engagements")


def summary(lines: tuple[int, int], branches: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    """A coverage.py file summary: ``lines`` and ``branches`` are (covered, total)."""
    covered, statements = lines
    covered_branches, num_branches = branches
    measured = statements + num_branches
    return {
        "covered_lines": covered,
        "num_statements": statements,
        "percent_covered": 100.0 if measured == 0 else 100 * (covered + covered_branches) / measured,
        "missing_lines": statements - covered,
        "excluded_lines": 0,
        "num_branches": num_branches,
        "num_partial_branches": 0,
        "covered_branches": covered_branches,
        "missing_branches": num_branches - covered_branches,
    }


def report(files: dict[str, dict[str, Any]], *, branch: bool = True) -> dict[str, Any]:
    keys = ("covered_lines", "num_statements", "num_branches", "covered_branches")
    totals = {key: sum(int(f[key]) for f in files.values()) for key in keys}
    covered = totals["covered_lines"] + totals["covered_branches"]
    measured = totals["num_statements"] + totals["num_branches"]
    return {
        "meta": {"format": 3, "version": "7.16.1", "branch_coverage": branch},
        "files": {path: {"summary": data} for path, data in files.items()},
        "totals": summary((totals["covered_lines"], totals["num_statements"]))
        | {"num_branches": totals["num_branches"], "covered_branches": totals["covered_branches"]}
        | {"percent_covered": 100 * covered / measured},
    }


def healthy() -> dict[str, dict[str, Any]]:
    """Every security package at 99 %, two other files of ``bridge`` at 90 %: 92.81 % in all."""
    files = {f"src/bridge/{name}/router.py": summary((99, 100)) for name in PACKAGES}
    files["src/bridge/proposals/tags.py"] = summary((900, 1000))
    files["src/bridge/config.py"] = summary((90, 100))
    return files


def gate(tmp_path: Path, content: dict[str, Any] | str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "coverage.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return subprocess.run([sys.executable, str(GATE), str(path)], capture_output=True, text=True, check=False)


def figures(output: str) -> dict[str, str]:
    """``{"total": "96.08 % ok", "auth": "99.00 % ok", ...}`` from the gate's table."""
    found = re.findall(r"^  (\w+)\s+([\d.]+ %|-)\s+minimum \d+ %\s+(ok|BELOW|NOT MEASURED)$", output, re.M)
    return {name: f"{value} {state}" for name, value, state in found}


# ------------------------------------------------------------------------------------------------ the thresholds


def test_a_healthy_report_passes_and_prints_every_figure(tmp_path: Path) -> None:
    result = gate(tmp_path, report(healthy()))
    assert result.returncode == 0, result.stdout
    assert figures(result.stdout) == {
        "total": "92.81 % ok",  # (5 * 99 + 900 + 90) / (5 * 100 + 1000 + 100)
        **dict.fromkeys(PACKAGES, "99.00 % ok"),
    }
    assert "::error" not in result.stdout


@pytest.mark.parametrize("package", PACKAGES)
def test_any_security_package_below_95_fails_and_names_its_weakest_files(tmp_path: Path, package: str) -> None:
    files = healthy()
    files[f"src/bridge/{package}/router.py"] = summary((75, 100))
    files[f"src/bridge/{package}/service.py"] = summary((100, 100))
    result = gate(tmp_path, report(files))
    assert result.returncode == 1
    assert figures(result.stdout)[package] == "87.50 % BELOW"
    assert f"::error title=Coverage below the gate::{package} 87.50 % is below 95 %" in result.stdout
    assert f"      src/bridge/{package}/router.py  75.00 %" in result.stdout
    assert f"src/bridge/{package}/service.py" not in result.stdout  # fully covered files are not listed
    assert result.stdout.count("::error") == 1


def test_the_total_below_85_fails_even_when_every_package_passes(tmp_path: Path) -> None:
    files = healthy()
    files["src/bridge/proposals/tags.py"] = summary((600, 1000))
    result = gate(tmp_path, report(files))
    assert result.returncode == 1
    assert figures(result.stdout)["total"] == "74.06 % BELOW"  # (495 + 600 + 90) / 1600
    assert "::error title=Coverage below the gate::total 74.06 % is below 85 %" in result.stdout
    assert all(figures(result.stdout)[name] == "99.00 % ok" for name in PACKAGES)


def test_statements_and_branches_count_together(tmp_path: Path) -> None:
    """Every statement of tenancy runs, but half its branches never do: combined, 110 of 120 (as coverage's
    ``percent_covered``), below 95 % although its statement coverage alone is 100 %."""
    files = healthy()
    files["src/bridge/tenancy/router.py"] = summary((100, 100), branches=(10, 20))
    result = gate(tmp_path, report(files))
    assert result.returncode == 1
    assert figures(result.stdout)["tenancy"] == "91.66 % BELOW"


def test_the_minimums_are_inclusive_and_never_rounded_up(tmp_path: Path) -> None:
    at = healthy()
    at["src/bridge/billing/router.py"] = summary((95, 100))
    exactly = gate(tmp_path, report(at))
    assert exactly.returncode == 0, exactly.stdout
    assert figures(exactly.stdout)["billing"] == "95.00 % ok"

    below = healthy()
    below["src/bridge/billing/router.py"] = summary((94_996, 100_000))  # 94.996 %: "95.00" when rounded to nearest
    result = gate(tmp_path, report(below))
    assert result.returncode == 1
    assert figures(result.stdout)["billing"] == "94.99 % BELOW"  # rounded down, never shown as the minimum


def test_a_package_that_was_not_measured_fails_closed(tmp_path: Path) -> None:
    files = {path: data for path, data in healthy().items() if "/engagements/" not in path}
    result = gate(tmp_path, report(files))
    assert result.returncode == 1
    assert figures(result.stdout)["engagements"] == "- NOT MEASURED"
    assert "::error title=Coverage below the gate::no file of bridge.engagements was measured" in result.stdout


def test_files_are_grouped_by_the_package_under_bridge_on_any_path(tmp_path: Path) -> None:
    """Subpackages count for their package; ``bridge``'s own modules and other trees count for none; Windows paths
    and a checkout directory that is itself called bridge are read the same."""
    files = healthy()
    files["src\\bridge\\auth\\oauth\\providers.py"] = summary((0, 100))  # nested, Windows separators
    files["/home/runner/work/bridge/bridge/backend/src/bridge/tenancy/deps.py"] = summary((0, 100))
    files["src/bridge/auth.py"] = summary((0, 100))  # a module named like a package: not the package
    files["tests/auth/helpers.py"] = summary((0, 100))  # outside bridge
    result = gate(tmp_path, report(files))
    shown = figures(result.stdout)
    assert (shown["auth"], shown["tenancy"], shown["billing"]) == ("49.50 % BELOW", "49.50 % BELOW", "99.00 % ok")


# ------------------------------------------------------------------------------------------------ fail closed


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (report(healthy(), branch=False), "no branch data"),
        ("{not json", "cannot read"),
        ("[]", "not a JSON object"),
        ({"meta": {"branch_coverage": True}, "totals": summary((1, 1))}, "lists no files"),
        (report(healthy()) | {"totals": {"covered_lines": 1}}, "no count"),
        (report(healthy()) | {"files": {"src/bridge/auth/x.py": {"summary": {"covered_lines": "9"}}}}, "no count"),
    ],
    ids=["no-branches", "not-json", "not-an-object", "no-files", "no-totals", "bad-file-summary"],
)
def test_an_unreadable_report_fails_the_gate(tmp_path: Path, content: dict[str, Any] | str, reason: str) -> None:
    result = gate(tmp_path, content)
    assert result.returncode == 1
    assert result.stdout.startswith("::error title=Coverage gate::cannot read")
    assert reason in result.stdout


def test_a_missing_report_fails_and_a_wrong_call_is_a_usage_error(tmp_path: Path) -> None:
    missing = subprocess.run(
        [sys.executable, str(GATE), str(tmp_path / "absent.json")], capture_output=True, text=True, check=False
    )
    assert missing.returncode == 1
    assert "cannot read" in missing.stdout
    usage = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True, check=False)
    assert usage.returncode == 2
    assert "usage:" in usage.stderr


# ------------------------------------------------------------------------------------------------ a real report


def _measure(tree: Path, calls: str) -> Path:
    """Run coverage (this environment's version, branch on) over a small ``bridge`` tree; return its JSON report.
    The child gets its own data file, whatever measures this test run."""
    (tree / "run.py").write_text(f"import sys\nsys.path.insert(0, 'src')\n{calls}\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE", "COVERAGE"))}
    env["COVERAGE_FILE"] = str(tree / ".coverage")
    for args in (["run", "--branch", "--source=bridge", "run.py"], ["json", "-q", "-o", "coverage.json"]):
        subprocess.run([sys.executable, "-m", "coverage", *args], cwd=tree, env=env, check=True, capture_output=True)
    return tree / "coverage.json"


def test_a_report_written_by_coverage_itself_is_read(tmp_path: Path) -> None:
    """Six packages with one two-way rule each (4 statements, 2 branches): all run both ways pass; tenancy run one way
    only is 3 of 4 statements and 1 of 2 branches, 66.66 %."""
    source = tmp_path / "src" / "bridge"
    for package in (*PACKAGES, "proposals"):
        (source / package).mkdir(parents=True)
        (source / package / "__init__.py").write_text("", encoding="utf-8")
        (source / package / "rules.py").write_text(
            "def decide(flag):\n    if flag:\n        return 'yes'\n    return 'no'\n", encoding="utf-8"
        )
    (source / "__init__.py").write_text("", encoding="utf-8")
    calls = [f"from bridge.{p}.rules import decide as d{i}; d{i}(True); d{i}(False)" for i, p in enumerate(PACKAGES)]
    calls.append("from bridge.proposals.rules import decide as d9; d9(True); d9(False)")
    passing = subprocess.run(
        [sys.executable, str(GATE), str(_measure(tmp_path, "\n".join(calls)))], capture_output=True, text=True
    )
    assert passing.returncode == 0, passing.stdout
    assert figures(passing.stdout) == dict.fromkeys(("total", *PACKAGES), "100.00 % ok")

    calls[1] = "from bridge.tenancy.rules import decide as d1; d1(True)"
    failing = subprocess.run(
        [sys.executable, str(GATE), str(_measure(tmp_path, "\n".join(calls)))], capture_output=True, text=True
    )
    assert failing.returncode == 1
    assert figures(failing.stdout)["tenancy"] == "66.66 % BELOW"
    assert "      src/bridge/tenancy/rules.py  66.66 %" in failing.stdout


# ------------------------------------------------------------------------------------------------ pr.yml


def test_the_backend_job_measures_coverage_and_gates_it_inside_the_sandbox() -> None:
    """pr.yml's backend job runs make check-backend-coverage in the egress sandbox: check-backend (the same lint,
    drift check and tests) with pytest measuring coverage, then the gate on its report."""
    raw: dict[Any, Any] = yaml.safe_load((REPO / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
    runs = [str(step.get("run", "")) for step in raw["jobs"]["backend"]["steps"]]
    [check] = [run for run in runs if "make check-backend" in run]
    assert check.startswith("infra/ci/sandboxed.sh ")
    assert check.endswith(" make check-backend-coverage")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^\tcd backend && \$\(UV\) run pytest \$\(PYTEST_ARGS\)$", makefile, re.M)
    assert re.search(r"^check-backend-coverage: PYTEST_ARGS = --cov --cov-report=json:coverage\.json$", makefile, re.M)
    rule = re.search(r"^check-backend-coverage: check-backend\n((?:\t.*\n?)+)", makefile, re.M)
    assert rule is not None
    assert rule.group(1).strip() == "cd backend && $(UV) run python ../infra/ci/coverage_gate.py coverage.json"
