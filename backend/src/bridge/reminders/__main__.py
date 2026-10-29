"""Run the reminders now: ``python -m bridge.reminders run [--now] [--only developers|organisations] [--user ID]``.

The dev/test trigger of PLAN.md §8 P6 (until P5's test-clock router offers one): one pass of ``reminders.dispatch``
and ``reminders.org_digest`` at the shared clock's time (``app_clock_now()``), exactly as the worker's jobs run them,
through the configured email provider (Mailpit in dev) and LLM runtime. ``--now`` also skips the 07:30 and 08:30 EAT
start times; it never sends anyone a second reminder for the same period, and ``APP_ENV=production`` refuses it.
``--user`` limits the pass to those users (repeatable). Runs as ``bridge_app`` (``DATABASE_URL``). Prints one line
per recipient: user, organisation, status, email status.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from uuid import UUID

from bridge.config import Settings, get_settings
from bridge.reminders.dispatch import ReminderRuntime, Report, run_developer_nudges, run_org_digests


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="python -m bridge.reminders", description="Run the daily reminders now.")
    commands = cli.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="one pass of reminders.dispatch and reminders.org_digest")
    run.add_argument("--now", action="store_true", help="skip the 07:30/08:30 EAT start times (not in production)")
    run.add_argument("--only", choices=("developers", "organisations"), help="run one of the two passes")
    run.add_argument("--user", action="append", type=UUID, dest="users", help="only this user (repeatable)")
    return cli


def _lines(name: str, report: Report) -> list[str]:
    if not report.ran:
        return [f"{name}: not yet ({report.now.isoformat()}; use --now to run before the start time)"]
    lines = [f"{name}: {report.today.isoformat()}, {len(report.outcomes)} recipient(s)"]
    for o in report.outcomes:
        email = o.email.value if o.email is not None else (o.email_skipped or "-")
        lines.append(f"  {o.user_id} {o.org_id or '-'} {o.status} email={email}")
    return lines


async def run(runtime: ReminderRuntime, *, force: bool, only: str | None, users: Sequence[UUID] | None) -> list[str]:
    deps = runtime.deps()
    lines: list[str] = []
    try:
        if only in (None, "developers"):
            lines += _lines("developers", await run_developer_nudges(deps, force=force, user_ids=users))
        if only in (None, "organisations"):
            lines += _lines("organisations", await run_org_digests(deps, force=force, user_ids=users))
    finally:
        await runtime.aclose()
    return lines


def main(
    argv: Sequence[str] | None = None, *, settings: Settings | None = None, runtime: ReminderRuntime | None = None
) -> int:
    args = parser().parse_args(argv)
    config = settings or get_settings()
    if args.now and config.app_env == "production":
        print("run --now is for dev, test and staging: APP_ENV=production refuses it.", file=sys.stderr)
        return 2
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    work = run(runtime or ReminderRuntime(config), force=args.now, only=args.only, users=args.users)
    for line in asyncio.run(work, loop_factory=loop_factory):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
