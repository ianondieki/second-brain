"""Banned-claims copy-lint (REQ-PROV-02, AC-IP-4; docs/spec/04 principle 2, ADR-003 item 6).

Fails (exit 1) when user-facing copy makes a claim the product must never make ("theft-proof", "cannot be stolen",
"protected idea", "patented"), or when a message in the ``engagement.*``, ``tracker.*`` or ``email.em2.*`` i18n
namespaces (or an EM2 template) says "approve"/"approved" without a non-binding qualifier. Rules live in
``copy/banned_claims.txt``.

Scope, under ``backend/`` and ``frontend/`` (dependency caches anywhere, top-level test and build directories, and
``*.test.*``/``*.spec.*`` files are excluded, since tests hold negative fixtures):

- i18n catalogues: every ``*.json`` (message by message, ICU ``select``/``plural`` branches separately) and ``*.po``
  under a ``locales/``, ``locale/``, ``messages/`` or ``i18n/`` directory; at least one must exist (fail closed);
- every file under a ``templates/``, ``emails/`` or ``email_templates/`` directory (any suffix);
- backend ``config/`` and ``seed/`` YAML, recursively (consent texts, legal placeholders, seed copy);
- string literals in backend Python under ``src/`` and ``alembic/`` (``ast``: adjacent literals are already joined; comments and docstrings are
  not copy and are skipped);
- frontend source and static copy under ``app/``, ``components/``, ``lib/`` and ``public/``.

Text is matched as a whole (a phrase may wrap onto the next line, never across a blank line or a block element)
after HTML-entity decoding, NFKC, removal of invisible format characters and combining marks, blank fillers and
Cyrillic/Greek lookalikes folded to Latin, and Unicode dashes folded; markup is matched both as written (attribute
copy) and with tags removed. Deliberate evasions beyond these (other homoglyph scripts, images of text) are a known
limit: the lint catches mistakes, human review catches intent. Stdlib only; run from anywhere:
``python scripts/copy_lint.py`` (CI: the pr.yml hygiene job; locally: ``make check-copy``).
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RULES_FILE = Path("copy") / "banned_claims.txt"

_DASHES = re.compile("[֊־᐀᠆‐-―−⸺⸻⹀〜゠﹘]")
_APOSTROPHES = re.compile("[‘’ʼ＇]")
# A tag starts with a letter after "<" or "</" (so "a < b" comparisons and "=>" arrows are not tags). Block tags
# become a paragraph break, so words in neighbouring elements never join into one phrase; inline tags vanish.
_TAG = re.compile(r"</?([A-Za-z][\w:-]*)\b[^<>]*>")
_BLOCK_TAGS = {
    "p", "div", "br", "hr", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "title", "mj-text", "mj-section", "mj-column",
}
_TEMPLATE_COMMENT = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)
# Spaces, tabs and hyphens, possibly absent, and at most one line break (a wrapped line), never a blank line.
_SEP = r"[ \t\-]*(?:\n[ \t\-]*)?"
# Blank fillers used as separators, and Cyrillic/Greek letters that look like Latin ones (deliberate evasions).
_FILLERS = re.compile("[ᅟᅠ⠀ㅤﾠ]")
_LINE_BREAKS = re.compile(r"\r\n?|[\x0b\x0c\x85\u2028\u2029]")
_CONFUSABLES = str.maketrans("аеорсхуіѕјԁкмтнвгΑΒΕΗΙΚΜΝΟΡΤΧΥοαερτ", "aeopcxyisjdkmthbrABEHIKMNOPTXYoaept")
MARKUP_SUFFIXES = {".html", ".htm", ".j2", ".jinja", ".mjml", ".tsx", ".jsx", ".md", ".mdx", ".svg", ".xml"}
FRONTEND_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".md", ".mdx", ".html", ".htm", ".json", ".txt", ".svg"}
# Skipped at any depth: dependency and tool caches. Skipped only directly under backend/ or frontend/: test and
# build output directories (a route segment such as app/(dev)/build/ is still copy).
SKIP_ANYWHERE = {
    "node_modules", ".venv", "venv", ".git", ".next", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    ".hypothesis", "__tests__",
}
SKIP_TOP = {"tests", "test", "e2e", "dist", "build", "coverage", "playwright-report", "test-results"}
CATALOGUE_DIRS = {"locales", "locale", "messages", "i18n"}
TEMPLATE_DIRS = {"templates", "emails", "email_templates"}
TEST_MARKERS = (".test.", ".spec.")
ICU_COMPLEX = {"select", "plural", "selectordinal"}
MAX_VARIANTS = 256


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


def _strip_tag(match: re.Match[str]) -> str:
    newlines = match.group(0).count("\n")
    if match.group(1).casefold() in _BLOCK_TAGS:
        return "\x1e" + "\n" * newlines  # a record separator: no phrase separator crosses it
    return "\n" * newlines


def normalise(text: str, *, markup: bool = False) -> str:
    """Decode entities; NFKC; drop invisible format characters and combining marks; blank fillers become spaces;
    Latin lookalikes become Latin; tags are removed for markup; dashes and case are folded.

    Newlines inside a removed tag are kept, so line numbers of later matches stay right."""
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", html.unescape(text)))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in {"Cf", "Mn"})
    text = _LINE_BREAKS.sub("\n", unicodedata.normalize("NFKC", text))
    text = _FILLERS.sub(" ", text).casefold().translate(_CONFUSABLES)
    if markup:
        text = _TAG.sub(_strip_tag, text)
    return _APOSTROPHES.sub("'", _DASHES.sub("-", text)).casefold()


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Whole phrase, spaces/hyphens interchangeable or absent; a trailing ``*`` allows any word ending."""
    stem = phrase.endswith("*")
    words = [re.escape(w) for w in re.split(r"[\s\-]+", normalise(phrase.rstrip("*")).strip()) if w]
    return re.compile(r"(?<!\w)" + _SEP.join(words) + (r"\w*" if stem else r"(?!\w)"))


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
    terms = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t.casefold()) for t in keys["terms"]) + r")(?!\w)")
    return Rules(
        tuple(banned),
        keys["namespaces"],
        tuple(p.casefold() for p in keys["templates"]),
        terms,
        tuple(normalise(q) for q in keys["qualifiers"]),
    )


