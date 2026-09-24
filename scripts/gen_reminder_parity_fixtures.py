"""Generate the reminder parity fixtures (REQ-REM-00) from the unchanged local companion.

Run from the repo root with the legacy venv (Python 3.13, the companion's dependencies):

    .venv\\Scripts\\python.exe scripts/gen_reminder_parity_fixtures.py          # (re)write the fixtures
    .venv\\Scripts\\python.exe scripts/gen_reminder_parity_fixtures.py --check  # exit 1 if they drifted

It imports reminder.remind and reminder.scan (read only), feeds them a fixed spread of inputs and writes inputs and
outputs to backend/tests/fixtures/reminder_parity/<kind>_<case>.json (sorted keys, LF endings):

* scenario: classify, pick_featured, fallback_text, actionable and compose_email over one set of projects;
* record:   a sequence of _record calls (delivery outcomes), with _finished/_gave_up after each call;
* pending:  the once-a-day decision, taken from reminder.remind.run itself with the LangGraph workflow faked;
* notices:  template_notices for one state.

backend/tests/unit/reminders/test_parity.py checks the backend port (bridge.reminders) against these files without
importing reminder/; scripts/test_reminder_parity_fixtures.py fails when the committed files no longer match what
reminder/ produces, so a change on either side is caught. Nothing here sends anything or reads a real .env.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import sys
import tempfile
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "backend" / "tests" / "fixtures" / "reminder_parity"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reminder import remind  # noqa: E402  (needs ROOT on sys.path)
from reminder.scan import DAY, GitState, Project  # noqa: E402

EAT = timezone(timedelta(hours=3))
NOW_DT = datetime(2026, 9, 21, 9, 15, tzinfo=EAT)  # Monday 21 September 2026, 09:15 in Nairobi
NOW = NOW_DT.timestamp()  # epoch seconds: the same on every machine, whatever its time zone
TODAY = date(2026, 9, 21)
CONFIG_FIELDS = ("path", "cold_after_days", "at_risk_after_days", "send_after_hour", "done", "snooze")
FAKE_ENV = {  # makes both channels "configured" for run(); nothing is ever sent (the workflow is faked)
    "GMAIL_ADDRESS": "owner@example.com",
    "GMAIL_APP_PASSWORD": "fixture-only",
    "WA_ACCESS_TOKEN": "fixture-only",
    "WA_PHONE_NUMBER_ID": "100000000000000",
    "WA_TO": "254700000000",
    "WA_TEMPLATE_NAME": "project_checkin",
}


# --------------------------------------------------------------------------- input builders

def ago(days: float) -> float:
    return NOW - days * DAY


def git(*, last_commit: float | None = None, commits: tuple[str, ...] = (), modified: list[str] | None = None,
        modified_days: float | None = None, unpushed: int | None = None) -> GitState:
    return GitState(
        branch="main", has_remote=unpushed is not None, unpushed=unpushed,
        last_commit=0.0 if last_commit is None else ago(last_commit), recent_commits=list(commits),
        modified=modified, modified_partial=False, modified_newest=0.0 if modified_days is None else ago(modified_days),
    )


def project(name: str, idle: int, *, g: GitState | None = None, recent: tuple[str, ...] = (), title: str = "",
            todos: tuple[str, ...] = (), open_todos: int | None = None, path: str | None = None) -> Project:
    never = idle >= 10**6
    return Project(
        name=name, path=path or f"/home/dev/projects/{name}", last_work=0.0 if never else ago(idle + 0.25),
        idle_days=idle, files=len(recent) + 7, truncated=False, recent_files=list(recent), readme_title=title,
        open_todos=len(todos) if open_todos is None else open_todos, todo_samples=list(todos), git=g,
    )


def config(**kw: Any) -> remind.Config:
    kw.setdefault("path", "/home/dev/second-brain/reminders.json")
    return remind.Config(projects_roots=["/home/dev/projects"], **kw)


def verdict(status: str, left_off: str, next_step: str, confidence: float = 0.0, evidence: tuple[str, ...] = (),
            source: str = "agent", trace: tuple[str, ...] = ()) -> remind.Verdict:
    return remind.Verdict(status=status, left_off=left_off, next_step=next_step, confidence=confidence,
                          evidence=list(evidence), trace=list(trace), source=source)


# --------------------------------------------------------------------------- encoders

def enc_config(cfg: remind.Config) -> dict[str, Any]:
    return {name: getattr(cfg, name) for name in CONFIG_FIELDS}


def enc_flagged(f: remind.Flagged) -> dict[str, Any]:
    return {"name": f.name, "cold": f.cold, "risks": list(f.risks), "headline": f.headline()}


# --------------------------------------------------------------------------- the four kinds

def scenario(case: str, description: str, projects: list[Project], *, cfg: remind.Config | None = None,
             verdicts: dict[str, remind.Verdict] | None = None, skipped: tuple[tuple[str, str], ...] = (),
             notices: tuple[str, ...] = (), featured_log: dict[str, str] | None = None) -> dict[str, Any]:
    cfg = cfg or config()
    verdicts = verdicts or {}
    featured_log = featured_log or {}
    flagged, quiet, held = remind.classify(projects, cfg, NOW, TODAY)
    featured = remind.pick_featured(flagged, featured_log)
    subject, text, body_html = remind.compose_email(flagged, quiet, held, list(skipped), verdicts, cfg, TODAY, NOW,
                                                    notices)
    return {
        "kind": "scenario", "case": case, "description": description,
        "input": {
            "projects": [dataclasses.asdict(p) for p in projects], "config": enc_config(cfg), "now": NOW,
            "today": TODAY.isoformat(), "verdicts": {n: dataclasses.asdict(v) for n, v in verdicts.items()},
            "skipped": [list(s) for s in skipped], "notices": list(notices), "featured_log": featured_log,
        },
        "expected": {
            "classify": {"flagged": [enc_flagged(f) for f in flagged], "quiet": [p.name for p in quiet],
                         "held": [[p.name, why] for p, why in held]},
            "featured": featured.name if featured else None,
            "fallback": {f.name: dataclasses.asdict(remind.fallback_text(f)) for f in flagged},
            "actionable": [f.name for f in remind.actionable(flagged, verdicts)],
            "email": {"subject": subject, "text": text, "html": body_html},
        },
    }


def record(case: str, description: str, day: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    state = copy.deepcopy(day)
    steps = []
    for call in calls:
        remind._record(state, call["channel"], call["ok"], datetime.fromisoformat(call["now"]), call["detail"],
                       call["transient"], call["force"], call["status"])
        steps.append({"day": copy.deepcopy(state),
                      "finished": {c: remind._finished(state.get(c)) for c in remind.CHANNELS},
                      "gave_up": {c: remind._gave_up(state.get(c)) for c in remind.CHANNELS}})
    return {"kind": "record", "case": case, "description": description,
            "input": {"day": day, "calls": calls}, "expected": {"steps": steps}}


def call(channel: str, ok: bool, now: str, detail: str, *, transient: bool = False, force: bool = False,
         status: str = "sent") -> dict[str, Any]:
    return {"channel": channel, "ok": ok, "now": now, "detail": detail, "transient": transient, "force": force,
            "status": status}


def legacy_pending(day: dict[str, Any], channels: list[str], now: datetime, send_after_hour: int, force: bool,
                   dry_run: bool) -> list[str]:
    """The channels reminder.remind.run would work on: run() itself, in a scratch base dir, with the LangGraph
    workflow replaced by a recorder (it is only reached once the guard lets at least one channel through)."""
    seen: list[list[str]] = []

    class Recorder:
        def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
            seen.append(list(inputs["pending"]))
            return {"exit_code": 0}

    fake_graph = types.ModuleType("reminder.graph")
    fake_graph.build_workflow = lambda *args: Recorder()  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "projects").mkdir()
        (base / ".state").mkdir()
        (base / "reminders.json").write_text(json.dumps({"projects_roots": [str(base / "projects")],
                                                         "send_after_hour": send_after_hour}), encoding="utf-8")
        (base / ".state" / "state.json").write_text(json.dumps({"days": {now.date().isoformat(): day}}),
                                                    encoding="utf-8")
        with mock.patch.dict(sys.modules, {"reminder.graph": fake_graph}):
            code = remind.run(str(base), now, dict(FAKE_ENV), force=force, dry_run=dry_run, only=list(channels))
    if code != 0:
        raise RuntimeError(f"reminder.remind.run exited {code}")
    return seen[0] if seen else []


def pending(case: str, description: str, day: dict[str, Any], channels: list[str], now: str, send_after_hour: int,
            *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    result = legacy_pending(day, channels, datetime.fromisoformat(now), send_after_hour, force, dry_run)
    return {"kind": "pending", "case": case, "description": description,
            "input": {"day": day, "channels": channels, "now": now, "send_after_hour": send_after_hour,
                      "force": force, "dry_run": dry_run},
            "expected": {"pending": result}}


def notices(case: str, description: str, state: dict[str, Any], today: date = TODAY) -> dict[str, Any]:
    return {"kind": "notices", "case": case, "description": description,
            "input": {"state": state, "today": today.isoformat()},
            "expected": {"lines": remind.template_notices(copy.deepcopy(state), today)}}


# --------------------------------------------------------------------------- the cases

def scenarios() -> list[dict[str, Any]]:
    out = [
        scenario("empty_root", "No projects and nothing skipped.", []),
        scenario("all_quiet", "Three recently worked-on projects (today, yesterday, 2 days): nothing flagged.", [
            project("alpha", 0, g=git(last_commit=0.1, commits=("Add login form",)), recent=("app.py",)),
            project("beta", 1, recent=("index.html",)),
            project("gamma", 2, g=git(), recent=("main.rs",)),
        ]),
        scenario("one_cold_not_in_git", "One cold folder without git: fallback wording from files and to-dos.", [
            project("field-notes", 5, recent=("notes/2026-09-16.md", "README.md", "draw.py", "x.py"),
                    title="Field notes", todos=("Sketch the **map** layer", "Fix `export`"), open_todos=4),
            project("quiet-one", 0, recent=("a.txt",)),
        ]),
    ]
    out.append(scenario(
        "at_risk_uncommitted_and_unpushed",
        "Work at risk: uncommitted and unpushed, commits today and days ago, singular and plural counts.", [
            project("payments-api", 0, recent=("src/callback.py",), g=git(
                last_commit=3.5, commits=("Wire M-Pesa callback", "Add STK push", "Initial commit"),
                modified=["src/callback.py"], modified_days=4.2, unpushed=1)),
            project("tiny-cli", 4, recent=("cli.py",), g=git(last_commit=4.5, commits=("Parse flags",), unpushed=2)),
            project("web-shop", 0, recent=("a.css",), title="Web shop", g=git(
                last_commit=0.2, commits=("Style the cart",), modified=["a.css", "b.css"], modified_days=3.1,
                unpushed=0)),
        ]))
    out.append(scenario(
        "thresholds_and_sort_order",
        "Risk just under the threshold, modified_newest unknown, unknown index/unpushed, name ties, never worked on,"
        " more than three projects in the subject, and featured rotation skipping recently featured ones.", [
            project("a-risk-young", 0, g=git(last_commit=0.5, modified=["a.py", "b.py"], modified_days=2.9)),
            project("b-risk-lastwork", 5, g=git(last_commit=5.5, modified=["x.py", "y.py", "z.py", "w.py"])),
            project("Echo", 7, recent=("echo.py",)),
            project("delta", 7, recent=("delta.py", "util.py")),
            project("unknown-index", 9, recent=("core.c",), g=git(last_commit=9.5, commits=("Fix the build",),
                                                                  modified=None, unpushed=None)),
            project("unpushed-zero", 1, g=git(last_commit=1.5, unpushed=0)),
            project("never-worked", 10**6),
            project("young-change-cold", 4, todos=("Write tests",), g=git(
                last_commit=6, modified=["m.py", "n.py"], modified_days=1)),
        ],
        featured_log={"b-risk-lastwork": "2026-09-20", "delta": "2026-09-19", "gone-project": "2026-06-01"}))
    out.append(scenario(
        "at_risk_later_than_cold",
        "at_risk_after_days (5) above cold_after_days (3): unpushed work below the risk age is only cold; every"
        " flagged project was featured before, so the oldest date wins.", [
            project("slow-push", 4, recent=("main.go",), g=git(last_commit=4.2, commits=("Refactor",), unpushed=2)),
            project("old-push", 6, g=git(last_commit=6.5, commits=("Ship v1",), unpushed=1)),
        ],
        cfg=config(cold_after_days=3, at_risk_after_days=5),
        featured_log={"slow-push": "2026-09-18", "old-push": "2026-09-20"}))
    out.append(scenario(
        "done_and_snoozed",
        "done matches case-insensitively; an active snooze holds a project; a snooze ending today does not.", [
            project("old-site", 40, recent=("index.php",)),
            project("thesis", 10, recent=("thesis.tex",)),
            project("garden", 8, recent=("plants.csv",)),
            project("blog", 1, recent=("post.md",)),
            project("api", 0, recent=("api.py",)),
        ],
        cfg=config(done=["Old-Site"], snooze={"thesis": "2026-10-05", "garden": "2026-09-21", "Blog": "2026-09-30"})))
    out.append(scenario(
        "agent_mixed_one_quick",
        "Agent verdicts: unfinished, probably_done, not_a_project, one with a blank next step (falls back, quick"
        " check), and a verdict for a project that is not flagged.", [
            project("shop-app", 5, recent=("cart.py", "views.py"), todos=("Cart totals",), g=git(
                last_commit=5.5, commits=("Add cart page",))),
            project("old-scripts", 30, recent=("backup.sh",), g=git(last_commit=31, commits=("Final tweaks",))),
            project("downloads-sorted", 12, recent=("IMG_0001.jpg",)),
            project("notes-app", 6, recent=("notes.py",), g=git(last_commit=6.5, commits=("Save notes",))),
            project("fresh", 0, recent=("fresh.py",)),
        ],
        verdicts={
            "shop-app": verdict("unfinished", "You were adding the cart page.", "Finish the cart total in cart.py.",
                                0.9, ("README says v2 is in progress", "TODO.md has 3 open items")),
            "old-scripts": verdict("probably_done", "The scripts run and the README says done.", "Nothing left.",
                                   0.83, ("README: 'Finished'",)),
            "downloads-sorted": verdict("not_a_project", "Only photos, no code.", "Move the photos.", 0.6,
                                        ("412 .jpg files",)),
            "notes-app": verdict("unfinished", "You were saving notes.", "   "),
            "fresh": verdict("unfinished", "Not flagged, so never shown.", "Nothing."),
        }))
    out.append(scenario(
        "agent_single_project",
        "One flagged project, looked at by the agent: 'the listed project', one small next step, preheader.", [
            project("thesis-tools", 4, recent=("refs.bib",), g=git(last_commit=4.4, commits=("Add bibtex export",))),
        ],
        verdicts={"thesis-tools": verdict("unfinished", "You were exporting references.",
                                          "Run the export on chapter 2.", 0.75, (), trace=("read_file README.md",))}))
    out.append(scenario(
        "agent_all_three",
        "Three flagged projects, all looked at by the agent.", [
            project("one", 3, recent=("one.py",)), project("two", 4, recent=("two.py",)),
            project("three", 5, recent=("three.py",)),
        ],
        verdicts={"one": verdict("unfinished", "Left off one.", "Do one."),
                  "two": verdict("unfinished", "Left off two.", "Do two."),
                  "three": verdict("probably_done", "Three is done.", "-", 1.0)}))
    out.append(scenario(
        "agent_one_of_three",
        "Three flagged projects, one looked at by the agent: 'The other 2 are marked quick check'.", [
            project("uno", 3, recent=("uno.py",)), project("dos", 4, recent=("dos.py",)),
            project("tres", 5, recent=("tres.py",)),
        ],
        verdicts={"dos": verdict("unfinished", "Left off dos.", "Do dos.")}))
    out.append(scenario(
        "nothing_actionable",
        "Every flagged project is probably finished or not a project: 'No project needs work today'.", [
            project("done-thing", 20, recent=("final.py",)),
            project("photos", 9, recent=("a.jpg",)),
            project("active", 1, recent=("active.py",)),
        ],
        verdicts={"done-thing": verdict("probably_done", "All tasks ticked.", "-", 0.95, ("CHANGELOG says 1.0",)),
                  "photos": verdict("not_a_project", "A photo dump.", "-", 0.7)}))
    out.append(scenario(
        "skipped_groups",
        "Skipped folders grouped: ignore list (with 'and 1 more'), hidden, backup copies (plural and singular),"
        " unreadable.", [
            project("soc-agents", 0, recent=("agents.py",)),
            project("app", 6, recent=("app.py",)),
        ],
        skipped=(("node-old", "ignored"), ("tmp", "ignored"), (".cache", "ignored"), ("archive", "ignored"),
                 ("scratch", "ignored"), (".obsidian", "ignored"),
                 ("soc-agents_backup_2026-09-15", "copy of soc-agents"), ("soc-agents-old", "copy of soc-agents"),
                 ("app_bak", "copy of app"), ("broken", "unreadable: PermissionError"))))
    out.append(scenario(
        "escaping_and_marks",
        "HTML-special characters in names, titles, commits and agent text; backticks in a folder name; a Windows"
        " settings path; non-ASCII text.", [
            project("tom & jerry's \"lab\"", 8, title="R&D <notes>", recent=("<b>.txt",)),
            project("odd`name`dir", 15, recent=("x.py",)),
            project("mradi-wa-maji", 5, title="Maji \u2014 caf\u00e9", recent=("ramani.py",), g=git(
                last_commit=5.5, commits=("Fix <script>alert(\"x\")</script> & tidy", "Ongeza ramani \U0001f680"))),
        ],
        cfg=config(path="C:\\Users\\dev\\second-brain\\reminders.json"),
        verdicts={
            "tom & jerry's \"lab\"": verdict("not_a_project", "Only **backups** of photos & a `.zip`", "-", 0.55,
                                             ("<img src=x onerror=alert(1)>",)),
            "odd`name`dir": verdict("probably_done", "Finished <for real>.", "-", 0.7),
            "mradi-wa-maji": verdict("unfinished", "Umebakiza ramani & \"legend\".",
                                     "Run `make test` then **commit**.", 0.8),
        }))
    note_state = {"template_note": {"template": "project_checkin_v2", "used": "project_checkin", "kind": "rejected",
                                    "why": "Meta rejected it (reason: INVALID_FORMAT)", "since": "2026-09-19",
                                    "last": "2026-09-20"}}
    out.append(scenario(
        "notices_and_long_lists",
        "One-day thresholds (singular wording), a heads-up from template_notices, more than 8 changed files,"
        " three commits, to-dos and recent files, never-worked project.", [
            project("big-refactor", 1, title="Big refactor", g=git(
                last_commit=1.2, commits=("Split models", "Move views", "Rename app"),
                modified=[f"pkg/mod{i}.py" for i in range(11)], modified_days=1.5, unpushed=0),
                recent=("pkg/mod0.py", "pkg/mod1.py", "pkg/mod2.py", "pkg/mod3.py", "pkg/mod4.py"),
                todos=("Update imports", "Fix tests", "Write the changelog"), open_todos=5),
            project("fresh", 0, recent=("fresh.py",)),
            project("never-touched", 10**6),
        ],
        cfg=config(cold_after_days=1, at_risk_after_days=1),
        notices=tuple(remind.template_notices(note_state, TODAY)),
        verdicts={"big-refactor": verdict("unfinished", "Halfway through moving views.", "Commit the moved views.",
                                          0.66, ("git status shows 11 changed files",))}))
    out.append(scenario(
        "featured_ties_follow_order",
        "Every flagged project was featured on the same day: the first in list order wins.", [
            project("kilo", 4, recent=("k.py",)), project("lima", 4, recent=("l.py",)),
            project("mike", 3, recent=("m.py",)),
        ],
        featured_log={"kilo": "2026-09-20", "lima": "2026-09-20", "mike": "2026-09-20"}))
    return out


T = "2026-09-21T09:15:00"
T2 = "2026-09-21T10:15:00"
T3 = "2026-09-21T11:15:00"
T4 = "2026-09-21T12:15:00"
SENT_EMAIL = {"attempts": 1, "at": "2026-09-21T08:00:00", "status": "sent", "ref": "owner@example.com"}
GAVE_UP_WA = {"attempts": 3, "at": "2026-09-21T08:30:00", "status": "failed", "error": "Meta error (code 131030)",
              "hard_failures": 3}


def records() -> list[dict[str, Any]]:
    return [
        record("first_send_ok", "First successful email of the day.", {},
               [call("email", True, T, "owner@example.com")]),
        record("transient_then_ok", "A transient failure does not use the retry budget; success clears the error.",
               {}, [call("whatsapp", False, T, "No network (timed out)", transient=True),
                    call("whatsapp", True, T2, "wamid.HBgM")]),
        record("three_hard_failures_give_up", "Three hard failures reach MAX_ATTEMPTS: the channel gives up.", {},
               [call("whatsapp", False, T, "Meta error (code 131030)"),
                call("whatsapp", False, T2, "Meta error (code 131030)"),
                call("whatsapp", False, T3, "Meta error (code 131030)")]),
        record("hard_transient_mix", "Hard, transient, hard, hard: only hard failures count towards giving up.", {},
               [call("email", False, T, "SMTP auth failed"),
                call("email", False, T2, "Connection reset", transient=True),
                call("email", False, T3, "SMTP auth failed"),
                call("email", False, T4, "SMTP auth failed")]),
        record("forced_after_sent", "A forced run never rewrites a finished entry; it is logged under 'forced'.",
               {"email": dict(SENT_EMAIL)},
               [call("email", True, T, "owner@example.com", force=True),
                call("email", False, T2, "SMTP timeout", transient=True, force=True)]),
        record("forced_after_give_up", "A forced failure after giving up does not touch the give-up.",
               {"whatsapp": dict(GAVE_UP_WA)},
               [call("whatsapp", False, T, "Meta error (code 131030)", force=True),
                call("whatsapp", True, T2, "wamid.FORCED", force=True)]),
        record("forced_on_unfinished", "A forced run on an unfinished entry records a normal attempt.",
               {"whatsapp": {"attempts": 1, "at": "2026-09-21T08:00:00", "status": "failed", "error": "x",
                             "hard_failures": 1}},
               [call("whatsapp", True, T, "wamid.OK", force=True)]),
        record("nothing_to_send", "'nothing' is a finished status too; forcing again logs it under 'forced'.", {},
               [call("whatsapp", True, T, "nothing actionable", status="nothing"),
                call("whatsapp", True, T2, "nothing actionable", force=True, status="nothing")]),
        record("aware_timestamp", "A timezone-aware 'now' keeps its offset in the stamp.", {},
               [call("email", True, "2026-09-21T09:15:42.123456+03:00", "owner@example.com")]),
        record("failure_after_success_keeps_ref", "A failure after a success keeps the ref; the next success drops"
               " the error.", {"email": dict(SENT_EMAIL)},
               [call("email", False, T, "SMTP timeout"), call("email", True, T2, "owner@example.com")]),
        record("two_channels_independent", "Each channel keeps its own entry.", {},
               [call("email", True, T, "owner@example.com"), call("whatsapp", False, T, "Meta error (code 190)")]),
    ]


BOTH = ["email", "whatsapp"]


def pendings() -> list[dict[str, Any]]:
    return [
        pending("before_send_hour", "Before send_after_hour nothing is pending.", {}, BOTH, "2026-09-21T07:59:00", 8),
        pending("at_send_hour", "At send_after_hour both unfinished channels are pending.", {}, BOTH,
                "2026-09-21T08:00:00", 8),
        pending("whatsapp_failed_email_sent", "A sent channel is done for the day; a failed one is retried.",
                {"email": dict(SENT_EMAIL), "whatsapp": {"attempts": 1, "status": "failed", "error": "x",
                                                         "hard_failures": 1, "at": "2026-09-21T08:00:00"}},
                BOTH, "2026-09-21T09:00:00", 8),
        pending("all_finished_including_give_up", "Sent and given-up channels are both finished: nothing pending.",
                {"email": dict(SENT_EMAIL), "whatsapp": dict(GAVE_UP_WA)}, BOTH, "2026-09-21T10:00:00", 8),
        pending("nothing_counts_as_finished", "'nothing' finishes WhatsApp; a transient email failure is retried.",
                {"email": {"attempts": 1, "status": "failed", "error": "timeout", "at": "2026-09-21T08:00:00"},
                 "whatsapp": {"attempts": 1, "status": "nothing", "ref": "nothing actionable",
                              "at": "2026-09-21T08:00:00"}},
                BOTH, "2026-09-21T08:15:00", 8),
        pending("force_ignores_guard", "--force: every channel, before the hour and although all are finished.",
                {"email": dict(SENT_EMAIL), "whatsapp": dict(GAVE_UP_WA)}, BOTH, "2026-09-21T06:00:00", 8,
                force=True),
        pending("dry_run_ignores_guard", "--dry-run: every channel, whatever the hour.", {}, BOTH,
                "2026-09-21T05:00:00", 8, dry_run=True),
        pending("only_email_already_sent", "Limited to email, which is already sent: nothing pending.",
                {"email": dict(SENT_EMAIL)}, ["email"], "2026-09-21T09:00:00", 8),
        pending("midnight_send_hour", "send_after_hour 0: pending from midnight.", {}, BOTH, "2026-09-21T00:05:00",
                0),
        pending("late_send_hour", "send_after_hour 23: nothing at 22:30.", {}, ["whatsapp"], "2026-09-21T22:30:00",
                23),
    ]


def _note(**kw: Any) -> dict[str, Any]:
    base = {"template": "project_checkin_v2", "used": "project_checkin", "kind": "reviewing",
            "why": "Meta is still reviewing it", "since": "2026-09-21", "last": "2026-09-21"}
    base.update(kw)
    return {"template_note": {k: v for k, v in base.items() if v is not None}}


def notice_cases() -> list[dict[str, Any]]:
    return [
        notices("no_note", "No template note: no heads-up.", {"days": {}, "featured": {}}),
        notices("note_not_a_dict", "A malformed note is ignored.", {"template_note": "oops"}),
        notices("note_without_template", "A note without a template name is ignored.",
                {"template_note": {"used": "project_checkin", "kind": "rejected"}}),
        notices("reviewing_same_day", "Still in review since today: not news yet.", _note()),
        notices("reviewing_one_day", "Still in review for one day: not news yet.", _note(since="2026-09-20")),
        notices("reviewing_overran", "In review for REVIEW_GRACE_DAYS (2) days: now it is news.",
                _note(since="2026-09-19", last="2026-09-20")),
        notices("rejected_today", "Anything but 'reviewing' is news at once.",
                _note(kind="rejected", why="Meta rejected it (reason: INVALID_FORMAT)")),
        notices("bad_since_date", "An unreadable 'since' counts as today; kind 'missing' is still reported.",
                _note(kind="missing", why="no template with that name exists in your WhatsApp account",
                      since="not-a-date", last="2026-09-20")),
        notices("reviewing_bad_since", "An unreadable 'since' on a template in review is not news.",
                _note(since="21/09/2026")),
        notices("no_last_uses_since", "Without 'last' the line reports 'since'.",
                _note(kind="paused", why="Meta has paused it because people rated it poorly", since="2026-09-10",
                      last=None)),
        notices("used_missing", "A note without 'used' prints None, as the companion does.",
                _note(kind="language", used=None, why="it exists in the language en_US, but WA_TEMPLATE_LANG in"
                                                      " .env says en")),
    ]


# --------------------------------------------------------------------------- output

def build() -> dict[str, str]:
    """{file name: JSON text} for every fixture, generated in memory from reminder/."""
    files: dict[str, str] = {}
    for fixture in [*scenarios(), *records(), *pendings(), *notice_cases()]:
        name = f"{fixture['kind']}_{fixture['case']}.json"
        if name in files:
            raise ValueError(f"duplicate fixture {name}")
        files[name] = json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return files


def drift(fresh: dict[str, str], directory: Path = FIXTURE_DIR) -> list[str]:
    """Names of fixtures that differ between `fresh` and the files in `directory` (missing, extra or changed)."""
    committed = {p.name: p.read_text(encoding="utf-8") for p in directory.glob("*.json")}  # CRLF read as LF
    return sorted(n for n in set(fresh) | set(committed) if fresh.get(n) != committed.get(n))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed fixtures differ from reminder/")
    args = ap.parse_args(argv)
    fresh = build()
    if args.check:
        changed = drift(fresh)
        for name in changed:
            print(f"drifted: {name}")
        return 1 if changed else 0
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in FIXTURE_DIR.glob("*.json"):
        if stale.name not in fresh:
            stale.unlink()
    for name, text in fresh.items():
        with open(FIXTURE_DIR / name, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    print(f"wrote {len(fresh)} fixtures to {FIXTURE_DIR.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
