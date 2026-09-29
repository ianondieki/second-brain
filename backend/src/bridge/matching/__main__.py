"""Run the scouts now: ``python -m bridge.matching run [--now] [--proposal ID]`` (dev and test only).

The demo's trigger (``make demo-scouts``; PLAN.md §8 P10): one pass of ``scouts.scan`` at the shared clock's time
(``app_clock_now()``), exactly as the worker's job runs it, through the configured email provider (Mailpit in dev)
and LLM runtime. ``--now`` also skips the 07:00 EAT start; a scout still runs at most once per Nairobi day or ISO
week (``app_scouts_due``). ``--proposal`` runs the on_new scouts for that publication instead. Any ``APP_ENV`` but
dev or test refuses it. Runs as ``bridge_app`` (``DATABASE_URL``). Prints one line per scout: scout, organisation,
status, proposals read, matches, digest recipients.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from uuid import UUID

from bridge.config import Settings, get_settings
from bridge.matching.runtime import ScoutRuntime
from bridge.matching.scan import Outcome, run_on_new, run_periodic

ALLOWED_ENVS = ("dev", "test")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="python -m bridge.matching", description="Run the scouts now (dev and test).")
    commands = cli.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="one pass of scouts.scan (or scouts.on_new for --proposal)")
    run.add_argument("--now", action="store_true", help="skip the 07:00 EAT start time")
    run.add_argument("--proposal", type=UUID, help="run the on_new scouts for this published proposal")
    return cli


def line(outcome: Outcome) -> str:
    recipients = len(outcome.digest.recipients) if outcome.digest is not None else 0
    reason = f" ({outcome.reason})" if outcome.reason else ""
    return (
        f"{outcome.scout_id} {outcome.org_id} {outcome.status}{reason} read={outcome.scanned}"
        f" matched={outcome.matched} digest_recipients={recipients}"
    )


async def run(runtime: ScoutRuntime, *, force: bool, proposal: UUID | None) -> list[str]:
    deps = runtime.deps()
    try:
        if proposal is not None:
            outcomes = await run_on_new(deps, proposal)
        else:
            outcomes = await run_periodic(deps, force=force)
    finally:
        await runtime.aclose()
    if not outcomes:
        return ["scouts: nothing due (before 07:00 EAT without --now, or every scout already ran this period)"]
    return [line(o) for o in outcomes]


def main(
    argv: Sequence[str] | None = None, *, settings: Settings | None = None, runtime: ScoutRuntime | None = None
) -> int:
    args = parser().parse_args(argv)
    config = settings or get_settings()
    if config.app_env not in ALLOWED_ENVS:
        print(f"python -m bridge.matching is for dev and test: APP_ENV={config.app_env} refuses it.", file=sys.stderr)
        return 2
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    work = run(runtime or ScoutRuntime(config), force=args.now, proposal=args.proposal)
    for text in asyncio.run(work, loop_factory=loop_factory):
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
