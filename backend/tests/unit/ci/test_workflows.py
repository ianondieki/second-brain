"""Workflow lint for AC-SEC-4 and AC-SEC-5 (REQ-FND-03), over every file in .github/workflows/.

AC-SEC-4: gitleaks, pip-audit, npm audit, Trivy and CodeQL run on every PR and block on high/critical.
AC-SEC-5: no path in pr.yml, main.yml (Phase 8) or make check performs a real network call to an LLM, email,
WhatsApp or payment provider; only nightly.yml's evals job may reach api.anthropic.com. The network side is enforced
by infra/ci/egress-lock.sh (probed in CI) and tests/egress.py; this file checks the workflow definitions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO / ".github" / "workflows"
PROVIDER_HOSTS = (
    "api.anthropic.com",
    "api.postmarkapp.com",
    "graph.facebook.com",
    "safaricom.co.ke",
    "api.paystack.co",
    "africastalking.com",
    "api.groq.com",
    "smtp.gmail.com",
)
PROVIDER_SECRETS = re.compile(r"secrets\.(ANTHROPIC|POSTMARK|WA_|WHATSAPP|DARAJA|MPESA|PAYSTACK|GROQ|SMS)", re.I)
PR_TRIGGERS = {"pull_request", "push"}


def load(name: str) -> dict[str, Any]:
    raw: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # YAML 1.1 reads the key `on` as True.
    return {("on" if key is True else str(key)): value for key, value in raw.items()}


def workflow_files() -> list[str]:
    return sorted(p.name for p in WORKFLOWS.glob("*.yml"))


def steps_text(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) + " " + str(step.get("uses", "")) for step in job.get("steps", []))


def runs_on_pr(name: str) -> bool:
    return bool(PR_TRIGGERS & set(load(name)["on"]))


# ---------------------------------------------------------------- AC-SEC-4


SCANNERS = {
    "gitleaks": ("pr.yml", "scanners", r"gitleaks.*--exit-code 1"),
    "pip-audit": ("pr.yml", "scanners", r"pip-audit --strict"),
    "npm audit": ("pr.yml", "scanners", r"npm audit --audit-level=high"),
    "osv-scanner": ("pr.yml", "scanners", r"osv-scanner"),
    "Trivy": ("pr.yml", "scanners", r"trivy.*--severity HIGH,CRITICAL --exit-code 1"),
    "CodeQL": ("codeql.yml", "analyze", r"sarif_gate\.py sarif-results 7\.0"),
}


@pytest.mark.parametrize("scanner", sorted(SCANNERS))
def test_scanner_runs_on_every_pr_and_blocks(scanner: str) -> None:
    filename, job_id, pattern = SCANNERS[scanner]
    workflow = load(filename)
    assert runs_on_pr(filename), f"{filename} must run on pull_request and push"
    job = workflow["jobs"][job_id]
    assert re.search(pattern, steps_text(job), re.S), f"{scanner} step missing or not blocking in {filename}"
    assert job.get("continue-on-error", False) is False
    for step in job["steps"]:
        assert step.get("continue-on-error", False) is False, f"{scanner}: a step may not continue on error"


def test_codeql_covers_python_and_typescript() -> None:
    languages = load("codeql.yml")["jobs"]["analyze"]["strategy"]["matrix"]["language"]
    assert set(languages) == {"python", "javascript-typescript"}


def test_sarif_gate_blocks_high_and_passes_low(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    def sarif(score: str) -> str:
        rule = {"id": "py/x", "properties": {"security-severity": score}}
        result = {"ruleId": "py/x", "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}}}]}
        return json.dumps({"runs": [{"tool": {"driver": {"rules": [rule]}}, "results": [result]}]})

    gate = REPO / "infra" / "ci" / "sarif_gate.py"
    (tmp_path / "high.sarif").write_text(sarif("8.1"), encoding="utf-8")
    high = subprocess.run([sys.executable, str(gate), str(tmp_path / "high.sarif"), "7.0"], capture_output=True)
    (tmp_path / "low.sarif").write_text(sarif("4.0"), encoding="utf-8")
    low = subprocess.run([sys.executable, str(gate), str(tmp_path / "low.sarif"), "7.0"], capture_output=True)
    assert (high.returncode, low.returncode) == (1, 0)


def test_sarif_gate_resolves_rule_indexes_and_fails_closed(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    rules = [{"id": "py/low", "properties": {"security-severity": "3.0"}}]
    extension = {"rules": [{"id": "py/high", "properties": {"security-severity": "9.1"}}]}
    by_index: dict[str, object] = {"rule": {"index": 0, "toolComponent": {"index": 0}}, "locations": [{}]}
    unresolved: dict[str, object] = {"locations": [{}]}
    gate = REPO / "infra" / "ci" / "sarif_gate.py"
    outcomes: list[int] = []
    for result in (by_index, unresolved, {"ruleId": "py/low", "locations": [{}]}):
        run = {"tool": {"driver": {"rules": rules}, "extensions": [extension]}, "results": [result]}
        path = tmp_path / f"r{len(outcomes)}.sarif"
        path.write_text(json.dumps({"runs": [run]}), encoding="utf-8")
        outcomes.append(subprocess.run([sys.executable, str(gate), str(path), "7.0"], capture_output=True).returncode)
    assert outcomes == [1, 1, 0]  # extension rule by index blocks; an unresolvable result blocks; a low one passes


# ---------------------------------------------------------------- AC-SEC-5


@pytest.mark.parametrize("name", workflow_files())
def test_only_nightly_evals_may_name_a_provider(name: str) -> None:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    if name == "nightly.yml":
        workflow = load(name)
        for job_id, job in workflow["jobs"].items():
            dumped = yaml.safe_dump(job)
            hosts = [h for h in PROVIDER_HOSTS if h in dumped]
            allowed = job_id == "evals" and hosts in ([], ["api.anthropic.com"])
            assert allowed, f"nightly.yml job {job_id} names {hosts}"
        return
    assert [h for h in PROVIDER_HOSTS if h in text] == [], f"{name} names a provider host"
    assert not PROVIDER_SECRETS.search(text), f"{name} reads a provider secret"


@pytest.mark.parametrize("job_id", ["legacy", "backend", "frontend", "e2e"])
def test_pr_test_jobs_run_inside_the_egress_lock(job_id: str) -> None:
    job = load("pr.yml")["jobs"][job_id]
    names = [str(step.get("run", "")) for step in job["steps"]]
    lock = next(i for i, run in enumerate(names) if "infra/ci/egress-lock.sh" in run)
    tests = [i for i, run in enumerate(names) if "make check" in run or "run_legacy_tests.py" in run]
    assert tests, f"{job_id} runs no test command"
    assert all(i > lock for i in tests), f"{job_id} runs tests before the egress lock"
    assert all("infra/ci/sandboxed.sh" in names[i] for i in tests), f"{job_id} runs tests outside the sandbox user"


def test_egress_probe_runs_in_pr() -> None:
    assert "infra/ci/egress_probe.py" in steps_text(load("pr.yml")["jobs"]["backend"])


def test_egress_lock_rejects_everything_but_private_networks() -> None:
    script = (REPO / "infra" / "ci" / "egress-lock.sh").read_text(encoding="utf-8")
    assert "--uid-owner" in script
    assert re.search(r"-m owner --uid-owner \"\$user_name\" -j REJECT", script)
    assert "DOCKER-USER" in script


def test_nightly_live_evals_are_off_until_d18_changes() -> None:
    evals = load("nightly.yml")["jobs"]["evals"]
    assert evals["if"] == "vars.LIVE_EVALS_ENABLED == 'true'"