def banned_hits(rules: Rules, norm: str) -> list[tuple[int, str]]:
    """(offset, matched text) for every banned phrase in already-normalised text."""
    return sorted((m.start(), m.group(0)) for p in rules.banned for m in p.finditer(norm))


def lacks_qualifier(rules: Rules, norm: str) -> bool:
    """True when normalised text says approve/approved without any non-binding qualifier."""
    return bool(rules.terms.search(norm)) and not any(q in norm for q in rules.qualifiers)


def in_namespace(key: str, namespaces: tuple[str, ...]) -> bool:
    for ns in namespaces:
        root = ns.rstrip(".")
        if key == root or key.startswith(root + ".") or key.startswith(root + "["):
            return True
    return False


# ------------------------------------------------------------------------------------------------ ICU messages


def _closing_brace(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _branches(body: str) -> list[str]:
    """Contents of the ``key {content}`` pairs of a select/plural argument (keys are selectors, not copy)."""
    found: list[str] = []
    index = 0
    while (start := body.find("{", index)) >= 0:
        end = _closing_brace(body, start)
        if end < 0:
            break
        found.append(body[start + 1 : end])
        index = end + 1
    return found


def icu_variants(message: str) -> list[str]:
    """Every text a message can render: one variant per combination of select/plural branches (capped)."""
    variants = [""]
    index = 0
    while index < len(message):
        start = message.find("{", index)
        if start < 0:
            return [v + message[index:] for v in variants]
        variants = [v + message[index:start] for v in variants]
        end = _closing_brace(message, start)
        if end < 0:
            return [v + message[start:] for v in variants]
        parts = message[start + 1 : end].split(",", 2)
        branches = _branches(parts[2]) if len(parts) == 3 and parts[1].strip() in ICU_COMPLEX else []
        if branches:
            expanded = [sub for branch in branches for sub in icu_variants(branch)]
            variants = [v + e for v in variants for e in expanded][:MAX_VARIANTS]
        else:
            variants = [v + " " for v in variants]  # a placeholder
        index = end + 1
    return variants


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


def _hits(rules: Rules, text: str, *, markup: bool) -> list[tuple[int, str]]:
    """(line index, hit) of banned phrases, from the text as written and, for markup, with tags removed, so copy in
    attributes (alt, title, aria-label, meta content) and copy split by inline tags are both seen. One hit per line."""
    seen: dict[int, str] = {}
    for norm in [normalise(text)] + ([normalise(text, markup=True)] if markup else []):
        for offset, hit in banned_hits(rules, norm):
            seen.setdefault(norm.count("\n", 0, offset), hit)
    return sorted(seen.items())


def scan_catalogue(rules: Rules, path: Path, rel: str) -> list[Violation]:
    found: list[Violation] = []
    for key, message in _flatten(json.loads(path.read_text(encoding="utf-8"))):
        for _, hit in _hits(rules, message, markup=True):
            found.append(Violation(f"{rel} [{key}]", f"banned claim {hit!r}"))
        if in_namespace(key, rules.namespaces) and any(
            lacks_qualifier(rules, normalise(variant, markup=True)) for variant in icu_variants(message)
        ):
            found.append(Violation(f"{rel} [{key}]", "says approve/approved without a non-binding qualifier"))
    return found


def _line_hits(rules: Rules, text: str, rel: str, *, markup: bool, first_line: int = 1) -> list[Violation]:
    return [
        Violation(f"{rel}:{first_line + line}", f"banned claim {hit!r}")
        for line, hit in _hits(rules, text, markup=markup)
    ]


def scan_text(rules: Rules, path: Path, rel: str, *, template: bool = False) -> list[Violation]:
    text = path.read_text(encoding="utf-8", errors="replace")
    markup = path.suffix.casefold() in MARKUP_SUFFIXES
    found = _line_hits(rules, text, rel, markup=markup)
    if template and path.name.casefold().startswith(rules.template_prefixes):
        body = normalise(_TEMPLATE_COMMENT.sub("", text), markup=markup)
        if lacks_qualifier(rules, body):
            found.append(Violation(rel, "EM2 template says approve/approved without a non-binding qualifier"))
    return found


def _docstrings(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    ids.add(id(first.value))
    return ids


def scan_python(rules: Rules, path: Path, rel: str) -> list[Violation]:
    """String literals only (f-string text parts joined); comments and docstrings are not copy."""
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _line_hits(rules, source, rel, markup=True)
    skip = _docstrings(tree)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.JoinedStr):
            parts = [v for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            skip.update(id(v) for v in parts)
            text = "".join(str(v.value) for v in parts)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        found.extend(_line_hits(rules, text, rel, markup=True, first_line=node.lineno))
    return found


def _walk(base: Path) -> Iterator[Path]:
    for folder, dirs, files in os.walk(base):
        top = Path(folder) == base
        dirs[:] = sorted(d for d in dirs if d not in SKIP_ANYWHERE and not (top and d in SKIP_TOP))
        for name in sorted(files):
            if not any(marker in name for marker in TEST_MARKERS):
                yield Path(folder) / name


def targets(root: Path) -> Iterator[tuple[str, Path]]:
    """(kind, path) for every file the lint reads; kind is catalogue, po, template, python or text."""
    for side in ("backend", "frontend"):
        base = root / side
        if not base.is_dir():
            continue
        for path in _walk(base):
            parts = path.relative_to(base).parts
            folders = set(parts[:-1])
            suffix = path.suffix.casefold()
            if side == "backend" and parts[0] in {"src", "alembic"} and suffix == ".py":
                yield "python", path
            elif folders & CATALOGUE_DIRS and suffix == ".json":
                yield "catalogue", path
            elif folders & CATALOGUE_DIRS and suffix == ".po":
                yield "po", path
            elif folders & TEMPLATE_DIRS:
                yield "template", path
            elif side == "backend" and parts[0] in {"config", "seed"} and suffix in {".yaml", ".yml"}:
                yield "text", path
            elif side == "frontend" and parts[0] in {"app", "components", "lib", "public"}:
                if suffix in FRONTEND_SUFFIXES or path.name.endswith(".webmanifest"):
                    yield "text", path


def lint(root: Path, rules_path: Path | None = None) -> list[Violation]:
    rules = load_rules(rules_path or root / RULES_FILE)
    violations: list[Violation] = []
    catalogues = 0
    for kind, path in targets(root):
        rel = path.relative_to(root).as_posix()
        if kind == "catalogue":
            catalogues += 1
            violations.extend(scan_catalogue(rules, path, rel))
        elif kind == "po":
            catalogues += 1
            violations.extend(scan_text(rules, path, rel))
        elif kind == "python":
            violations.extend(scan_python(rules, path, rel))
        else:
            violations.extend(scan_text(rules, path, rel, template=kind == "template"))
    if catalogues == 0:
        violations.append(Violation(root.as_posix(), "no i18n catalogue found (locales/*.json): refusing to pass"))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
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
