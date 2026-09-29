"""Provenance commands: ``python -m bridge.provenance register-key [--if-configured]`` and ``probe-tsa`` (ADR-003).

``register-key`` publishes the signing key's public half in ``provenance_keys`` (served at
``/.well-known/provenance-keys.json``) as the owner role (``DATABASE_OWNER_URL``); the app role may only read that
table. Idempotent. ``--if-configured`` exits 0 without doing anything when no signing key is configured (the dev
compose ``migrate`` step), instead of failing.

``probe-tsa`` timestamps a fresh random digest at ``TSA_URL`` and at ``TSA_FALLBACK_URL``, each on its own (no
fallback between them), with the worker's own client and settings: the pinned bundles, nonce and imprint, the
timeStamping certificate, ESS, the 256 KiB cap and the anchors' one-minute bound on the token's time. It prints one
line per TSA and exits 0 when every TSA passed, 1 when one failed, 2 when the settings fail closed. It makes real TSA
calls: run it from the worker host before a release (``docs/runbooks/verify-offline.md``), never from tests or CI.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from bridge.config import ConfigurationError, Settings, get_settings
from bridge.provenance.signing import Signer, register_public_key, signer_from_settings
from bridge.provenance.transparency import ANCHOR_MAX_AHEAD
from bridge.provenance.tsa import TsaClient, TsaError, tsa_client_from_settings


async def register(url: str, signer: Signer) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            return await register_public_key(connection, signer)
    finally:
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class ProbeResult:
    url: str
    ok: bool
    detail: str


async def probe(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> list[ProbeResult]:
    """Timestamp a random digest at every configured TSA, one at a time; ``ConfigurationError`` when the settings
    fail closed (a TSA without its bundle outside dev and test)."""
    configured = tsa_client_from_settings(settings, transport=transport)
    digest = hashlib.sha256(b"bridge tsa probe " + secrets.token_bytes(16)).digest()
    results: list[ProbeResult] = []
    for endpoint in configured.endpoints:
        client = TsaClient(
            [endpoint],
            timeout=settings.tsa_timeout_seconds,
            deadline=settings.tsa_deadline_seconds,
            transport=transport,
            clock=clock,
        )
        try:
            token = await client.timestamp(digest, max_ahead=ANCHOR_MAX_AHEAD)
        except TsaError as exc:
            results.append(ProbeResult(endpoint.url, ok=False, detail=str(exc)))
            continue
        chain = (
            f"chain pinned to {endpoint.trust.source}"
            if endpoint.trust is not None
            else "chain NOT checked (no bundle: dev and test only)"
        )
        detail = f"genTime {token.gen_time.isoformat()}, serial {token.serial}, policy {token.policy}, {chain}"
        results.append(ProbeResult(endpoint.url, ok=True, detail=detail))
    return results


def _loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None


def _probe_command(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    clock: Callable[[], datetime] | None,
) -> int:
    try:
        results = asyncio.run(probe(settings, transport=transport, clock=clock), loop_factory=_loop_factory())
    except ConfigurationError as exc:
        print(f"provenance: {exc}", file=sys.stderr)
        return 2
    for result in results:
        if result.ok:
            print(f"ok {result.url}: {result.detail}")
        else:
            print(f"FAILED {result.url}: {result.detail}", file=sys.stderr)
    return 0 if all(result.ok for result in results) else 1


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """The command line; ``transport`` and ``clock`` are for tests (the local openssl TSA, a skewed clock)."""
    parser = argparse.ArgumentParser(prog="python -m bridge.provenance")
    commands = parser.add_subparsers(dest="command", required=True)
    register_key = commands.add_parser("register-key", help="publish the signing key's public key (owner role)")
    register_key.add_argument("--if-configured", action="store_true", help="succeed quietly when no key is set")
    commands.add_parser("probe-tsa", help="timestamp a random digest at each configured TSA (real TSA calls)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "probe-tsa":
        return _probe_command(settings, transport, clock)
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
    added = asyncio.run(register(settings.database_owner_url.get_secret_value(), signer), loop_factory=_loop_factory())
    print(f"provenance: {key_id} {'registered' if added else 'already registered'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
