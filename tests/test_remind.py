"""Policy, delivery and orchestration tests. No network: every side effect is injected or patched.

    .venv\\Scripts\\python.exe -m unittest tests.test_remind -v
"""
import http.client
import io
import json
import os
import shutil
import smtplib
import ssl
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime
from unittest import mock

from reminder import notify, remind
from reminder.remind import Config, Deps, Flagged, Verdict, classify, pick_featured, run
from reminder.scan import DAY, GitState, Project

NOW = datetime(2026, 9, 17, 9, 30)
TS = NOW.timestamp()
ALERT_17 = "Second Brain: the WhatsApp reminder did not go out today \u00b7 Thu 17 Sep"
ALERT_18 = "Second Brain: the WhatsApp reminder did not go out today \u00b7 Fri 18 Sep"
ENV_ALL = {"GMAIL_ADDRESS": "me@example.com", "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
           "WA_ACCESS_TOKEN": "tok", "WA_PHONE_NUMBER_ID": "123", "WA_TARGET_NUMBER": "254 700 000 000",
           "WA_TEMPLATE_NAME": "project_checkin", "WA_TEMPLATE_LANG": "en"}


def project(name, idle, git=None, todos=(), recent=("main.py",)):
    return Project(name=name, path=f"C:/p/{name}", last_work=TS - idle * DAY, idle_days=idle, files=3,
                   truncated=False, recent_files=list(recent), readme_title="", open_todos=len(todos),
                   todo_samples=list(todos), git=git)


def gitstate(modified=(), modified_age=0, unpushed=0, commit_age=10, commits=("wip",)):
    return GitState(branch="main", has_remote=True, unpushed=unpushed, last_commit=TS - commit_age * DAY,
                    recent_commits=list(commits), modified=list(modified), modified_partial=False,
                    modified_newest=(TS - modified_age * DAY) if modified else 0.0)


def cfg(**kw):
    base = dict(path="C:/cfg.json", projects_roots=["C:/p"], cold_after_days=3, at_risk_after_days=3)
    base.update(kw)
    return Config(**base)


class ClassifyTests(unittest.TestCase):
    def test_cold_threshold_boundary(self):
        flagged, quiet, _ = classify([project("warm", 2), project("cold", 3)], cfg(), TS, NOW.date())
        self.assertEqual([f.name for f in flagged], ["cold"])
        self.assertEqual([p.name for p in quiet], ["warm"])

    def test_done_and_snooze(self):
        c = cfg(done=["Finished"], snooze={"later": "2026-09-18", "back": "2026-09-17"})
        flagged, _, held = classify([project("finished", 9), project("later", 9), project("back", 9)], c, TS,
                                    NOW.date())
        self.assertEqual([f.name for f in flagged], ["back"])            # snooze ends ON its date
        self.assertEqual(sorted((p.name, why) for p, why in held),
                         [("finished", "done"), ("later", "snoozed until 2026-09-18")])

    def test_risk_age_boundaries(self):
        exactly = project("exactly", 1, gitstate(modified=["a.py", "b.py"], modified_age=3, unpushed=1, commit_age=3))
        under = project("under", 1, gitstate(modified=["a.py"], modified_age=2, unpushed=2, commit_age=2))
        flagged, quiet, _ = classify([exactly, under], cfg(), TS, NOW.date())
        self.assertEqual([f.name for f in flagged], ["exactly"])
        self.assertEqual(flagged[0].risks, ["2 changed files not committed for 3 days",
                                            "1 commit not pushed for 3 days"])
        self.assertFalse(flagged[0].cold)
        self.assertEqual([p.name for p in quiet], ["under"])

    def test_order_risk_first_then_most_recently_dropped(self):
        ps = [project("old", 50), project("recent", 4), project("risk", 60, gitstate(modified=["x"], modified_age=60))]
        flagged, _, _ = classify(ps, cfg(), TS, NOW.date())
        self.assertEqual([f.name for f in flagged], ["risk", "recent", "old"])

    def test_rotation_prefers_never_or_least_recently_featured(self):
        fl = [Flagged(project(n, 5), True, []) for n in ("a", "b", "c")]
        self.assertEqual(pick_featured(fl, {}).name, "a")
        self.assertEqual(pick_featured(fl, {"a": "2026-09-16"}).name, "b")
        self.assertEqual(pick_featured(fl, {"a": "2026-09-16", "b": "2026-09-15", "c": "2026-09-14"}).name, "c")
        self.assertIsNone(pick_featured([], {}))


