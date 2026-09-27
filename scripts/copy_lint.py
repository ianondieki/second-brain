"""Banned-claims copy-lint (REQ-PROV-02, AC-IP-4; docs/spec/04 principle 2, ADR-003 item 6).

Fails (exit 1) when user-facing copy makes a claim the product must never make ("theft-proof", "cannot be stolen",
"protected idea", "patented"), or when a message in the ``engagement.*``, ``tracker.*`` or ``email.em2.*`` i18n
namespaces (or an EM2 email template) says "approve"/"approved" without a non-binding qualifier in the same message.
Rules live in ``copy/banned_claims.txt``.

Scanned: every string in ``frontend/locales/*.json`` (reported by key), backend templates (any file under a
``templates`` directory of ``backend/src``), backend config and seed YAML (consent texts, legal placeholders),
backend Python source (email bodies are composed there), and frontend source under ``app/``, ``components/`` and
``lib/`` (test files excluded: they may hold negative fixtures). Stdlib only; run from anywhere:
``python scripts/copy_lint.py`` (CI: the pr.yml hygiene job; locally: ``make check-copy``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RULES_FILE = Path("copy") / "banned_claims.txt"

# Unicode hyphens and dashes (U+2010..U+2015, minus sign) and typographic apostrophes are normalised first.
_DASHES = re.compile("[‐-―−]")
_APOSTROPHES = re.compile("[‘’ʼ]")
_SPACE_OR_HYPHEN = r"[\s\-]+"


@dataclass(frozen=True, slots=True)
class Rules:
    banned: tuple[re.Pattern[str], ...]
    namespaces: tuple[str, ...]
    template_prefixes: tuple[str, ...]
    terms: re.Pattern[str]
    qualifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Violation:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def normalise(text: str) -> str:
    return _APOSTROPHES.sub("'", _DASHES.sub("-", text)).casefold()


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    """A whole-phrase, case-insensitive pattern where spaces and hyphens are interchangeable."""
    words = [re.escape(w) for w in re.split(_SPACE_OR_HYPHEN, normalise(phrase).strip()) if w]
    return re.compile(r"(?<![\w-])" + _SPACE_OR_HYPHEN.join(words) + r"(?![\w-])")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def load_rules(path: Path) -> Rules:
    section = ""
    banned: list[re.Pattern[str]] = []
    keys: dict[str, tuple[str, ...]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "banned":
            banned.append(phrase_pattern(line))
        elif section == "cooccurrence":
            key, sep, value = line.partition(":")
            if not sep:
                raise ValueError(f"{path}: expected 'key: value' in [cooccurrence], got {raw!r}")
            keys[key.strip()] = _csv(value)
        else:
            raise ValueError(f"{path}: line outside a known section: {raw!r}")
    missing = {"namespaces", "templates", "terms", "qualifiers"} - set(keys)
    if not banned or missing:
        raise ValueError(f"{path}: rules incomplete (banned phrases: {len(banned)}, missing keys: {sorted(missing)})")
    terms = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t.casefold()) for t in keys["terms"]) + r")(?![\w-])")
    return Rules(
        tuple(banned),
        keys["namespaces"],
        keys["templates"],
        terms,
        tuple(normalise(q) for q in keys["qualifiers"]),
    )


def banned_hits(rules: Rules, text: str) -> list[str]:
    norm = normalise(text)
    return [m.group(0) for p in rules.banned for m in p.finditer(norm)]


def lacks_qualifier(rules: Rules, text: str) -> bool:
    """True when ``text`` says approve/approved without any non-binding qualifier."""
    norm = normalise(text)
    return bool(rules.terms.search(norm)) and not any(q in norm for q in rules.qualifiers)


# ------------------------------------------------------------------------------------------------ scanners


def _flatten(node: object, prefix: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _flatten(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _flatten(value, f"{prefix}[{index}]")
    elif isinstance(node, str):
        yield prefix, node


def scan_locale(rules: Rules, path: Path, rel: str) -> list[Violation]:
    found: list[Violation] = []
    for key, message in _flatten(json.loads(path.read_text(encoding="utf-8"))):
        for hit in banned_hits(rules, message):
            found.append(Violation(f"{rel} [{key}]", f"banned claim {hit!r}"))
        if any(key.startswith(ns) for ns in rules.namespaces) and lacks_qualifier(rules, message):
            found.append(Violation(f"{rel} [{key}]", "says approve/approved without a non-binding qualifier"))
    return found


def scan_text(rules: Rules, path: Path, rel: str) -> list[Violation]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found: list[Violation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for hit in banned_hits(rules, line):
            found.append(Violation(f"{rel}:{number}", f"banned claim {hit!r}"))
    if path.name.casefold().startswith(rules.template_prefixes) and lacks_qualifier(rules, text):
        found.append(Violation(rel, "EM2 template says approve/approved without a non-binding qualifier"))
    return found


FRONTEND_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}
TEST_MARKERS = (".test.", ".spec.")


def targets(root: Path) -> Iterator[tuple[str, Path]]:
    """(kind, path) for every file the lint reads; kind is ``locale`` or ``text``."""
    for path in sorted((root / "frontend" / "locales").glob("*.json")):
        yield "locale", path
    src = root / "backend" / "src"
    if src.is_dir():
        for path in sorted(src.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and (
                "templates" in path.relative_to(src).parts or path.suffix == ".py"
            ):
                yield "text", path
    for folder in ("config", "seed"):
        for path in sorted((root / "backend" / folder).glob("*.y*ml")):
            yield "text", path
    for folder in ("app", "components", "lib"):
        base = root / "frontend" / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if (
                path.is_file()
                and path.suffix in FRONTEND_SUFFIXES
                and not any(marker in path.name for marker in TEST_MARKERS)
                and "node_modules" not in path.parts
            ):
                yield "text", path


def lint(root: Path, rules_path: Path | None = None) -> list[Violation]:
    rules = load_rules(rules_path or root / RULES_FILE)
    violations: list[Violation] = []
    for kind, path in targets(root):
        rel = path.relative_to(root).as_posix()
        scan = scan_locale if kind == "locale" else scan_text
        violations.extend(scan(rules, path, rel))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO, help="repository root (default: this checkout)")
    parser.add_argument("--rules", type=Path, default=None, help="rules file (default: <root>/copy/banned_claims.txt)")
    args = parser.parse_args(argv)
    violations = lint(args.root, args.rules)
    for violation in violations:
        print(f"FAIL {violation}")
    if violations:
        print(f"copy-lint: {len(violations)} violation(s); see copy/banned_claims.txt for approved phrasing")
        return 1
    print("copy-lint: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
