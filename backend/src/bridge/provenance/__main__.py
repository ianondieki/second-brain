"""Provenance key registration: ``python -m bridge.provenance register-key [--if-configured]`` (ADR-003).

Publishes the signing key's public half in ``provenance_keys`` (served at ``/.well-known/provenance-keys.json``) as the
owner role (``DATABASE_OWNER_URL``); the app role may only read that table. Idempotent. ``--if-configured`` exits 0
without doing anything when no signing key is configured (the dev compose ``migrate`` step), instead of failing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from bridge.config import ConfigurationError, get_settings
from bridge.provenance.signing import Signer, register_public_key, signer_from_settings


async def register(url: str, signer: Signer) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            return await register_public_key(connection, signer)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bridge.provenance")
    commands = parser.add_subparsers(dest="command", required=True)
    register_key = commands.add_parser("register-key", help="publish the signing key's public key (owner role)")
    register_key.add_argument("--if-configured", action="store_true", help="succeed quietly when no key is set")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        signer = signer_from_settings(settings)
        key_id = signer.key_id
    except (ConfigurationError, NotImplementedError) as exc:
        if args.if_configured:
            print(f"provenance: no key registered ({exc})")
            return 0
        print(f"provenance: {exc}", file=sys.stderr)
        return 2
    if settings.database_owner_url is None:
        print("DATABASE_OWNER_URL is not set: keys are registered as the owner role (bridge_owner).", file=sys.stderr)
        return 2
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    added = asyncio.run(register(settings.database_owner_url.get_secret_value(), signer), loop_factory=loop_factory)
    print(f"provenance: {key_id} {'registered' if added else 'already registered'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