class WordingTests(unittest.TestCase):
    def setUp(self):
        self.f = Flagged(project("app", 5, todos=["ship it"]), True, [])

    def test_fallback_prefers_risk_then_todo(self):
        risky = Flagged(project("r", 5, gitstate(modified=["a.py"], modified_age=5)), True,
                        ["1 changed file not committed for 5 days"])
        self.assertEqual(remind.fallback_text(risky).next_step, "Look over your changes in a.py, then commit them.")
        unpushed = Flagged(project("u", 5, gitstate(unpushed=2)), True, ["2 commits not pushed for 5 days"])
        self.assertEqual(remind.fallback_text(unpushed).next_step, "Push your 2 commits so the work is backed up.")
        self.assertIn("ship it", remind.fallback_text(self.f).next_step)
        self.assertEqual(remind.fallback_text(self.f).source, "fallback")

    def test_verdict_for_rejects_empty_agent_text(self):
        good = Verdict(status="unfinished", left_off="x", next_step="y")
        self.assertIs(remind.verdict_for(self.f, {"app": good}), good)
        self.assertEqual(remind.verdict_for(self.f, {"app": Verdict(left_off="", next_step="y")}).source, "fallback")
        self.assertEqual(remind.verdict_for(self.f, {"app": "junk"}).source, "fallback")

    def test_actionable_excludes_done_and_non_projects(self):
        fl = [Flagged(project(n, 5), True, []) for n in ("a", "b", "c", "d")]
        verdicts = {"a": Verdict(status="probably_done", left_off="x", next_step="y"),
                    "b": Verdict(status="not_a_project", left_off="x", next_step="y"),
                    "c": Verdict(status="unclear", left_off="x", next_step="y")}
        self.assertEqual([f.name for f in remind.actionable(fl, verdicts)], ["c", "d"])

    def test_whatsapp_params_are_template_safe(self):
        payload = notify.build_whatsapp_template("+254 700-000-000", "t", "en",
                                                 ["a\nb", "c\t\td", "e     f", "", "z" * 500])
        params = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
        self.assertEqual(payload["to"], "254700000000")
        self.assertEqual(params[:4], ["a b", "c d", "e f", "-"])
        self.assertEqual(len(params[4]), notify.WA_PARAM_MAX)
        for p in params:
            self.assertNotRegex(p, r"[\n\t]| {4,}")

    def test_variables_cannot_carry_whatsapp_formatting(self):
        """WhatsApp pairs *, _, ~ and ` marks across the message, so one stray mark in a commit message
        would bold or italicise the template's own text. Marks become look-alikes, except an underscore
        inside a word, which WhatsApp never treats as a mark."""
        clean = notify.clean_param
        self.assertEqual(clean("Look over test_remind.py and app_v2.py"), "Look over test_remind.py and app_v2.py")
        self.assertEqual(clean("__init__.py"), "\uff3f\uff3finit\uff3f\uff3f.py")
        self.assertEqual(clean("fix *the* parser, ~/notes, `npm test`, _draft_"),
                         "fix \u2217the\u2217 parser, \u223c/notes, \u02cbnpm test\u02cb, \uff3fdraft\uff3f")
        self.assertEqual(clean("my*app"), "my\u2217app")
        for raw in ("a * b", "*", "_x", "x_", "x _ y", "~~", "`", "**bold**", "snake_case_name", "__dunder__",
                    "\u00e9_x", "_"):
            out = clean(raw)
            self.assertNotRegex(out, r"[*~`]", raw)
            self.assertNotRegex(out, r"(?<![^\W_])_|_(?![^\W_])", raw)       # no underscore at a word edge
        shown = notify.render_template_preview(["my*app", "no work", "fix *the* parser", "edit __init__.py"])
        self.assertEqual(shown.count("*"), 2 + notify.TEMPLATE_BODY.count("*"))   # header + the labels' own pairs
        self.assertEqual(shown.count("_"), 2)                                     # only the footer's italics

    def test_template_preview_fills_variables_the_way_they_are_sent(self):
        shown = notify.render_template_preview(["app", "no work\nfor 5 days", "left {{4}} off", "next"])
        self.assertTrue(shown.startswith("*Daily project update*\n\nHere is today's update"))
        self.assertTrue(shown.endswith("_Sent by your Second Brain_"))
        self.assertIn("*Today's project:* app\n", shown)
        self.assertIn("*Why it is on the list:* no work for 5 days\n", shown)   # cleaned like the real send
        self.assertIn("\nleft {{4}} off\n", shown)                          # a variable's text is never re-filled
        self.assertIn("\nnext\n", shown)
        self.assertIn("{{3}}", notify.render_template_preview(["only", "two"]))  # too few values: left visible

    def test_template_definition_follows_meta_review_rules(self):
        import difflib
        import re
        d = notify.build_template_definition("project_checkin_v2", "en")
        parts = {c["type"]: c for c in d["components"]}
        self.assertEqual(list(parts), ["HEADER", "BODY", "FOOTER"])
        body = parts["BODY"]["text"]
        nums = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)]
        self.assertEqual(nums, [1, 2, 3, 4])                                 # sequential, no gaps
        self.assertFalse(re.match(r"^\s*\{\{", body) or re.search(r"\}\}\s*$", body))   # not at start/end
        self.assertIsNone(re.search(r"\}\}\s*\{\{", body))                   # never adjacent
        self.assertEqual(parts["BODY"]["example"], {"body_text": [notify.TEMPLATE_EXAMPLE]})   # a list of lists
        self.assertEqual(len(notify.TEMPLATE_EXAMPLE), 4)
        self.assertLessEqual(len(body), 1024)
        self.assertIsNone(re.search(r"\n{3,}", body))                         # at most one blank line in a row
        fixed = len(re.sub(r"\{\{\d+\}\}", "", body))
        self.assertLessEqual(fixed + 4 * notify.WA_PARAM_MAX + 24, 1024)     # fits even when filled in (132005)
        # Bold marks sit on fixed label text only: never touching a variable, in pairs, one label per variable.
        self.assertIsNone(re.search(r"[*_~]\{\{|\}\}[*_~]", body))
        self.assertEqual(body.count("*") % 2, 0)
        self.assertEqual(len(re.findall(r"\*([^*\n]+)\*", body)), 4)
        self.assertNotRegex(body, r"(?m)^[*-] ")                              # "* " or "- " at a line start = bullet
        self.assertTrue(body.startswith("Here is today's update"))            # opens and closes with a sentence
        self.assertTrue(body.endswith("."))
        # Meta rejects a template that repeats an existing one's wording, and one with too few fixed words
        # for its variables. The first approved template, for comparison:
        first = ("Your daily project check-in: {{1}} needs attention ({{2}}).\n\nWhere you left off: {{3}}\n\n"
                 "Suggested next step: {{4}}\n\nThe full list of waiting projects is in today's email.")

        def words(s):
            return re.sub(r"\{\{\d+\}\}|[^\w\s']", " ", s).lower().split()
        self.assertLess(difflib.SequenceMatcher(None, words(first), words(body)).ratio(), 0.5)
        self.assertGreaterEqual(len(words(body)), 3 * 4 + 1 + 15)
        for fixed_part in (parts["HEADER"], parts["FOOTER"]):               # static: no variables or marks, short
            self.assertNotRegex(fixed_part["text"], r"[{}\n*_~`-]")
            self.assertLessEqual(len(fixed_part["text"]), 60)
        self.assertEqual(set(parts["HEADER"]), {"type", "format", "text"})   # no example: it has no variable
        self.assertEqual(parts["HEADER"]["format"], "TEXT")
        self.assertEqual(set(parts["FOOTER"]), {"type", "text"})
        self.assertEqual((d["category"], d["parameter_format"]), ("UTILITY", "positional"))
        self.assertTrue(re.fullmatch(r"[a-z0-9_]+", d["name"]))
        hello = notify.build_hello_world("+254 700 000 000")
        self.assertEqual((hello["to"], hello["template"]["name"], hello["template"]["language"]["code"]),
                         ("254700000000", "hello_world", "en_US"))

    def test_whatsapp_headline_puts_work_at_risk_first(self):
        p = project("app", 5)
        self.assertEqual(Flagged(p, True, []).headline(), "no work for 5 days")
        self.assertEqual(Flagged(p, False, ["1 commit not pushed for 4 days"]).headline(),
                         "work at risk: 1 commit not pushed for 4 days")
        self.assertEqual(Flagged(p, True, ["a", "b"]).headline(), "work at risk: a, b; no work for 5 days")

    def test_email_escapes_html_including_agent_text(self):
        fl = [Flagged(project("<script>x</script>", 5, recent=["<b>.py"]), True, [])]
        verdicts = {"<script>x</script>": Verdict(status="unfinished", left_off="<img src=x onerror=1>",
                                                  next_step="<i>step</i>", evidence=["<e>"], confidence=0.5)}
        _, text, body = remind.compose_email(fl, [], [], [], verdicts, cfg(), NOW.date(), TS)
        for raw in ("<script>", "<img", "<i>step", "<e>"):
            self.assertNotIn(raw, body)
        self.assertIn("&lt;img src=x onerror=1&gt;", body)
        self.assertIn("<script>x</script>", text)                      # plain-text part stays literal

    def test_email_sections_for_done_and_non_projects(self):
        fl = [Flagged(project(n, 5), True, []) for n in ("work", "fin", "junk")]
        verdicts = {"fin": Verdict(status="probably_done", left_off="shipped", next_step="none", confidence=0.9),
                    "junk": Verdict(status="not_a_project", left_off="downloads", next_step="ignore", confidence=0.7)}
        subject, text, body = remind.compose_email(fl, [], [], [], verdicts, cfg(), NOW.date(), TS)
        self.assertEqual(subject, "1 project needs you today: work (no work for 5 days) \u00b7 Thu 17 Sep")
        self.assertIn('add "fin" to the "done" list, like this: "done": ["fin"]. You will not be reminded', text)
        self.assertIn('add "junk" to the "ignore" list, like this: "ignore": ["junk"]. The reminder will stop', text)
        self.assertEqual(text.count("If you do not agree, you do not need to do anything."), 2)
        self.assertIn('looked inside 2 of the 3 listed projects. The other one is marked "quick check".', text)
        self.assertEqual(text.count(remind.QUICK_NOTE), 1)                  # "work" had no verdict
        self.assertIn("add <b>&quot;fin&quot;</b> to the <b>&quot;done&quot;</b> list", body)
        self.assertIn(">&quot;done&quot;: [&quot;fin&quot;]</code>", body)
        # Same reading order in both parts.
        order = ["AT A GLANCE", "PROJECTS THAT NEED YOU", "MAYBE FINISHED", "MAYBE NOT A PROJECT", "HOW THIS WORKS"]
        self.assertEqual(sorted(order, key=text.index), order)
        headings = [f">{h}</h2>" for h in ("Projects that need you", "Maybe finished", "Maybe not a project",
                                            "How this works")]
        self.assertEqual(sorted(headings, key=body.index), headings)
        self.assertLess(body.index("At a glance"), body.index(headings[0]))
        # Only a project that needs work gets a next step; the others get "what you can do".
        self.assertEqual(text.count(">> YOUR NEXT STEP"), 1)
        self.assertEqual(text.count(">> WHAT YOU CAN DO"), 2)
        self.assertNotIn("none", text.split("MAYBE FINISHED")[1].split("MAYBE NOT A PROJECT")[0])


