"""Tests for scripts/copy_lint.py (AC-IP-4): inserting a banned claim into any template, i18n string or email body
fails the lint; the Approve/approved co-occurrence rule holds for EM2 and the stage-3 label (positive fixtures) and
exempts moderation holds. Stdlib unittest, discovered by pr.yml ("Runner self-tests")."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import copy_lint

REPO = Path(__file__).resolve().parents[1]

# Positive fixtures (docs/spec/06 6.9 stage 3 label, 6.10 EM2 subject) and the exempt fixture (a moderation hold).
EM2_SUBJECT = 'Good news: {company_name} approved "{title}" to proceed (non-binding)'
STAGE3_LABEL = "Approved to proceed (non-binding)"
EM2_BODY = (
    "{company_name} has approved your proposal and will contact you shortly to agree on pursuing the project. "
    "This approval is an expression of interest, not a contract or a commitment to buy."
)
MODERATION_HOLD = "Your teaser will be published once a moderator has approved it."


class LintTree(unittest.TestCase):
    """A scratch repository root holding the real rules file plus the files a test adds."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "copy").mkdir()
        shutil.copy(REPO / "copy" / "banned_claims.txt", self.root / "copy" / "banned_claims.txt")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def locale(self, messages: dict[str, object]) -> None:
        self.write("frontend/locales/en.json", json.dumps(messages, ensure_ascii=False))

    def violations(self) -> list[str]:
        return [str(v) for v in copy_lint.lint(self.root)]


class RepositoryIsClean(unittest.TestCase):
    def test_the_checked_in_copy_passes(self) -> None:
        self.assertEqual([str(v) for v in copy_lint.lint(REPO)], [])

    def test_main_exits_zero_on_the_repository(self) -> None:
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(copy_lint.main(["--root", str(REPO)]), 0)
        self.assertIn("PASS", out.getvalue())


class BannedClaims(LintTree):
    def test_theft_proof_in_a_real_i18n_string_fails(self) -> None:
        messages = json.loads((REPO / "frontend" / "locales" / "en.json").read_text(encoding="utf-8"))
        messages["landing"] = {**messages.get("landing", {}), "tagline": "Your ideas, theft-proof."}
        self.locale(messages)
        found = self.violations()
        self.assertEqual(len(found), 1, found)
        self.assertIn("[landing.tagline]", found[0])

    def test_theft_proof_in_an_email_template_fails(self) -> None:
        self.write("backend/src/bridge/notifications/templates/em1.html.j2", "<p>Your idea is now theft-proof.</p>\n")
        self.assertEqual(len(self.violations()), 1)

    def test_theft_proof_in_an_email_body_composed_in_python_fails(self) -> None:
        source = (REPO / "backend" / "src" / "bridge" / "auth" / "emails.py").read_text(encoding="utf-8")
        self.write("backend/src/bridge/auth/emails.py", source + '\nEXTRA = "Registered and theft proof."\n')
        found = self.violations()
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("backend/src/bridge/auth/emails.py:"))

    def test_theft_proof_in_frontend_source_fails(self) -> None:
        self.write("frontend/components/Hero.tsx", "export const Hero = () => <p>Theft-Proof ideas</p>;\n")
        self.assertEqual(len(self.violations()), 1)

    def test_theft_proof_in_consent_or_seed_yaml_fails(self) -> None:
        self.write("backend/config/consents.yaml", "marketing: {text: 'Keep your ideas theft-proof'}\n")
        self.assertEqual(len(self.violations()), 1)

    def test_every_banned_phrase_and_variant_is_caught(self) -> None:
        texts = [
            "THEFT PROOF",
            "theft‑proof",  # non-breaking hyphen
            "It cannot be stolen",
            "it can’t be stolen",
            "a Protected Idea",
            "protected ideas",
            "a patented method",
        ]
        self.locale({"landing": {f"t{i}": text for i, text in enumerate(texts)}})
        self.assertEqual(len(self.violations()), len(texts))

    def test_neighbouring_words_are_not_banned(self) -> None:
        self.locale(
            {
                "cert": {
                    "footer": "It is not a patent, copyright registration or guarantee against misuse.",
                    "other": "unpatented, patents, theft-proofing-free",
                }
            }
        )
        self.assertEqual(self.violations(), [])

    def test_test_files_may_hold_negative_fixtures(self) -> None:
        self.write("frontend/components/Hero.test.tsx", "expect(copy).not.toContain('theft-proof');\n")
        self.write("frontend/e2e/copy.spec.ts", "expect(copy).not.toContain('theft-proof');\n")
        self.assertEqual(self.violations(), [])

    def test_main_exits_one_and_names_the_file(self) -> None:
        self.write("frontend/app/page.tsx", "const t = 'patented';\n")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(copy_lint.main(["--root", str(self.root)]), 1)
        self.assertIn("frontend/app/page.tsx:1", out.getvalue())


class ApproveNeedsANonBindingQualifier(LintTree):
    def test_em2_subject_and_stage3_label_are_positive_fixtures(self) -> None:
        self.locale(
            {
                "email": {"em2": {"subject": EM2_SUBJECT, "body": EM2_BODY}},
                "tracker": {"stage": {"interestConfirmed": STAGE3_LABEL}},
            }
        )
        self.assertEqual(self.violations(), [])

    def test_moderation_hold_is_the_exempt_fixture(self) -> None:
        self.locale({"moderation": {"held": MODERATION_HOLD}, "email": {"em8": {"subject": "Verification approved"}}})
        self.assertEqual(self.violations(), [])

    def test_approved_without_a_qualifier_fails_in_each_scoped_namespace(self) -> None:
        self.locale(
            {
                "engagement": {"banner": "Safaricom approved your proposal"},
                "tracker": {"stage": {"interestConfirmed": "Approved to proceed"}},
                "email": {"em2": {"subject": "Good news: your proposal was approved"}},
            }
        )
        found = self.violations()
        self.assertEqual(len(found), 3, found)
        self.assertTrue(all("non-binding qualifier" in v for v in found))

    def test_em2_template_needs_the_qualifier(self) -> None:
        self.write("backend/src/bridge/notifications/templates/em2.txt.j2", "{{ company_name }} approved it.\n")
        self.assertEqual(len(self.violations()), 1)
        self.write(
            "backend/src/bridge/notifications/templates/em2.txt.j2",
            "{{ company_name }} approved it. This is not a contract or a commitment to buy.\n",
        )
        self.assertEqual(self.violations(), [])


class RulesFile(unittest.TestCase):
    def test_a_line_outside_a_section_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.txt"
            path.write_text("theft-proof\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                copy_lint.load_rules(path)

    def test_missing_cooccurrence_keys_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.txt"
            path.write_text("[banned]\ntheft-proof\n[cooccurrence]\nterms: approve\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                copy_lint.load_rules(path)


if __name__ == "__main__":
    unittest.main()
