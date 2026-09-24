"""Backend-only guarantees of the ported reminder email (REQ-REM-00); behaviour parity is in test_parity.py."""

from __future__ import annotations

from datetime import date, datetime

from markupsafe import Markup

from bridge.reminders import compose
from bridge.reminders.compose import EmailParts, compose_email, marks_html
from bridge.reminders.policy import (
    DAY,
    Flagged,
    GitState,
    Project,
    ReminderConfig,
    Verdict,
    pending_channels,
    record,
)

NOW = 1_790_000_000.0
TODAY = date(2026, 9, 21)
HOSTILE = '<img src=x onerror="alert(1)">'


def _project(name: str) -> Project:
    git = GitState(
        branch="main",
        has_remote=True,
        unpushed=1,
        last_commit=NOW - 5 * DAY,
        recent_commits=[f"commit {HOSTILE}"],
        modified=[f"{HOSTILE}.py"],
        modified_partial=False,
        modified_newest=NOW - 5 * DAY,
    )
    return Project(
        name=name,
        path=f"/srv/{HOSTILE}",
        last_work=NOW - 5 * DAY,
        idle_days=5,
        files=3,
        truncated=False,
        recent_files=[HOSTILE],
        readme_title=HOSTILE,
        open_todos=1,
        todo_samples=[f"**{HOSTILE}**"],
        git=git,
    )


def test_marks_html_escapes_before_adding_its_own_tags() -> None:
    out = marks_html("**<i>x</i>** and `a & b`")
    assert isinstance(out, Markup)
    assert out.startswith("<b>&lt;i&gt;x&lt;/i&gt;</b> and <code style=")
    assert out.endswith(">a &amp; b</code>")


def test_text_from_projects_and_agents_is_escaped_everywhere() -> None:
    flagged = [Flagged(_project(f"dir {HOSTILE}"), cold=True, risks=[f"{HOSTILE} not committed"])]
    verdicts = {
        f"dir {HOSTILE}": Verdict(
            status="not_a_project", left_off=HOSTILE, next_step=HOSTILE, confidence=0.5, evidence=[HOSTILE]
        )
    }
    cfg = ReminderConfig(path=f"/home/{HOSTILE}/reminders.json")
    parts = compose_email(flagged, [], [], [(HOSTILE, "ignored")], verdicts, cfg, TODAY, NOW, [f"**{HOSTILE}**"])
    assert isinstance(parts, EmailParts)
    assert "<img" not in parts.html
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in parts.html
    assert HOSTILE in parts.text  # the plain-text part is never HTML-escaped
    assert parts.html.startswith('<!doctype html><html lang="en"><head>')
    assert parts.html.endswith("</ul></div></body></html>")


def test_the_template_loads_with_autoescape_and_strict_undefined() -> None:
    env = compose._ENV
    assert env.autoescape is True
    template = env.get_template(compose.TEMPLATE)
    assert "\n" not in template.render(
        preheader="p",
        date_line="d",
        lead="l",
        tip="t",
        helper="h",
        counts=[("Need you", 0)],
        notices=[],
        sections=[],
        other=[],
        other_blurb="o",
        how=[],
    )


def test_line_breaks_are_dropped_for_lf_and_crlf_checkouts() -> None:
    joiner = compose._JoinLines(compose._ENV)
    assert joiner.preprocess("<a>\n  <b>x</b> \r\n\t<c>", "t.j2") == "<a><b>x</b><c>"
    assert joiner.preprocess("<b>{{ x }}:</b> <span>", None) == "<b>{{ x }}:</b> <span>"


def test_record_flags_are_keyword_only_and_return_a_new_day() -> None:
    day: dict[str, dict[str, object]] = {}
    new = record(day, "email", ok=True, now=datetime(2026, 9, 21, 9, 0), detail="x", transient=False, force=False)  # noqa: DTZ001 - the companion stamps local wall-clock time
    assert day == {}
    assert new == {"email": {"attempts": 1, "at": "2026-09-21T09:00:00", "status": "sent", "ref": "x"}}


def test_pending_channels_returns_a_fresh_list() -> None:
    channels = ["email", "whatsapp"]
    result = pending_channels({}, channels, datetime(2026, 9, 21, 6, 0), 8, force=True)  # noqa: DTZ001 - local hour
    assert result == channels
    assert result is not channels