class EmailLayoutTests(unittest.TestCase):
    """The email is for a reader who has never seen the code: clear parts, one action each."""

    def compose(self, flagged, verdicts=None, quiet=(), held=(), skipped=(), notices=()):
        return remind.compose_email(flagged, list(quiet), list(held), list(skipped), verdicts or {}, cfg(),
                                    NOW.date(), TS, notices=notices)

    def test_at_a_glance_counts_every_group(self):
        fl = [Flagged(project(n, 5), True, []) for n in ("w1", "w2", "fin")]
        verdicts = {"fin": Verdict(status="probably_done", left_off="x", next_step="y", confidence=0.9)}
        _, text, body = self.compose(fl, verdicts, quiet=[project("ok", 0), project("ok2", 1)])
        for line in ("2 projects need you today.", '"The assistant" in this email is an AI helper',
                     "- Need you: 2", "- Maybe finished: 1", "- Maybe not projects: 0", "- Going fine: 2",
                     "ok (today), ok2 (yesterday)", "The most urgent one is first. Start with number 1"):
            self.assertIn(line, text)
        self.assertIn("<b>2 projects</b> need you today.", body)
        self.assertIn("1. w1", text)                                        # numbered when there is a choice
        self.assertIn("2. w2", text)

    def test_single_project_is_not_numbered_and_reads_in_the_singular(self):
        subject, text, _ = self.compose([Flagged(project("solo", 1), False, ["1 commit not pushed for 4 days"])])
        self.assertEqual(subject, "1 project needs you today: solo (work at risk) \u00b7 Thu 17 Sep")
        self.assertIn("1 project needs you today.", text)
        self.assertIn("It has one small next step. You can start now.", text)
        self.assertIn("- solo", text)
        self.assertNotIn("1. solo", text)
        self.assertIn("Last worked on yesterday", text)
        self.assertIn("!! WORK AT RISK:\n      - 1 commit not pushed for 4 days. This work is only on this laptop, "
                      "not backed up online.", text)

    def test_work_at_risk_is_explained_and_worked_on_today_is_not_highlighted(self):
        import re
        busy = project("busy", 0, gitstate(modified=["a.py"], modified_age=4, unpushed=1, commit_age=4))
        subject, text, body = self.compose([Flagged(busy, False, ["1 changed file not committed for 4 days",
                                                                   "1 commit not pushed for 4 days"])])
        self.assertIn("busy (work at risk)", subject)
        self.assertIn("- 1 changed file not committed for 4 days. This work is not saved in git yet.", text)
        self.assertIn("- 1 commit not pushed for 4 days. This work is only on this laptop", text)
        self.assertEqual(body.count("&#9888; Work at risk"), 1)             # one red box, a line per risk
        self.assertNotIn("#fef3c7", body)                                  # "Worked on today" is not news
        self.assertIn(">Worked on today</span>", body)
        _, _, cold_body = self.compose([Flagged(project("old", 9), True, [])])
        self.assertRegex(cold_body, r"background:#fef3c7;color:#92400e;font-weight:700;[^>]*>No work for 9 days<")

    def test_many_projects_keep_the_subject_short(self):
        fl = [Flagged(project(n, 5), True, []) for n in "abcde"]
        subject, _, _ = self.compose(fl)
        self.assertEqual(subject, "5 projects need you today: a (no work for 5 days), b (no work for 5 days), "
                                  "c (no work for 5 days) and 2 more \u00b7 Thu 17 Sep")

    def test_nothing_actionable_says_so(self):
        fl = [Flagged(project("fin", 5), True, [])]
        verdicts = {"fin": Verdict(status="probably_done", left_off="x", next_step="y", confidence=0.9)}
        subject, text, body = self.compose(fl, verdicts)
        self.assertEqual(subject, "Project check-in: no project needs work today \u00b7 Thu 17 Sep")
        self.assertIn("No project needs work today.", text)
        self.assertNotIn("PROJECTS THAT NEED YOU", text)
        self.assertNotIn(">> YOUR NEXT STEP", text)
        self.assertIn("The assistant looked inside the listed project.", text)
        self.assertNotIn("quick check", text.lower())

    def test_next_step_is_the_highlighted_part(self):
        fl = [Flagged(project("app", 5), True, [])]
        verdicts = {"app": Verdict(status="unfinished", left_off="Auth built.", next_step="Wire the scheduler.",
                                   evidence=["README.md: open item", "app.py: stub"], confidence=0.8)}
        _, text, body = self.compose(fl, verdicts)
        self.assertIn(">> YOUR NEXT STEP (about 15 minutes):\n      Wire the scheduler.", text)
        self.assertIn("Where you left off:\n      Auth built.", text)
        self.assertRegex(body, r"background:#fffbeb[^>]*>.*?Your next step.*?font-weight:700[^>]*>Wire the scheduler\.")
        self.assertIn("- Clues the assistant checked:\n          * README.md: open item", text)
        self.assertIn("<li style=\"margin:0 0 2px\">app.py: stub</li>", body)
        self.assertIn("Start with app: Wire the scheduler.", body)          # inbox preview line

    def test_everything_else_groups_skipped_folders(self):
        skipped = [("scratch", "ignored"), (".claude", "ignored"), ("one_backup", "copy of one")] + \
                  [(f"app_backup{i}", "copy of app") for i in range(5)] + [("odd", "unreadable: OSError")]
        held = [(project("old", 50), "done"), (project("later", 9), "snoozed until 2026-10-01")]
        _, text, body = self.compose([Flagged(project("app", 5), True, [])], skipped=skipped, held=held)
        for line in ("- Skipped (on your ignore list): scratch\n", "- Skipped (hidden folders): .claude",
                     "- Skipped (1 backup copy of one): one_backup",
                     "- Skipped (5 backup copies of app): app_backup0, app_backup1, app_backup2 and 2 more",
                     "- Skipped (could not be read): odd (unreadable: OSError)",
                     "- Marked done or snoozed by you: old (done), later (snoozed until 2026-10-01)",
                     "This list shows your other folders"):
            self.assertIn(line, text)
        self.assertIn("did not look inside any project this time", text)   # no verdicts were passed in
        self.assertNotIn("looked inside 0 of", text)
        self.assertIn("<b>Marked done or snoozed by you:</b>", body)

    def test_how_this_works_uses_the_real_settings_and_explains_the_words(self):
        _, text, body = remind.compose_email([Flagged(project("app", 9), True, [])], [], [], [], {},
                                             cfg(cold_after_days=7, at_risk_after_days=2), NOW.date(), TS)
        self.assertIn("none of its files have changed for 7 days", text)
        self.assertIn("not committed or pushed for 2 days", text)
        self.assertIn('"snooze": {"project-name": "2026-10-01"}', text)      # two weeks from NOW, never stale
        self.assertIn("Your settings file is C:/cfg.json.", text)
        for word in ("git", "commit", "push"):
            self.assertIn(f"<b>{word}</b>", body)                            # each technical word explained once
        self.assertNotIn("**", text)                                        # marks never leak into plain text
        self.assertNotIn("`", text)

    def test_the_assistants_hint_is_bold_in_html_and_plain_in_text(self):
        fl = [Flagged(project(n, 5), True, []) for n in ("fin", "junk")]
        verdicts = {"fin": Verdict(status="probably_done", left_off="x", next_step="y", confidence=0.9),
                    "junk": Verdict(status="not_a_project", left_off="x", next_step="y", confidence=0.7)}
        _, text, body = self.compose(fl, verdicts)
        self.assertNotIn("**", text)
        self.assertIn("thinks this is finished (90% sure)", text)
        self.assertIn("thinks this is not a real project (70% sure)", text)
        self.assertIn("thinks this is <b>finished</b> (90% sure)", body)
        self.assertIn("thinks this is <b>not a real project</b> (70% sure)", body)

    def test_only_the_work_section_is_numbered(self):
        names = ("f1", "f2", "j1", "j2")
        fl = [Flagged(project(n, 5), True, []) for n in names]
        verdicts = {n: Verdict(status="probably_done" if n[0] == "f" else "not_a_project",
                               left_off="x", next_step="y", confidence=0.9) for n in names}
        _, text, _ = self.compose(fl, verdicts)
        for n in names:
            self.assertIn(f"- {n}", text)
            self.assertNotRegex(text, rf"\d\. {n}")

    def test_days_ago_wording_and_the_last_commit_fact(self):
        self.assertEqual([remind._ago(d) for d in (-1, 0, 1, 2, 9)],
                         ["today", "today", "yesterday", "2 days ago", "9 days ago"])
        _, text, _ = self.compose([Flagged(project("app", 5, gitstate(commit_age=4)), True, [])])
        self.assertIn("No work for 5 days  |  Last commit 4 days ago", text)

    def test_heads_up_comes_right_after_at_a_glance(self):
        _, text, body = self.compose([Flagged(project("app", 5), True, [])], notices=["Check **this** `now`"])
        self.assertIn("HEADS-UP\n  ! Check this now", text)
        self.assertLess(text.index("AT A GLANCE"), text.index("HEADS-UP"))
        self.assertLess(text.index("HEADS-UP"), text.index("PROJECTS THAT NEED YOU"))
        self.assertIn("Check <b>this</b> <code", body)
        _, text, _ = self.compose([Flagged(project("app", 5), True, [])])
        self.assertNotIn("HEADS-UP", text)

    def test_marks_cannot_smuggle_markup(self):
        self.assertEqual(remind._marks_html('**<b onclick=x>** & "q"'),
                         "<b>&lt;b onclick=x&gt;</b> &amp; &quot;q&quot;")
        self.assertRegex(remind._marks_html("run `<x>`"), r'^run <code style="[^"]+">&lt;x&gt;</code>$')
        self.assertEqual(remind._marks_text("a **b** `c`"), "a b c")
        self.assertEqual([remind._and_list(x) for x in ([], ["a"], ["a", "b"], ["a", "b", "c"])],
                         ["", "a", "a and b", "a, b and c"])

    def test_html_is_a_complete_well_nested_document_that_wraps_on_a_phone(self):
        from html.parser import HTMLParser
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
                "track", "wbr"}

        class Nesting(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.errors = [], []

            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    self.stack.append(tag)

            def handle_startendtag(self, tag, attrs):
                pass                                                        # <tag/> opens and closes itself

            def handle_endtag(self, tag):
                if not self.stack or self.stack.pop() != tag:
                    self.errors.append(tag)

        risky = project("risky", 6, gitstate(modified=[f"f{i}.py" for i in range(10)], modified_age=6, unpushed=2,
                                             commit_age=6), todos=["one", "two"])
        fl = [Flagged(risky, True, ["10 changed files not committed for 6 days"]),
              Flagged(project("w2", 5), True, []), Flagged(project("fin", 5), True, []),
              Flagged(project("junk", 5), True, [])]
        verdicts = {"risky": Verdict(status="unfinished", left_off="l", next_step="n", evidence=["a", "b"]),
                    "fin": Verdict(status="probably_done", left_off="x", next_step="y", confidence=0.9),
                    "junk": Verdict(status="not_a_project", left_off="x", next_step="y", confidence=0.7)}
        _, text, body = self.compose(fl, verdicts, quiet=[project("ok", 0)], skipped=[("s", "ignored")],
                                     notices=["a **b** `c`"])
        self.assertTrue(body.startswith("<!doctype html>"))
        self.assertTrue(body.endswith("</body></html>"))
        self.assertIn('name="viewport"', body)
        self.assertIn("overflow-wrap:anywhere", body)
        for doc in (body, remind.compose_alert("whatsapp", {"error": "code 132001"}, "log", NOW.date())[2]):
            checker = Nesting()
            checker.feed(doc)
            self.assertEqual((checker.errors, checker.stack), ([], []))
        self.assertIn("f7.py \u2026", text)                                 # long file lists are cut, and say so
        self.assertNotIn("f8.py", text)

    def test_alert_email_says_how_to_fix_it_before_the_technical_details(self):
        entry = {"hard_failures": 3, "error": "WhatsApp API HTTP 404, code 132001: <tmpl> not in en"}
        subject, text, body = remind.compose_alert("whatsapp", entry, "C:/x/remind.log", NOW.date())
        self.assertEqual(subject, "Second Brain: the WhatsApp reminder did not go out today \u00b7 Thu 17 Sep")
        order = ["WHAT HAPPENED", "HOW TO FIX IT", "TECHNICAL DETAILS", "C:/x/remind.log"]
        self.assertEqual(sorted(order, key=text.index), order)
        for part in ("tried 3 times today", "Your daily email was sent as normal", "usually does not fix itself",
                     "called a template", "\n      python -m reminder --whatsapp-template-status\n",
                     "Error: WhatsApp API HTTP 404, code 132001"):
            self.assertIn(part, text)
        self.assertIn("&lt;tmpl&gt;", body)
        self.assertNotIn("<tmpl>", body)
        self.assertLess(body.index("How to fix it"), body.index("Technical details"))
        self.assertIn(">python -m reminder --whatsapp-template-status</div>", body)
        _, text, _ = remind.compose_alert("whatsapp", {}, "log", NOW.date())   # a bare entry must not crash
        self.assertIn("tried 0 times", text)
        self.assertNotIn("\n      python", text)                            # no command for an unknown error

    def test_every_known_failure_has_its_own_hint(self):
        for needle, hint, command in remind.FIX_HINTS:
            with self.subTest(needle=needle):
                self.assertEqual(remind.fix_hint(f"WhatsApp API HTTP 400, {needle}: details"), (hint, command))
        self.assertIn("log file", remind.fix_hint("something new")[0])
        self.assertEqual(remind.fix_hint("something new")[1], "")


class EnvAndConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb-remind-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, content):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_load_env_handles_quotes_comments_and_spaces(self):
        self.write(".env", '# c\nA=1\nB= spaced \nC="quoted # not comment"\nD=val # comment\nexport E=e\nBAD\n'
                           'F="abcd efgh ijkl mnop"  # app password\nG=\'single\' # x\nH="unterminated\n')
        env = remind.load_env(os.path.join(self.tmp, ".env"))
        self.assertEqual(env, {"A": "1", "B": "spaced", "C": "quoted # not comment", "D": "val", "E": "e",
                               "F": "abcd efgh ijkl mnop", "G": "single", "H": "unterminated"})

    def test_real_environment_variable_wins(self):
        self.write(".env", "A=file\n")
        with mock.patch.dict(os.environ, {"A": "process"}):
            self.assertEqual(remind.load_env(os.path.join(self.tmp, ".env"))["A"], "process")

    def test_config_created_from_example_and_validated(self):
        self.write("reminders.example.json", json.dumps({"_help": "x", "projects_roots": [self.tmp]}))
        c = remind.load_config(self.tmp)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "reminders.json")))
        self.assertEqual((c.cold_after_days, c.send_after_hour, c.max_investigate), (3, 8, 4))

    def test_config_errors_are_specific(self):
        cases = [({"projects_roots": [self.tmp], "cold_after": 3}, "unknown setting"),
                 ({"projects_roots": [os.path.join(self.tmp, "missing")]}, "projects root not found"),
                 ({"projects_roots": [self.tmp], "snooze": {"a": "next week"}}, "YYYY-MM-DD"),
                 ({"projects_roots": [self.tmp], "cold_after_days": 0}, "whole number"),
                 ({"projects_roots": [self.tmp], "done": "app"}, "list of folder names")]
        for raw, msg in cases:
            self.write("reminders.json", json.dumps(raw))
            with self.assertRaisesRegex(remind.ConfigError, msg):
                remind.load_config(self.tmp)
        self.write("reminders.json", "{not json")
        with self.assertRaisesRegex(remind.ConfigError, "not valid JSON"):
            remind.load_config(self.tmp)

    def test_state_save_retries_locked_file_and_prunes_old_days(self):
        st = {"days": {f"2026-08-{d:02d}": {} for d in range(1, 21)}, "featured": {}}
        real_replace, calls = os.replace, []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("locked by antivirus")
            real_replace(src, dst)
        with mock.patch("reminder.remind.os.replace", flaky), mock.patch("reminder.remind.time.sleep"):
            remind.save_state(self.tmp, st)
        saved = remind.load_state(self.tmp)
        self.assertEqual(len(saved["days"]), remind.KEEP_DAYS)
        self.assertIn("2026-08-20", saved["days"])
        self.assertNotIn("2026-08-01", saved["days"])


