"""The committed reminder parity fixtures still match reminder/ (REQ-REM-00).

Run: python -m unittest discover -s scripts -t scripts   (legacy venv / the pr.yml legacy job, Python 3.13)

Regenerates every fixture in memory with scripts/gen_reminder_parity_fixtures.py and compares it with
backend/tests/fixtures/reminder_parity/. A change to reminder/remind.py or reminder/scan.py that alters an output
fails here; a change to the backend port that alters an output fails backend/tests/unit/reminders/test_parity.py.
To accept an intended companion change, rerun the generator and commit the fixtures with the backend port updated.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import gen_reminder_parity_fixtures as gen

KINDS = ("scenario", "record", "pending", "notices")


class ReminderParityFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fresh = gen.build()

    def test_committed_fixtures_match_what_reminder_produces(self) -> None:
        drifted = gen.drift(self.fresh)
        self.assertEqual(drifted, [], "fixtures differ from reminder/: rerun scripts/gen_reminder_parity_fixtures.py"
                                      " with the legacy venv and update the backend port if needed")

    def test_the_spread_covers_every_kind(self) -> None:
        self.assertGreaterEqual(len(self.fresh), 25)
        kinds = [json.loads(text)["kind"] for text in self.fresh.values()]
        for kind in KINDS:
            self.assertGreaterEqual(kinds.count(kind), 5, kind)

    def test_fixtures_are_stable_across_runs(self) -> None:
        self.assertEqual(gen.build(), self.fresh)

    def test_drift_reports_missing_extra_and_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.json").write_text("{}\n", encoding="utf-8")
            (directory / "b.json").write_text("{\"x\": 1}\r\n", encoding="utf-8", newline="")  # CRLF checkout
            (directory / "stale.json").write_text("{}\n", encoding="utf-8")
            fresh = {"a.json": "{}\n", "b.json": "{\"x\": 2}\n", "new.json": "{}\n"}
            self.assertEqual(gen.drift(fresh, directory), ["b.json", "new.json", "stale.json"])
            (directory / "b.json").write_text("{\"x\": 2}\r\n", encoding="utf-8", newline="")
            (directory / "stale.json").unlink()
            (directory / "new.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(gen.drift(fresh, directory), [])

    def test_the_legacy_run_guard_is_what_the_pending_fixtures_record(self) -> None:
        # The pending fixtures come from reminder.remind.run itself; spot-check both sides of the hour guard.
        self.assertEqual(gen.legacy_pending({}, ["email", "whatsapp"], datetime(2026, 9, 21, 7, 59), 8,
                                            False, False), [])
        self.assertEqual(gen.legacy_pending({}, ["email", "whatsapp"], datetime(2026, 9, 21, 8, 0), 8,
                                            False, False), ["email", "whatsapp"])


if __name__ == "__main__":
    unittest.main()
