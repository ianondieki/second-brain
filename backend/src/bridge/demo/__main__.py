"""Demo helpers (P9 ``make demo``; REQ-FND-02): ``python -m bridge.demo <command>``. Dev and test only.

- ``totp [ADDRESS]``: the current TOTP code of one demo account (the code alone, for scripts), or of every demo
  account with the seconds it stays valid. Codes come from the accounts' fixed demo secrets
  (``bridge.seed.demo.data.totp_secret``); a code is accepted once per account (replay protection), so wait for the
  next one if it was just used.
- ``logins``: the demo logins, what each one is, and the shared demo password.
- ``cert-id [--wait SECONDS]``: the certificate id of the exported demo proposal (``E2E_VERIFY_CERT_ID``), waiting up
  to SECONDS until the worker has hashed and signed it, so ``/verify`` shows its evidence. Needs
  ``DATABASE_OWNER_URL``.
- ``clock [--days N] [--hours N]``: the shared dev/test clock (revision 0003), moved forward by N days and hours when
  given, through ``app_set_test_clock``, the function the test-clock router calls: only forward, at most 366 days in
  all, and only where the seed enabled the clock (an explicit ``APP_ENV`` of dev or test). Every tracker deadline,
  reminder and evidence time follows it. After a move it runs one pass of the tracker's clock job
  (``bridge.engagements.expiry``, as the worker does every 15 minutes, as ``DATABASE_URL``'s app role), so an
  expiry or the end of a hold shows at once; the worker sends both parties' notices. Needs ``DATABASE_OWNER_URL``.

Every command refuses outside ``APP_ENV`` dev and test (``bridge.seed.demo.demo_refusal``), like the demo seed: the
fixed credentials exist nowhere else.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bridge.auth import totp
from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.engagements.expiry import run_expiry
from bridge.seed.demo import demo_refusal, exported_cert_id, registration_status, totp_code
from bridge.seed.demo.data import DEMO_LOGINS_DOC, all_accounts

SIGNED = frozenset({"signed", "timestamped"})
POLL_SECONDS = 2.0


def _totp(address: str | None) -> int:
    accounts = {email: (name, what) for email, name, what in all_accounts()}
    if address is not None:
        email = address.strip().lower()
        if email not in accounts:
            print(f"{address} is not a demo account; python -m bridge.demo logins lists them", file=sys.stderr)
            return 2
        print(totp_code(email))
        return 0
    left = totp.PERIOD - int(time.time()) % totp.PERIOD
    print(f"TOTP codes (valid for {left} more seconds; each is accepted once per account):")
    for email, (name, what) in accounts.items():
        print(f"  {totp_code(email)}  {email:30}  {name:16}  {what}")
    return 0


def _logins() -> int:
    print(f"Demo logins (all share the dev-only demo password in {DEMO_LOGINS_DOC}; never printed here):")
    for email, name, what in all_accounts():
        print(f"  {email:30}  {name:16}  {what}")
    print("Second factor (TOTP codes): make demo-totp, or make demo-totp EMAIL=<address> for one code.")
    return 0


def _owner_engine(settings: Settings, command: str) -> AsyncEngine:
    url = settings.database_owner_url
    if url is None:
        raise SystemExit(f"DATABASE_OWNER_URL is not set: {command} runs as the owner role")
    return create_async_engine(url.get_secret_value())


async def _clock(settings: Settings, days: int, hours: int) -> int:
    engine = _owner_engine(settings, "clock")
    try:
        async with engine.begin() as conn:
            if days or hours:
                current = (await conn.execute(text("SELECT clock_offset FROM test_clock"))).scalar_one()
                offset = current + timedelta(days=days, hours=hours)
                try:
                    await conn.execute(text("SELECT app_set_test_clock(:offset)"), {"offset": offset})
                except DBAPIError as exc:
                    print(f"the clock did not move: {str(exc.orig).splitlines()[0]}", file=sys.stderr)
                    return 1
            row = (
                await conn.execute(text("SELECT enabled, clock_offset, app_clock_now() AS now FROM test_clock"))
            ).one()
    finally:
        await engine.dispose()
    state = "enabled" if row.enabled else "disabled (run python -m bridge.seed with APP_ENV dev or test)"
    print(f"test clock {state}; offset {row.clock_offset}; app time now {row.now.isoformat()}")
    if days or hours:
        print(await _expiry_pass(settings))
    return 0


def _app_engine(settings: Settings) -> AsyncEngine:
    return create_engine(settings.database_url.get_secret_value())


async def _expiry_pass(settings: Settings) -> str:
    """One pass of the tracker's clock job on the moved clock (REQ-ENG-10): what it expired and resumed."""
    engine = _app_engine(settings)
    try:
        report = await run_expiry(create_session_factory(engine))
    finally:
        await engine.dispose()
    expired = sum(1 for o in report.outcomes if o.action == "expire")
    resumed = sum(1 for o in report.outcomes if o.action == "resume")
    failed = sum(1 for o in report.outcomes if o.error)
    line = f"tracker clock: {expired} engagement(s) expired, {resumed} hold(s) resumed"
    return line + (f", {failed} failed (see the logs; the worker retries)" if failed else "")


async def _cert_id(settings: Settings, wait: float) -> str | None:
    engine = _owner_engine(settings, "cert-id")
    try:
        deadline = time.monotonic() + wait
        while True:
            cert_id = await exported_cert_id(engine)
            if cert_id is not None and (wait <= 0 or await registration_status(engine, cert_id) in SIGNED):
                return cert_id
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bridge.demo", description="Local demo helpers (dev and test).")
    commands = parser.add_subparsers(dest="command", required=True)
    code = commands.add_parser("totp", help="current TOTP codes of the demo accounts")
    code.add_argument("address", nargs="?", help="one demo account: print its code only")
    commands.add_parser("logins", help="the demo logins and the shared demo password")
    cert = commands.add_parser("cert-id", help="the exported demo certificate id (E2E_VERIFY_CERT_ID)")
    cert.add_argument("--wait", type=float, default=0.0, help="seconds to wait until it is hashed and signed")
    clock = commands.add_parser("clock", help="show the dev/test clock, or move it forward")
    clock.add_argument("--days", type=int, default=0, help="days to move forward (0-366)")
    clock.add_argument("--hours", type=int, default=0, help="hours to move forward")
    args = parser.parse_args([] if argv is None else argv)
    settings = get_settings()
    if (reason := demo_refusal(settings)) is not None:
        print(f"bridge.demo refused: {reason}", file=sys.stderr)
        return 2
    if args.command == "totp":
        return _totp(args.address)
    if args.command == "logins":
        return _logins()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    if args.command == "clock":
        if args.days < 0 or args.hours < 0:
            print("the clock only moves forward", file=sys.stderr)
            return 2
        return asyncio.run(_clock(settings, args.days, args.hours), loop_factory=loop_factory)
    cert_id = asyncio.run(_cert_id(settings, args.wait), loop_factory=loop_factory)
    if cert_id is None:
        print(
            "the demo certificate is not registered yet (run python -m bridge.seed --demo; is the worker up?)",
            file=sys.stderr,
        )
        return 1
    print(cert_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