class NotifyTests(unittest.TestCase):
    def test_tls_context_only_drops_strict_flag(self):
        ctx, default = notify.tls_context(), ssl.create_default_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertFalse(ctx.verify_flags & ssl.VERIFY_X509_STRICT)
        self.assertEqual(ctx.verify_flags | ssl.VERIFY_X509_STRICT, default.verify_flags | ssl.VERIFY_X509_STRICT)
        self.assertEqual((ctx.minimum_version, ctx.options), (default.minimum_version, default.options))

    def test_send_email_uses_starttls_before_login_and_reports_refusals(self):
        calls = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                calls.append(("connect", host, port))

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def ehlo(self):
                calls.append(("ehlo",))

            def starttls(self, context):
                assert context.verify_mode == ssl.CERT_REQUIRED
                calls.append(("starttls",))

            def login(self, user, password):
                calls.append(("login", user, password))

            def send_message(self, msg):
                calls.append(("send", msg["To"]))
                return {"bad@example.com": (550, b"no")} if msg["To"] == "bad@example.com" else {}

        msg = notify.build_email("me@example.com", "you@example.com", "s", "t", "<p>h</p>")
        with mock.patch("reminder.notify.smtplib.SMTP", FakeSMTP):
            notify.send_email("me@example.com", "abcd efgh ijkl mnop", msg)
            self.assertEqual([c[0] for c in calls], ["connect", "ehlo", "starttls", "ehlo", "login", "send"])
            self.assertEqual(calls[0][2], 587)
            self.assertEqual(calls[4], ("login", "me@example.com", "abcdefghijklmnop"))   # spaces stripped
            bad = notify.build_email("me@example.com", "bad@example.com", "s", "t", "h")
            with self.assertRaisesRegex(notify.DeliveryError, "refused recipients"):
                notify.send_email("me@example.com", "pw", bad)

    def test_send_email_error_classification(self):
        def failing(exc):
            class F:
                def __init__(self, *a, **k):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def ehlo(self):
                    pass

                def starttls(self, context):
                    pass

                def login(self, u, p):
                    raise exc
            return F
        msg = notify.build_email("a@b.c", "a@b.c", "s", "t", "h")
        cases = [(smtplib.SMTPAuthenticationError(535, b"bad"), False, "App Password"),
                 (OSError("no network"), True, "Email send failed"),
                 (smtplib.SMTPServerDisconnected("gone"), True, "Email send failed"),
                 (smtplib.SMTPResponseException(451, b"try later"), True, "Email send failed"),
                 (smtplib.SMTPResponseException(554, b"rejected"), False, "Email send failed")]
        for exc, transient, text in cases:
            with mock.patch("reminder.notify.smtplib.SMTP", failing(exc)):
                with self.assertRaisesRegex(notify.DeliveryError, text) as cm:
                    notify.send_email("a@b.c", "pw", msg)
                self.assertEqual(cm.exception.transient, transient, exc)

    def test_whatsapp_error_mapping(self):
        def http_error(code, body):
            return urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(body))

        def ok(body):
            resp = mock.MagicMock()
            resp.read.return_value = body
            resp.__enter__.return_value = resp
            return resp
        payload = notify.build_hello_world("254700000000")
        cases = [(http_error(401, b'{"error":{"code":190,"message":"expired"}}'), False, "code 190: expired"),
                 (http_error(429, b'{"error":{"code":130429,"message":"rate"}}'), True, "HTTP 429"),
                 (http_error(500, b"<html>oops</html>"), True, "oops"),
                 (urllib.error.URLError("dns"), True, "unreachable"),
                 (http.client.IncompleteRead(b"x"), True, "IncompleteRead"),
                 (TimeoutError("slow"), True, "unreachable")]
        for exc, transient, text in cases:
            with mock.patch("reminder.notify.urllib.request.urlopen", side_effect=exc):
                with self.assertRaisesRegex(notify.DeliveryError, text) as cm:
                    notify.send_whatsapp("t", "1", payload)
                self.assertEqual(cm.exception.transient, transient, text)
        for body, code in ((b'{"error":{"code":132001,"message":"no template"}}', 132001),
                           (b'{"error":{"code":"132001"}}', None), (b'{"error":{"code":true}}', None),
                           (b'{"error":"flat"}', None), (b"[]", None), (b"<html>", None)):
            with mock.patch("reminder.notify.urllib.request.urlopen", side_effect=http_error(404, body)):
                with self.assertRaises(notify.DeliveryError) as cm:
                    notify.send_whatsapp("t", "1", payload)
            self.assertEqual((cm.exception.code, cm.exception.transient), (code, False), body)
        self.assertIsNone(notify.DeliveryError("plain").code)
        self.assertEqual(notify.TEMPLATE_UNAVAILABLE, {132001, 132015, 132016})
        with mock.patch("reminder.notify.urllib.request.urlopen", return_value=ok(b"not json")):
            with self.assertRaisesRegex(notify.DeliveryError, "unreadable JSON") as cm:
                notify.send_whatsapp("t", "1", payload)
            self.assertTrue(cm.exception.transient)
        with mock.patch("reminder.notify.urllib.request.urlopen", return_value=ok(b'{"messages":[{}]}')):
            with self.assertRaisesRegex(notify.DeliveryError, "no message id"):
                notify.send_whatsapp("t", "1", payload)
        with mock.patch("reminder.notify.urllib.request.urlopen", return_value=ok(b'[1,2]')):
            with self.assertRaisesRegex(notify.DeliveryError, "unexpected body"):
                notify.send_whatsapp("t", "1", payload)
        with mock.patch("reminder.notify.urllib.request.urlopen", return_value=ok(b'{"messages":[{"id":"wamid.9"}]}')) as m:
            self.assertEqual(notify.send_whatsapp("t", "1", payload), "wamid.9")
            req = m.call_args[0][0]
            self.assertEqual(req.get_header("Authorization"), "Bearer t")
            self.assertIn("/v26.0/1/messages", req.full_url)


