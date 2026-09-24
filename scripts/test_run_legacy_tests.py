"""Tests for scripts/run_legacy_tests.py (REQ-FND-01). Run: python -m unittest discover -s scripts -t scripts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import run_legacy_tests as runner


def _dummy_tests(*names: str) -> list[unittest.TestCase]:
    """Build throwaway test cases without defining a module-level TestCase that discovery would run."""

    class Dummy(unittest.TestCase):
        def test_a(self) -> None:
            pass

        def test_b(self) -> None:
            pass

    return [Dummy(name) for name in names]


class SkipListTests(unittest.TestCase):
    def test_comments_and_blank_lines_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "skip.txt"
            path.write_text("# header\n\n  tests.a.B.test_c  \n# note\ntests.d.E.test_f\n", encoding="utf-8")
            self.assertEqual(runner.read_skip_list(path), ["tests.a.B.test_c", "tests.d.E.test_f"])

    def test_listed_ids_are_dropped_and_the_rest_kept_in_order(self) -> None:
        tests = _dummy_tests("test_a", "test_b")
        kept, stale = runner.select(tests, {tests[0].id()})
        self.assertEqual([t.id() for t in runner.iter_tests(kept)], [tests[1].id()])
        self.assertEqual(stale, [])

    def test_an_id_missing_from_the_suite_is_reported_as_stale(self) -> None:
        tests = _dummy_tests("test_a")
        _, stale = runner.select(tests, {"tests.gone.Old.test_x"})
        self.assertEqual(stale, ["tests.gone.Old.test_x"])

    def test_the_committed_skip_list_names_only_existing_legacy_tests(self) -> None:
        loader = unittest.defaultTestLoader
        suite = loader.discover(str(runner.ROOT / "tests"), top_level_dir=str(runner.ROOT))
        present = {t.id() for t in runner.iter_tests(suite)}
        missing = set(runner.read_skip_list(runner.SKIP_FILE)) - present
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
