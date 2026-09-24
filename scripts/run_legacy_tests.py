"""Run the legacy local-companion test suite (tests/) on any OS.

Discovery is the same as ``python -m unittest discover -s tests -t .``
(``unittest.defaultTestLoader.discover("tests", top_level_dir=".")``). When
``sys.platform != "win32"`` the test ids listed in
``docs/platform/tests_skip_linux.txt`` are dropped (they rely on Windows
paths or ``cmd /c mklink``); on Windows the full suite runs. ``tests/`` itself
is never edited (docs/spec/02-existing-repo.md).

Exit code: 0 when every selected test passes; 1 on any failure or error;
2 when the skip list names an id the suite no longer contains (a stale list
must be fixed, not ignored).

CI notes (docs/platform/DECISIONS-NEEDED.md D-12, D-13):
- ``--no-skip`` runs the full suite on Linux too; the non-blocking
  ``legacy-linux-full`` job uses it to keep the skip list honest.
- ``adviser.__main__.check()`` needs a cloudflared binary. The tests pass
  it an explicit env dict, so ``ADVISER_CLOUDFLARED`` in the process
  environment is not read; the workflow instead puts an empty stub named
  ``cloudflared`` on PATH (found by ``shutil.which``) and installs
  ``requirements.txt`` so the four imports the check makes succeed.

Requirement: REQ-FND-01 (AC-REM-4/a).
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_FILE = ROOT / "docs" / "platform" / "tests_skip_linux.txt"


def read_skip_list(path: Path) -> list[str]:
    """Return the test ids in ``path``: one per line, ``#`` comments and blank lines ignored."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            ids.append(entry)
    return ids


def iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    """Flatten nested suites in discovery order (class and module fixtures still run once)."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def select(tests: list[unittest.TestCase], skip: set[str]) -> tuple[unittest.TestSuite, list[str]]:
    """Drop the ids in ``skip``; return the kept suite and any skip ids the suite does not contain."""
    present = {test.id() for test in tests}
    stale = sorted(skip - present)
    kept = unittest.TestSuite(test for test in tests if test.id() not in skip)
    return kept, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the legacy tests/ suite (skip list applied off Windows).")
    parser.add_argument("--no-skip", action="store_true", help="run the full suite even off Windows")
    parser.add_argument("-v", "--verbose", action="store_const", const=2, default=1, dest="verbosity")
    args = parser.parse_args(argv)

    root = str(ROOT)
    os.chdir(root)  # same working directory as `python -m unittest discover -s tests -t .` from the repo root
    if root not in sys.path:
        sys.path.insert(0, root)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=root)
    tests = list(iter_tests(suite))

    apply_skip = sys.platform != "win32" and not args.no_skip
    skip = set(read_skip_list(SKIP_FILE)) if apply_skip else set()
    kept, stale = select(tests, skip)
    if stale:
        print(f"{SKIP_FILE.relative_to(ROOT)} lists ids the suite does not contain:", file=sys.stderr)
        for test_id in stale:
            print(f"  {test_id}", file=sys.stderr)
        return 2
    if skip:
        print(f"Skipping {len(skip)} Windows-only test(s) listed in {SKIP_FILE.relative_to(ROOT)}:", file=sys.stderr)
        for test_id in sorted(skip):
            print(f"  {test_id}", file=sys.stderr)

    result = unittest.TextTestRunner(verbosity=args.verbosity).run(kept)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
