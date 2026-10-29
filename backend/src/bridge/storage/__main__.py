"""Object-store buckets before start-up: ``python -m bridge.storage ensure-buckets [--wait SECONDS]`` (ADR-007).

Runs in the dev compose ``migrate`` step, before the API and the worker start, so no code path creates a bucket at
first use. In ``APP_ENV`` dev and test it creates the missing ``evidence``, ``kyc-review`` and ``uploads`` buckets
(SeaweedFS); in staging and production it only checks that they exist and fails closed (exit 2) when one is missing:
there infrastructure creates them, with Object Lock on ``evidence`` (which S3 sets only when a bucket is created).
Idempotent. ``--wait`` retries for that many seconds while the store refuses connections (it may still be starting).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from botocore.exceptions import ConnectionError as BotoConnectionError
from botocore.exceptions import HTTPClientError

from bridge.config import ConfigurationError, get_settings
from bridge.storage.objects import BucketName, object_store_from_settings

CREATING_ENVS = frozenset({"dev", "test"})
RETRY_EVERY = 1.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bridge.storage")
    commands = parser.add_subparsers(dest="command", required=True)
    ensure = commands.add_parser("ensure-buckets", help="create (dev, test) or check (elsewhere) the buckets")
    ensure.add_argument("--wait", type=float, default=30.0, help="seconds to wait for a store that is starting")
    args = parser.parse_args(argv)

    settings = get_settings()
    store = object_store_from_settings(settings)
    create = settings.app_env in CREATING_ENVS
    give_up = time.monotonic() + args.wait
    while True:
        try:
            created: list[BucketName] = asyncio.run(store.ensure_buckets(create=create))
            break
        except ConfigurationError as exc:
            print(f"storage: {exc}", file=sys.stderr)
            return 2
        except (BotoConnectionError, HTTPClientError) as exc:
            if time.monotonic() >= give_up:
                print(f"storage: could not reach the object store ({type(exc).__name__})", file=sys.stderr)
                return 2
            time.sleep(RETRY_EVERY)
    print(f"storage: created {', '.join(created)}" if created else "storage: every bucket exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