class RunTests(unittest.TestCase):
    """Guards, retries, alerts and state through the real LangGraph workflow with fake
    scanner / agent / senders."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb-run-")
        with open(os.path.join(self.tmp, "reminders.json"), "w", encoding="utf-8") as fh:
            json.dump({"projects_roots": [self.tmp]}, fh)
        self.projects = [project("cold-one", 6), project("warm", 0)]
        self.sent = {"email": [], "whatsapp": []}
        self.failing = {"email": None, "whatsapp": None}
        self.verdicts = {}
        self.scans = 0
        self.email_attempts = 0
        self.output = []
        self.mails = []
        self.template_rows = []             # what Meta "says" about templates; an Exception is raised instead
        self.status_calls = []

        def fake_discover(roots, ignore, track, now):
            self.scans += 1
            if isinstance(self.projects, Exception):
                raise self.projects
            return list(self.projects), []

        def fake_email(user, pw, msg):
            self.email_attempts += 1
            if self.failing["email"]:
                raise self.failing["email"]
            self.sent["email"].append(msg["Subject"])
            self.mails.append(msg)

        def fake_wa(token, pnid, payload, version):
            if self.failing["whatsapp"]:
                raise self.failing["whatsapp"]
            self.sent["whatsapp"].append(payload)
            return "wamid.1"

        def fake_status(token, waba, name, version):
            self.status_calls.append(name)
            if isinstance(self.template_rows, Exception):
                raise self.template_rows
            return list(self.template_rows)

        self.deps = Deps(discover=fake_discover, investigate=lambda fl, c, e, o: dict(self.verdicts),
                         send_email=fake_email, send_whatsapp=fake_wa, template_status=fake_status)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def go(self, now=NOW, env=ENV_ALL, **kw):
        return run(self.tmp, now, dict(env), deps=self.deps, out=self.output.append, **kw)

    def day(self, d="2026-09-17"):
        return remind.load_state(self.tmp)["days"].get(d, {})

    def wa_params(self, i=0):
        return [p["text"] for p in self.sent["whatsapp"][i]["template"]["components"][0]["parameters"]]

    def test_before_send_hour_does_nothing(self):
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 7, 59)), 0)
        self.assertEqual(self.scans, 0)

    def test_sends_both_once_per_day(self):
        self.assertEqual(self.go(), 0)
        self.assertEqual((len(self.sent["email"]), len(self.sent["whatsapp"])), (1, 1))
        self.assertEqual(self.wa_params()[:2], ["cold-one", "no work for 6 days"])
        self.assertEqual((self.day()["email"]["status"], self.day()["whatsapp"]["status"]), ("sent", "sent"))
        self.assertEqual(remind.load_state(self.tmp)["featured"], {"cold-one": "2026-09-17"})
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 10, 0)), 0)   # second run same day: nothing
        self.assertEqual((len(self.sent["email"]), len(self.sent["whatsapp"]), self.scans), (1, 1, 1))
        self.go(now=datetime(2026, 9, 18, 8, 5))                           # next day sends again
        self.assertEqual(len(self.sent["email"]), 2)

    def test_agent_verdict_shapes_the_messages(self):
        self.verdicts = {"cold-one": Verdict(status="unfinished", left_off="Auth built.", next_step="Wire the scheduler.",
                                             confidence=0.9, evidence=["README.md: - [ ] scheduler"])}
        self.go()
        self.assertEqual(self.wa_params()[2:], ["Auth built.", "Wire the scheduler."])

    def test_probably_done_skips_whatsapp_but_emails_the_hint(self):
        self.verdicts = {"cold-one": Verdict(status="probably_done", left_off="Shipped.", next_step="Nothing.", confidence=0.9)}
        self.assertEqual(self.go(), 0)
        self.assertEqual(len(self.sent["whatsapp"]), 0)
        self.assertEqual(self.day()["whatsapp"]["status"], "nothing")
        self.assertEqual(len(self.sent["email"]), 1)
        self.assertIn("no project needs work today", self.sent["email"][0])
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 10, 0)), 0)
        self.assertEqual(self.scans, 1)

    def test_nothing_cold_marks_day_and_stops_rescanning(self):
        self.projects = [project("warm", 1)]
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.sent, {"email": [], "whatsapp": []})
        self.assertEqual(self.day()["email"]["status"], "nothing")
        self.go(now=datetime(2026, 9, 17, 11, 0))
        self.assertEqual(self.scans, 1)

    def test_nothing_cold_dry_run_writes_no_state(self):
        self.projects = [project("warm", 1)]
        self.assertEqual(self.go(dry_run=True), 0)
        self.assertEqual(remind.load_state(self.tmp)["days"], {})

    def test_hard_failures_retry_then_give_up_and_alert_once(self):
        self.failing["whatsapp"] = notify.DeliveryError("WhatsApp API HTTP 401, code 190: token expired")
        self.assertEqual(self.go(), 1)
        self.assertEqual((self.day()["whatsapp"]["hard_failures"], len(self.sent["email"])), (1, 1))
        self.go(now=datetime(2026, 9, 17, 10, 0))
        self.assertEqual(self.sent["email"][1:], [])                        # no alert before giving up
        self.go(now=datetime(2026, 9, 17, 10, 30))                         # third hard failure -> alert
        self.assertEqual(self.day()["whatsapp"]["hard_failures"], 3)
        self.assertEqual(self.sent["email"][1:], [ALERT_17])
        self.assertTrue(self.day()["whatsapp"]["alerted"])
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 11, 0)), 0)    # given up: quiet, no rescan
        self.assertEqual((len(self.sent["email"]), self.scans), (2, 3))
        self.failing["whatsapp"] = None
        self.go(now=datetime(2026, 9, 17, 12, 0), force=True)              # manual force still works
        self.assertEqual(len(self.sent["whatsapp"]), 1)

    def test_transient_failures_do_not_use_up_the_budget(self):
        self.failing["whatsapp"] = notify.DeliveryError("WhatsApp API unreachable: no network", transient=True)
        for h in (9, 10, 11, 12):
            self.assertEqual(self.go(now=datetime(2026, 9, 17, h, 0)), 1)
        entry = self.day()["whatsapp"]
        self.assertEqual((entry["attempts"], entry.get("hard_failures", 0), entry["status"]), (4, 0, "failed"))
        self.assertEqual(self.sent["email"][1:], [])                        # no give-up, so no alert
        self.failing["whatsapp"] = None
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 13, 0)), 0)
        self.assertEqual((self.day()["whatsapp"]["status"], len(self.sent["whatsapp"])), ("sent", 1))
        self.assertEqual(len(self.sent["email"]), 1)                        # email not resent

    def test_alert_waits_until_email_works(self):
        self.failing["whatsapp"] = notify.DeliveryError("code 190")
        self.failing["email"] = notify.DeliveryError("unreachable", transient=True)
        for h in (9, 10, 11):
            self.go(now=datetime(2026, 9, 17, h, 0))
        self.assertTrue(remind._gave_up(self.day()["whatsapp"]))
        self.assertEqual(self.sent["email"], [])
        self.assertEqual(self.email_attempts, 3)                             # no alert attempts while email is down
        self.failing["email"] = None
        self.go(now=datetime(2026, 9, 17, 12, 0))
        self.assertEqual(self.sent["email"], ["1 project needs you today: cold-one (no work for 6 days) \u00b7 Thu 17 Sep",
                                              ALERT_17])
        self.assertEqual(self.email_attempts, 5)
        self.go(now=datetime(2026, 9, 17, 13, 0))
        self.assertEqual(len(self.sent["email"]), 2)                        # alert not repeated

    def test_scan_failure_exits_3_without_touching_state_or_sending(self):
        self.projects = OSError("external drive not connected")
        self.assertEqual(self.go(), 3)
        self.assertEqual(self.sent, {"email": [], "whatsapp": []})
        self.assertEqual(remind.load_state(self.tmp)["days"], {})
        self.assertTrue(any("Run failed before anything was sent" in line for line in self.output))
        self.projects = [project("warm", 1)]
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 10, 0)), 0)  # next run recovers normally

    def test_unwritable_state_does_not_crash_or_hide_the_sends(self):
        with mock.patch("reminder.remind.save_state", side_effect=PermissionError("locked")):
            with self.assertLogs("reminder", level="ERROR") as logged:
                self.assertEqual(self.go(), 1)
        self.assertEqual((len(self.sent["email"]), len(self.sent["whatsapp"])), (1, 1))
        self.assertTrue(any("Could not write" in line for line in logged.output))

    def test_force_with_nothing_actionable_keeps_a_give_up_record(self):
        self.failing["whatsapp"] = notify.DeliveryError("code 190")
        for h in (9, 10, 11):
            self.go(now=datetime(2026, 9, 17, h, 0))
        self.assertTrue(remind._gave_up(self.day()["whatsapp"]))
        self.failing["whatsapp"] = None
        self.verdicts = {"cold-one": Verdict(status="probably_done", left_off="x", next_step="y")}
        self.go(now=datetime(2026, 9, 17, 12, 0), force=True)
        self.assertTrue(remind._gave_up(self.day()["whatsapp"]))            # not overwritten with "nothing"
        self.assertEqual(self.day()["whatsapp"]["forced"][0]["status"], "nothing")
        self.projects = [project("warm", 1)]                                # and on the nothing-flagged path
        self.go(now=datetime(2026, 9, 17, 13, 0), force=True)
        self.assertTrue(remind._gave_up(self.day()["whatsapp"]))

    def test_featured_memory_is_pruned_on_save(self):
        st = {"days": {"2026-09-17": {}}, "featured": {"old": "2026-01-01", "recent": "2026-09-01", "junk": "nope"}}
        remind.save_state(self.tmp, st)
        self.assertEqual(remind.load_state(self.tmp)["featured"], {"recent": "2026-09-01"})

    def test_unexpected_exception_counts_as_hard_failure_and_email_state_survives(self):
        self.failing["whatsapp"] = KeyError("bug")
        self.assertEqual(self.go(), 1)
        self.assertEqual(self.day()["email"]["status"], "sent")
        self.assertEqual(self.day()["whatsapp"]["hard_failures"], 1)
        self.assertIn("KeyError", self.day()["whatsapp"]["error"])

    def test_force_never_rearms_a_finished_day(self):
        self.go()                                                          # both sent at 09:30
        self.failing["email"] = notify.DeliveryError("smtp down")
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 12, 0), force=True), 1)
        self.assertEqual(self.day()["email"]["status"], "sent")
        self.assertEqual(self.day()["email"]["forced"][0]["status"], "failed")
        self.failing["email"] = None
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 12, 30)), 0)   # scheduled run: nothing pending
        self.assertEqual(len(self.sent["email"]), 1)
        # After a give-up + alert, a failing forced send must not restart the retry budget.
        self.failing["whatsapp"] = notify.DeliveryError("code 190")
        for h in (8, 9, 10):
            self.go(now=datetime(2026, 9, 18, h, 0))
        self.assertEqual(self.sent["email"][-1], ALERT_18)
        n_alerts = self.sent["email"].count(ALERT_18)
        self.go(now=datetime(2026, 9, 18, 11, 0), force=True, only=["whatsapp"])
        for h in (12, 13, 14):
            self.go(now=datetime(2026, 9, 18, h, 0))
        self.assertEqual(self.day("2026-09-18")["whatsapp"]["hard_failures"], 3)
        self.assertEqual(self.sent["email"].count(ALERT_18), n_alerts)

    def test_dry_run_sends_nothing_and_keeps_state_clean(self):
        self.verdicts = {"cold-one": Verdict(status="unfinished", left_off="L", next_step="N", confidence=0.7,
                                             trace=["read_file(path='README.md')"], evidence=["README.md: x"])}
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 6, 0), dry_run=True), 0)
        self.assertEqual(self.sent, {"email": [], "whatsapp": []})
        self.assertEqual(remind.load_state(self.tmp)["days"], {})
        joined = "\n".join(self.output)
        self.assertIn("{{1}} cold-one", joined)
        self.assertIn("*Today's project:* cold-one", joined)                # the formatted message is previewed
        self.assertIn("tool: read_file(path='README.md')", joined)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, ".state", "preview.html")))

    def test_unapproved_template_falls_back_to_the_next_name(self):
        env = dict(ENV_ALL, WA_TEMPLATE_NAME=" new_look , project_checkin,new_look ")
        tried = []

        def picky(token, pnid, payload, version):
            tried.append(payload["template"]["name"])
            if payload["template"]["name"] == "new_look":
                raise notify.DeliveryError("WhatsApp API HTTP 404, code 132001: not in en", code=132001)
            self.sent["whatsapp"].append(payload)
            return "wamid.2"
        self.deps.send_whatsapp = picky
        with self.assertLogs("reminder", level="INFO") as logged:
            self.assertEqual(self.go(env=env), 0)
        self.assertEqual(tried, ["new_look", "project_checkin"])             # duplicates dropped, order kept
        self.assertEqual(self.sent["whatsapp"][0]["template"]["name"], "project_checkin")
        self.assertEqual(self.wa_params()[:2], ["cold-one", "no work for 6 days"])   # same variables
        entry = self.day()["whatsapp"]
        self.assertEqual((entry["status"], entry["ref"], entry.get("hard_failures", 0)), ("sent", "wamid.2", 0))
        self.assertTrue(any("cannot be used yet" in line for line in logged.output))
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 10, 0), env=env), 0)  # still once a day
        self.assertEqual(len(tried), 2)

    def test_fallback_is_only_for_template_problems_and_runs_out(self):
        env = dict(ENV_ALL, WA_TEMPLATE_NAME="new_look,project_checkin")
        tried = []

        def failing(code):
            def send(token, pnid, payload, version):
                tried.append(payload["template"]["name"])
                raise notify.DeliveryError(f"WhatsApp API HTTP 400, code {code}: no", code=code)
            return send
        self.deps.send_whatsapp = failing(190)                             # bad token: another name cannot help
        self.assertEqual(self.go(env=env), 1)
        self.assertEqual(tried, ["new_look"])
        self.assertEqual(self.day()["whatsapp"]["hard_failures"], 1)
        del tried[:]
        self.deps.send_whatsapp = failing(132001)                          # neither template approved
        self.assertEqual(self.go(now=datetime(2026, 9, 17, 10, 0), env=env), 1)
        self.assertEqual(tried, ["new_look", "project_checkin"])
        entry = self.day()["whatsapp"]
        self.assertEqual((entry["hard_failures"], entry["status"]), (2, "failed"))   # one failure per run, not per name
        self.assertIn("132001", entry["error"])

    def test_a_transient_failure_never_moves_on_to_the_next_template(self):
        env = dict(ENV_ALL, WA_TEMPLATE_NAME="new_look,project_checkin")
        tried = []

        def send(token, pnid, payload, version):
            tried.append(payload["template"]["name"])
            raise notify.DeliveryError("WhatsApp API HTTP 500, code 132015: paused", transient=True, code=132015)
        self.deps.send_whatsapp = send
        self.assertEqual(self.go(env=env), 1)
        self.assertEqual(tried, ["new_look"])                              # Meta may have taken the first one
        entry = self.day()["whatsapp"]
        self.assertEqual((entry["status"], entry.get("hard_failures", 0)), ("failed", 0))   # free retry next run

    def test_env_graph_version_is_used_for_every_attempt(self):
        seen = []

        def send(token, pnid, payload, version):
            seen.append(version)
            if payload["template"]["name"] == "a":
                raise notify.DeliveryError("not approved", code=132001)
            return "wamid.1"
        payload = notify.build_whatsapp_template("254700", "a", "en", ["1", "2", "3", "4"])
        deps = Deps(send_whatsapp=send)
        got = remind.send_whatsapp_with_fallback(deps, dict(ENV_ALL, WA_GRAPH_VERSION="v19.0"), payload, ["b"])
        self.assertEqual((got, seen), (("wamid.1", "b", ["a"]), ["v19.0", "v19.0"]))   # the fallback too
        remind.send_whatsapp_with_fallback(deps, dict(ENV_ALL), payload, ["b"])
        self.assertEqual(seen[2:], [notify.DEFAULT_GRAPH_VERSION] * 2)   # unset: the default

    ENV_TWO = dict(ENV_ALL, WA_TEMPLATE_NAME="new_look,project_checkin", WA_BUSINESS_ACCOUNT_ID="waba")

    def refuse_new_look(self, refuse=True):
        def send(token, pnid, payload, version):
            if refuse and payload["template"]["name"] == "new_look":
                raise notify.DeliveryError("WhatsApp API HTTP 404, code 132001: not approved", code=132001)
            self.sent["whatsapp"].append(payload)
            return "wamid.3"
        self.deps.send_whatsapp = send

    def mail_text(self, i=-1):
        return self.mails[i].get_body(("plain",)).get_content()

    def test_a_rejected_template_is_explained_in_the_next_email(self):
        self.refuse_new_look()
        self.template_rows = [{"name": "new_look_old", "language": "en", "status": "APPROVED"},
                              {"name": "new_look", "language": "en", "status": "REJECTED",
                               "rejected_reason": "INVALID_<b>FORMAT"}]
        self.assertEqual(self.go(env=self.ENV_TWO), 0)
        self.assertNotIn("HEADS-UP", self.mail_text())                     # the email was written before the send
        note = remind.load_state(self.tmp)["template_note"]
        self.assertEqual((note["template"], note["used"], note["kind"], note["since"]),
                         ("new_look", "project_checkin", "rejected", "2026-09-17"))
        self.assertEqual(self.status_calls, ["new_look"])
        self.go(now=datetime(2026, 9, 18, 9, 0), env=self.ENV_TWO)         # next day: the owner is told
        text = self.mail_text()
        self.assertIn('On 2026-09-17, the WhatsApp reminder went out in the older layout, "project_checkin", '
                      'because the newer one, "new_look", could not be used: Meta rejected it '
                      '(reason: INVALID_<b>FORMAT).', text)
        html_part = self.mails[-1].get_body(("html",)).get_content()
        self.assertIn("INVALID_&lt;b&gt;FORMAT", html_part)
        self.assertNotIn("INVALID_<b>FORMAT", html_part)
        self.assertLess(text.index("AT A GLANCE"), text.index("HEADS-UP"))
        self.assertLess(text.index("HEADS-UP"), text.index("PROJECTS THAT NEED YOU"))
        note = remind.load_state(self.tmp)["template_note"]
        self.assertEqual((note["since"], note["last"]), ("2026-09-17", "2026-09-18"))   # the first day is kept
        self.refuse_new_look(False)                                        # Meta approves it: the note goes away
        self.go(now=datetime(2026, 9, 19, 9, 0), env=self.ENV_TWO)
        self.assertEqual(self.sent["whatsapp"][-1]["template"]["name"], "new_look")
        self.assertNotIn("template_note", remind.load_state(self.tmp))
        self.go(now=datetime(2026, 9, 20, 9, 0), env=self.ENV_TWO)
        self.assertNotIn("HEADS-UP", self.mail_text())

    def test_a_template_still_in_review_is_only_mentioned_once_it_overruns(self):
        self.refuse_new_look()
        self.template_rows = [{"name": "new_look", "language": "en", "status": "PENDING"}]
        for day in (17, 18):
            self.go(now=datetime(2026, 9, day, 9, 0), env=self.ENV_TWO)
            self.assertNotIn("HEADS-UP", self.mail_text(), day)
        self.go(now=datetime(2026, 9, 19, 9, 0), env=self.ENV_TWO)         # two days in review: say so
        self.assertIn("could not be used: Meta is still reviewing it.", self.mail_text())
        self.assertEqual(len(self.sent["whatsapp"]), 3)                    # and the reminders kept going out

    def test_a_failed_status_lookup_never_costs_the_reminder(self):
        self.refuse_new_look()
        self.template_rows = RuntimeError("graph api down")
        self.assertEqual(self.go(env=self.ENV_TWO), 0)
        self.assertEqual(self.day()["whatsapp"]["status"], "sent")
        note = remind.load_state(self.tmp)["template_note"]
        self.assertEqual(note["kind"], "unknown")
        self.assertIn("graph api down", note["why"])
        env = {k: v for k, v in self.ENV_TWO.items() if k != "WA_BUSINESS_ACCOUNT_ID"}
        self.go(now=datetime(2026, 9, 18, 9, 0), env=env)                  # no account id: no lookup, still sent
        self.assertEqual(self.status_calls, ["new_look"])
        self.assertIn("WA_BUSINESS_ACCOUNT_ID", remind.load_state(self.tmp)["template_note"]["why"])
        with mock.patch("reminder.remind.why_template_unusable", side_effect=KeyError("bug")):
            with self.assertLogs("reminder", level="ERROR"):
                self.assertEqual(self.go(now=datetime(2026, 9, 19, 9, 0), env=self.ENV_TWO), 0)
        self.assertEqual(len(self.sent["whatsapp"]), 3)

    def test_why_template_unusable_tells_the_cases_apart(self):
        env = dict(self.ENV_TWO)
        cases = [([], "missing", "no template with that name"),
                 ([{"name": "new_look", "language": "en_US", "status": "APPROVED"}], "language", "en_US"),
                 ([{"name": "new_look", "language": "en", "status": "APPROVED"}], "mismatch", "approved"),
                 ([{"name": "new_look", "language": "en", "status": "PENDING"}], "reviewing", "still reviewing"),
                 ([{"name": "new_look", "language": "en", "status": "PAUSED"}], "paused", "paused"),
                 ([{"name": "new_look", "language": "en", "status": "DISABLED"}], "disabled", "disabled"),
                 ([{"name": "new_look", "language": "en", "status": "REJECTED", "rejected_reason": "NONE"}],
                  "rejected", "Meta rejected it"),
                 ([{"name": "new_look", "language": "en"}], "unknown", "unknown"),
                 (["junk", {"name": "new_look_2", "language": "en", "status": "APPROVED"}], "missing", "no template")]
        for rows, kind, words in cases:
            self.template_rows = rows
            got = remind.why_template_unusable(self.deps, env, "new_look")
            self.assertEqual(got[0], kind, rows)
            self.assertIn(words, got[1])
        self.template_rows = cases[6][0]
        self.assertNotIn("reason", remind.why_template_unusable(self.deps, env, "new_look")[1])
        self.assertEqual(remind.template_notices({}, NOW.date()), [])
        self.assertEqual(remind.template_notices({"template_note": "junk"}, NOW.date()), [])
        self.assertEqual(remind.template_notices({"template_note": {"template": "t", "kind": "reviewing",
                                                                    "since": "garbage"}}, NOW.date()), [])

    def test_template_names_parsing(self):
        self.assertEqual(remind.template_names({}), ["project_checkin"])
        self.assertEqual(remind.template_names({"WA_TEMPLATE_NAME": " , "}), ["project_checkin"])
        self.assertEqual(remind.template_names({"WA_TEMPLATE_NAME": "a, b ,a"}), ["a", "b"])

    def test_no_llm_uses_fallback_wording(self):
        self.verdicts = {"cold-one": Verdict(status="unfinished", left_off="agent", next_step="agent")}
        self.go(use_llm=False)
        self.assertTrue(self.wa_params()[3].startswith("Open main.py"))

    def test_only_configured_channels_are_used(self):
        email_only = {k: v for k, v in ENV_ALL.items() if not k.startswith("WA_")}
        self.assertEqual(self.go(env=email_only), 0)
        self.assertEqual((len(self.sent["email"]), len(self.sent["whatsapp"])), (1, 0))
        self.assertEqual(self.go(env={}), 1)                               # nothing configured

    def test_lock_blocks_concurrent_run_and_stale_lock_is_reclaimed(self):
        os.makedirs(os.path.join(self.tmp, ".state"))
        lock = os.path.join(self.tmp, ".state", "remind.lock")
        open(lock, "w").close()
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.sent, {"email": [], "whatsapp": []})
        old = time.time() - remind.LOCK_STALE_SECONDS - 60
        os.utime(lock, (old, old))
        self.assertEqual(self.go(), 0)
        self.assertEqual(len(self.sent["email"]), 1)
        self.assertFalse(os.path.exists(lock))


class WhatsAppSetupTests(unittest.TestCase):
    ENV = {"WA_ACCESS_TOKEN": "tok", "WA_BUSINESS_ACCOUNT_ID": "waba", "WA_TEMPLATE_NAME": "v2,project_checkin",
           "WA_TEMPLATE_LANG": "en"}

    def run_setup(self, env=None, **flags):
        args = mock.MagicMock(whatsapp_hello=False, whatsapp_create_template=False, whatsapp_template_status=False)
        for k, v in flags.items():
            setattr(args, k, v)
        lines = []
        return remind.whatsapp_setup(dict(self.ENV if env is None else env), args, lines.append), lines

    def test_create_submits_the_first_name_only(self):
        with mock.patch("reminder.notify.create_template", return_value={"status": "PENDING", "category": "UTILITY"}) as m:
            code, lines = self.run_setup(whatsapp_create_template=True)
        self.assertEqual(code, 0)
        self.assertEqual(m.call_args[0][:4], ("tok", "waba", "v2", "en"))
        self.assertIn("Submitted template 'v2'", lines[0])
        self.assertEqual(len(lines), 1)                                    # UTILITY: nothing to warn about

    def test_create_warns_when_meta_files_it_as_marketing(self):
        with mock.patch("reminder.notify.create_template", return_value={"status": "APPROVED", "category": "MARKETING"}):
            code, lines = self.run_setup(whatsapp_create_template=True)
        self.assertEqual(code, 0)
        self.assertIn("category MARKETING", lines[0])
        self.assertIn("Careful: Meta filed it as MARKETING, not UTILITY", lines[1])
        self.assertIn("Do not put this name in WA_TEMPLATE_NAME", lines[1])

    def test_status_lists_every_name_with_exact_matches_and_says_which_is_live(self):
        def status(token, waba, name, version):
            rows = [{"name": "project_checkin", "language": "en", "status": "APPROVED", "category": "UTILITY"},
                    {"name": "project_checkin_old", "language": "en", "status": "APPROVED", "category": "UTILITY"}]
            return rows if name == "project_checkin" else \
                [{"name": "v2", "language": "en", "status": "PENDING", "category": "UTILITY"}]
        with mock.patch("reminder.notify.template_status", side_effect=status):
            code, lines = self.run_setup(whatsapp_template_status=True)
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["v2 (en): PENDING, category UTILITY", "project_checkin (en): APPROVED, category UTILITY",
                                 "Reminders will go out with: project_checkin (order tried: v2, project_checkin)"])

    def test_status_with_one_name_stays_as_before_and_reports_missing(self):
        env = dict(self.ENV, WA_TEMPLATE_NAME="gone")
        with mock.patch("reminder.notify.template_status", return_value=[]):
            code, lines = self.run_setup(env=env, whatsapp_template_status=True)
        self.assertEqual((code, lines), (0, ["No template named 'gone' found. Run --whatsapp-create-template first."]))

    def test_missing_settings_and_api_errors_are_reported_not_raised(self):
        code, lines = self.run_setup(env={"WA_ACCESS_TOKEN": "tok"}, whatsapp_template_status=True)
        self.assertEqual((code, lines), (2, ["Missing in .env: WA_BUSINESS_ACCOUNT_ID"]))
        with mock.patch("reminder.notify.template_status", side_effect=notify.DeliveryError("code 190: expired")):
            code, lines = self.run_setup(whatsapp_template_status=True)
        self.assertEqual((code, lines), (1, ["WhatsApp setup call failed: code 190: expired"]))


class ConsoleOutputTests(unittest.TestCase):
    def test_dry_run_preview_prints_on_a_legacy_windows_console(self):
        """The WhatsApp preview has emoji; main() must widen stdout to UTF-8 before anything is
        printed, or --dry-run dies on a cp1252 console (the default in cmd.exe on this laptop)."""
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")

        def fake_run(base_dir, now, env, **kw):
            kw["out"](notify.render_template_preview(["a", "b", "c", "d"]))
            return 0
        with mock.patch.object(sys, "stdout", stream), \
                mock.patch("reminder.remind.setup_logging"), \
                mock.patch("reminder.remind.load_env", return_value={}), \
                mock.patch("reminder.remind.run", side_effect=fake_run):
            self.assertEqual(remind.main(["--dry-run", "--no-llm"]), 0)   # 3 would mean it crashed
        self.assertEqual(stream.encoding, "utf-8")


if __name__ == "__main__":
    unittest.main()
