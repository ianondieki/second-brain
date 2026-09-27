"""Tests for scripts/copy_lint.py (AC-IP-4): inserting a banned claim into any template, i18n string or email body
fails the lint and therefore CI; the Approve/approved co-occurrence rule holds for EM2 and the stage-3 label
(positive fixtures) and exempts moderation holds. Stdlib unittest, discovered by pr.yml ("Runner self-tests")."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import copy_lint

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "copy" / "banned_claims.txt"

# Positive fixtures (docs/spec/06 6.9 stage 3 label, 6.10 EM2 subject) and the exempt fixture (a moderation hold).
EM2_SUBJECT = 'Good news: {company_name} approved "{title}" to proceed (non-binding)'
STAGE3_LABEL = "Approved to proceed (non-binding)"
EM2_BODY = (
    "{company_name} has approved your proposal and will contact you shortly to agree on pursuing the project. "
    "This approval is an expression of interest, not a contract or a commitment to buy."
)
MODERATION_HOLD = "Your teaser will be published once a moderator has approved it."


def rule_lines(section: str) -> list[str]:
    lines, current = [], ""
    for raw in RULES.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line.strip("[]")
        elif current == section:
            lines.append(line)
    return lines


def terms() -> list[str]:
    line = next(entry for entry in rule_lines("cooccurrence") if entry.startswith("terms:"))
    return [t.strip() for t in line.partition(":")[2].split(",") if t.strip()]


class LintTree(unittest.TestCase):
    """A scratch repository root with the real rules file and an empty English catalogue."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "copy").mkdir()
        shutil.copy(RULES, self.root / "copy" / "banned_claims.txt")
        self.locale({})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def locale(self, messages: dict[str, object], name: str = "en.json") -> None:
        self.write(f"frontend/locales/{name}", json.dumps(messages, ensure_ascii=False))

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

    def test_the_swahili_catalogue_is_scanned(self) -> None:
        self.locale({"landing": {"tagline": "Mawazo yako ni theft-proof"}}, name="sw.json")
        self.assertEqual(len(self.violations()), 1)

    def test_a_backend_email_catalogue_is_scanned(self) -> None:
        self.write(
            "backend/src/bridge/notifications/locales/en.json",
            json.dumps({"email": {"em1": {"subject": "Your idea is theft-proof"}}}),
        )
        self.assertEqual(len(self.violations()), 1)

    def test_theft_proof_in_any_templates_directory_fails(self) -> None:
        self.write("backend/src/bridge/notifications/templates/em1.html.j2", "<p>Your idea is now theft-proof.</p>\n")
        self.write("backend/templates/page.txt", "theft-proof\n")
        self.assertEqual(len(self.violations()), 2)

    def test_a_phrase_wrapped_across_lines_fails_and_names_its_first_line(self) -> None:
        self.write(
            "backend/src/bridge/notifications/templates/em1.html.j2",
            "<p>Hello</p>\n<p>Your idea is registered and cannot be\n   stolen by anyone.</p>\n",
        )
        self.assertEqual(self.violations(), ["backend/src/bridge/notifications/templates/em1.html.j2:2: "
                                             "banned claim 'cannot be\\n   stolen'"])

    def test_an_email_body_composed_in_python_fails_even_when_wrapped(self) -> None:
        source = (REPO / "backend" / "src" / "bridge" / "auth" / "emails.py").read_text(encoding="utf-8")
        extra = '\nEXTRA = (\n    "Your idea is registered and cannot be "\n    "stolen by anyone."\n)\n'
        self.write("backend/src/bridge/auth/emails.py", source + extra)
        found = self.violations()
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("backend/src/bridge/auth/emails.py:"))

    def test_python_comments_and_docstrings_are_not_copy(self) -> None:
        self.write(
            "backend/src/bridge/provenance/certificate.py",
            '"""The footer never says theft-proof."""\n# Principle 2: never "patented".\nFOOTER = "Evidence only."\n',
        )
        self.assertEqual(self.violations(), [])

    def test_f_string_text_is_scanned(self) -> None:
        self.write("backend/src/bridge/x.py", 'name = "a"\nTEXT = f"{name} is patented"\n')
        self.assertEqual(len(self.violations()), 1)

    def test_frontend_source_and_static_copy_fail(self) -> None:
        self.write("frontend/components/Hero.tsx", "export const Hero = () => <p>Theft-Proof ideas</p>;\n")
        self.write("frontend/public/offline.html", "<p>protected ideas</p>")
        self.write("frontend/app/about/page.mdx", "Our method is patented.")
        self.assertEqual(len(self.violations()), 3)

    def test_nested_config_and_seed_yaml_fail(self) -> None:
        self.write("backend/config/consents.yaml", "marketing: {text: 'Keep your ideas theft-proof'}\n")
        self.write("backend/seed/niches/extra.yaml", "- {name: 'Patented things'}\n")
        self.assertEqual(len(self.violations()), 2)

    def test_every_banned_rule_is_enforced(self) -> None:
        for line in rule_lines("banned"):
            with self.subTest(rule=line):
                self.locale({"landing": {"t": f"Ideas here: {line.rstrip('*')}."}})
                self.assertEqual(len(self.violations()), 1)

    def test_evasions_are_caught(self) -> None:
        texts = [
            "THEFT PROOF",
            "theftproof",
            "theft-proofing for every idea",
            "theft-proofs",
            "theft‑proof",  # non-breaking hyphen
            "theft－proof",  # fullwidth hyphen
            "theft­proof",  # soft hyphen
            "the​ft-proof",  # zero-width space
            "theft&#8209;proof",
            "theft&#x2011;proof",
            "theft&hyphen;proof",
            "cannot&nbsp;be&nbsp;stolen",
            "<strong>cannot</strong> be stolen",
            "it can’t be stolen",
            "it can not be stolen",
            "It cannot be stolen",
            "a Protected Idea",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.locale({"landing": {"t": text}})
                self.assertEqual(len(self.violations()), 1)

    def test_neighbouring_words_are_not_banned(self) -> None:
        self.locale(
            {
                "cert": {
                    "footer": "It is not a patent, copyright registration or guarantee against misuse.",
                    "other": "unpatented designs; patents pending elsewhere; theft reports",
                }
            }
        )
        self.assertEqual(self.violations(), [])

    def test_test_files_and_test_directories_may_hold_negative_fixtures(self) -> None:
        self.write("frontend/components/Hero.test.tsx", "expect(copy).not.toContain('theft-proof');\n")
        self.write("frontend/e2e/copy.spec.ts", "expect(copy).not.toContain('theft-proof');\n")
        self.write("frontend/lib/__tests__/copy.ts", "export const bad = 'theft-proof';\n")
        self.write("backend/tests/unit/test_x.py", "BAD = 'theft-proof'\n")
        self.assertEqual(self.violations(), [])

    def test_no_catalogue_fails_closed(self) -> None:
        (self.root / "frontend" / "locales" / "en.json").unlink()
        self.assertIn("no i18n catalogue", " ".join(self.violations()))

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

    def test_every_term_needs_the_qualifier(self) -> None:
        for term in terms():
            with self.subTest(term=term):
                self.locale({"tracker": {"action": term.capitalize()}})
                self.assertEqual(len(self.violations()), 1)
                self.locale({"tracker": {"action": f"{term.capitalize()} to proceed (non-binding)"}})
                self.assertEqual(self.violations(), [])

    def test_approved_without_a_qualifier_fails_in_each_scoped_form(self) -> None:
        self.locale(
            {
                "engagement": {"banner": "Safaricom approved your proposal"},
                "engagements": {"banner": "Safaricom pre-approved your proposal"},
                "tracker": ["Approved to proceed"],
                "email": {"em2": "Good news: your proposal was approved"},
            }
        )
        found = self.violations()
        self.assertEqual(len(found), 4, found)
        self.assertTrue(all("non-binding qualifier" in v for v in found))

    def test_each_icu_branch_needs_its_own_qualifier(self) -> None:
        self.locale(
            {
                "tracker": {
                    "bad": "{role, select, developer {They approved it (non-binding)} other {You approved it}}",
                    "good": "{role, select, developer {They approved it} other {You approved it}} (non-binding)",
                    "key": "{state, select, approved {Waiting for review} other {Open}}",
                }
            }
        )
        found = self.violations()
        self.assertEqual(len(found), 1, found)
        self.assertIn("[tracker.bad]", found[0])

    def test_em2_template_needs_the_qualifier_outside_comments(self) -> None:
        path = "backend/src/bridge/notifications/templates/em2.txt.j2"
        self.write(path, "{{ company_name }} approved it.\n")
        self.assertEqual(len(self.violations()), 1)
        self.write(path, "{# non-binding #}{{ company_name }} approved it.\n")
        self.assertEqual(len(self.violations()), 1)
        self.write(path, "{{ company_name }} approved it. This is not a contract or a commitment to buy.\n")
        self.assertEqual(self.violations(), [])

    def test_the_em2_rule_applies_to_templates_not_modules(self) -> None:
        self.write("backend/src/bridge/notifications/em2.py", '"""EM2 approval email."""\nSUBJECT_KEY = "email.em2"\n')
        self.assertEqual(self.violations(), [])


class SpecMinimumAndRoundTwo(LintTree):
    """Hard-coded spec minimum (docs/spec/04 principle 2), independent of the rules file, and review round 2."""

    def test_the_spec_phrases_are_banned_whatever_the_rules_file_says(self) -> None:
        for phrase in ("theft-proof", "cannot be stolen", "protected idea", "patented"):
            with self.subTest(phrase=phrase):
                self.locale({"landing": {"t": f"Here: {phrase}."}})
                self.assertEqual(len(self.violations()), 1)

    def test_approve_and_approved_need_the_qualifier_whatever_the_rules_file_says(self) -> None:
        for label in ("Approve", "Approved", "They approved it", "Approving now"):
            with self.subTest(label=label):
                self.locale({"tracker": {"action": label}})
                self.assertEqual(len(self.violations()), 1)

    def test_attribute_copy_is_scanned(self) -> None:
        self.write("backend/src/bridge/notifications/templates/em1.html.j2", '<img alt="Theft-proof certificate">\n')
        self.write("backend/src/bridge/notifications/templates/meta.html", '<meta content="Your idea is theft-proof">\n')
        self.write("frontend/components/Banner.tsx", '<Banner title="Your idea is patented" />\n')
        self.write("frontend/components/Button.tsx", '<button aria-label="Make your idea theft-proof" />\n')
        self.assertEqual(len(self.violations()), 4, self.violations())

    def test_comparisons_are_not_tags(self) -> None:
        self.write(
            "backend/src/bridge/notifications/templates/em1.txt.j2",
            "{% if saved_count < 1 %}Your idea is theft-proof.{% endif %}\n{% if sent_count > 5 %}ok{% endif %}\n",
        )
        self.write("frontend/components/Cmp.tsx", "const ok = a < b; const t = 'patented'; const f = () => 1;\n")
        self.assertEqual(len(self.violations()), 2, self.violations())

    def test_block_elements_and_blank_lines_do_not_join_words(self) -> None:
        self.write(
            "backend/src/bridge/notifications/templates/em1.html.j2",
            "<h3>How your data is protected</h3><p>Ideas you register are timestamped.</p>\n",
        )
        self.write(
            "backend/src/bridge/notifications/templates/em1.txt.j2",
            "What to do if you suspect theft\n\nProof of authorship: {{ receipt_id }}\n",
        )
        self.assertEqual(self.violations(), [])

    def test_more_catalogue_and_template_locations_are_scanned(self) -> None:
        self.write("backend/src/bridge/notifications/locales/en/email.json", json.dumps({"s": "theft-proof"}))
        self.write("frontend/messages/en.json", json.dumps({"s": "patented"}))
        self.write("backend/src/bridge/locale/sw/LC_MESSAGES/bridge.po", 'msgid "x"\nmsgstr "theft-proof"\n')
        self.write("backend/src/bridge/notifications/emails/welcome.html", "<p>protected ideas</p>")
        self.write("backend/alembic/versions/0099_x.py", 'BODY = "cannot be stolen"\n')
        self.write("frontend/app/(dev)/build/page.tsx", "export default () => <p>Theft-proof builds</p>;\n")
        self.assertEqual(len(self.violations()), 6, self.violations())

    def test_the_em2_rule_ignores_non_template_files(self) -> None:
        self.write("frontend/lib/em2.ts", "export const subjectKey = 'email.em2.subject'; // approved\n")
        self.write("frontend/lib/em2.txt", "approved\n")
        self.assertEqual(self.violations(), [])

    def test_deliberate_evasions_are_folded(self) -> None:
        texts = ["théft-proof", "theft️-proof", "theftㅤproof", "theft⠀proof", "thеft-proof"]
        for text in texts:
            with self.subTest(text=text):
                self.locale({"landing": {"t": text}})
                self.assertEqual(len(self.violations()), 1)


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


class CiWiring(LintTree):
    """AC-IP-4 says CI fails: the lint must run in pr.yml and make check, and exit non-zero on a violation."""

    def test_the_hygiene_job_runs_the_lint_and_cannot_be_skipped(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
        job = re.search(r"\n  hygiene:\n(.*?)(?=\n  [\w-]+:\n)", workflow, re.S)
        assert job is not None
        block = job.group(1)
        step = re.search(r"- name: [^\n]*copy-lint[^\n]*\n((?:        [^\n]*\n)+)", block + "\n")
        assert step is not None, "no copy-lint step in the hygiene job"
        self.assertIn("run: python3 scripts/copy_lint.py", step.group(1))
        self.assertIn("if: ${{ !cancelled() }}", step.group(1))
        self.assertNotIn("continue-on-error", block)

    def test_make_check_runs_the_lint(self) -> None:
        makefile = (REPO / "Makefile").read_text(encoding="utf-8")
        check = re.search(r"^check:([^\n]*)$", makefile, re.M)
        assert check is not None
        self.assertIn("check-copy", check.group(1).split())
        self.assertRegex(makefile, r"(?m)^check-copy:\n\t[^\n]*scripts/copy_lint\.py")

    def test_the_process_exits_non_zero_on_a_violation(self) -> None:
        self.write("frontend/app/page.tsx", "const t = 'theft-proof';\n")
        script = REPO / "scripts" / "copy_lint.py"
        bad = subprocess.run([sys.executable, str(script), "--root", str(self.root)], capture_output=True, check=False)
        self.assertEqual(bad.returncode, 1, bad.stdout)
        good = subprocess.run([sys.executable, str(script)], capture_output=True, check=False)
        self.assertEqual(good.returncode, 0, good.stdout)


if __name__ == "__main__":
    unittest.main()
