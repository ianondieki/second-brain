"""D-43 (a), REQ-SCOUT-02 ("the scout reads Tier 1 and metadata only"): the prototype's scout runs as bridge_app, which
may switch to the Tier-2 roles, so the code itself must never do it. This import lint reads every module of the scout
(``bridge.matching`` and its job module) and fails when one imports ``as_role`` or the Tier-2 roles, any Tier-2 or
decrypting module, a Tier-2 model, or names a Tier-2 role or table in a string (SQL included). Phase 4 restores a
separate database role for the scout; this test keeps the code honest until then."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

import bridge

SRC = Path(bridge.__file__).resolve().parent
SCOUT_FILES = sorted([*(SRC / "matching").rglob("*.py"), SRC / "jobs" / "scouts.py"])
# Modules that read, decrypt or render Tier 2 (or switch roles for it).
FORBIDDEN_MODULES = (
    "bridge.proposals.tier2",
    "bridge.proposals.access",
    "bridge.proposals.render",
    "bridge.proposals.views",
    "bridge.proposals.service",  # the owner's own Tier-2 reads
    "bridge.proposals.editor",
    "bridge.proposals.grants",
    "bridge.crypto",
    "bridge.storage",
)
FORBIDDEN_NAMES = frozenset(
    {"as_role", "TIER2_ROLES", "ProposalConfidential", "ProposalConfidentialEmbedding", "ProposalAttachment", "TIER2"}
)
# Tier-2 roles and tables, and the role switch, in any string of the scout's code.
FORBIDDEN_TEXT = (
    "tier2_reader",
    "tier2_moderation",
    "tier2_embed_worker",
    "provenance_worker",
    "dsr_exporter",
    "proposal_confidential",
    "proposal_attachments",
    "set role",
    "set_config('role'",
    "tier2",
)


def _imports(tree: ast.AST) -> Iterator[tuple[str, str | None]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                yield node.module, alias.name


def problems(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for module, name in _imports(tree):
        if any(module == bad or module.startswith(bad + ".") for bad in FORBIDDEN_MODULES) or "tier2" in module:
            found.append(f"imports {module}")
        if name is not None and (name in FORBIDDEN_NAMES or "tier2" in name.lower()):
            found.append(f"imports {name} from {module}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(f"uses .{node.attr}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(f"uses {node.id}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.lower()
            found += [f"names {bad!r} in a string" for bad in FORBIDDEN_TEXT if bad in text]
    return found


def test_the_scout_modules_are_all_checked() -> None:
    names = {p.relative_to(SRC).as_posix() for p in SCOUT_FILES}
    assert {"matching/scan.py", "matching/pipeline.py", "matching/rationale.py", "jobs/scouts.py"} <= names


@pytest.mark.parametrize("path", SCOUT_FILES, ids=lambda p: p.relative_to(SRC).as_posix())
def test_the_scout_never_reaches_for_tier2(path: Path) -> None:
    assert problems(path) == []


@pytest.mark.parametrize(
    "source",
    [
        "from bridge.db import as_role",
        "import bridge.proposals.tier2",
        "from bridge.proposals import tier2",
        "from bridge.proposals.models import ProposalConfidential",
        "from bridge.crypto.envelope import open_sealed",
        "from bridge.llm.types import Tier\nx = Tier.TIER2",
        "SQL = 'SELECT ciphertext FROM proposal_confidential'",
        "SQL = \"SELECT set_config('role', 'tier2_reader', true)\"",
        "SQL = 'SET ROLE provenance_worker'",
    ],
)
def test_the_lint_catches_each_way_in(source: str, tmp_path: Path) -> None:
    """The lint's own mutation proofs: each line alone is reported."""
    module = tmp_path / "bad.py"
    module.write_text(source + "\n", encoding="utf-8")
    assert problems(module) != []
