"""Demo helpers (P9 ``make demo``; REQ-FND-02): ``python -m bridge.demo <command>``. Dev and test only.

- ``totp [ADDRESS]``: the current TOTP code of one demo account (the code alone, for scripts), or of every demo
  account with the seconds it stays valid. Codes come from the accounts' fixed demo secrets
  (``bridge.seed.demo.data.totp_secret``); a code is accepted once per account (replay protection), so wait for the
  next one if it was just used.
- ``logins``: the demo logins, what each one is, and the shared demo password.
- ``cert-id [--wait SECONDS]``: the certificate id of the exported demo proposal (``E2E_VERIFY_CERT_ID``), waiting up
  to SECONDS until the worker has hashed and signed it, so ``/verify`` shows its evidence. Needs
  ``DATABASE_OWNER_URL``.

Every command refuses outside ``APP_ENV`` dev and test (``bridge.seed.demo.demo_refusal``), like the demo seed: the
fixed credentials exist nowhere else.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from sqlalchemy.ext.asyncio import create_async_engine

from bridge.auth import totp
from bridge.config import Settings, get_settings
from bridge.seed.demo import demo_refusal, exported_cert_id, registration_status, totp_code
from bridge.seed.demo.data import DEMO_PASSWORD, all_accounts

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
    print(f"Demo logins (password for all: {DEMO_PASSWORD}; dev-only, public on purpose):")
    for email, name, what in all_accounts():
        print(f"  {email:30}  {name:16}  {what}")
    print("Second factor: make demo-totp (or python -m bridge.demo totp <address>).")
    return 0


async def _cert_id(settings: Settings, wait: float) -> str | None:
    url = settings.database_owner_url
    if url is None:
        raise SystemExit("DATABASE_OWNER_URL is not set: cert-id reads as the owner role")
    engine = create_async_engine(url.get_secret_value())
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
