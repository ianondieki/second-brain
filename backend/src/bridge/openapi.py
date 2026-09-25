"""Write the OpenAPI document to ``backend/openapi.json`` (frozen and drift-checked in CI, docs/spec/12 12.3).

Usage: ``uv run python -m bridge.openapi [--check]``. ``--check`` exits 1 when the committed file is stale.
No database, network or real secret is needed: the schema comes from the routes alone.
"""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import SecretStr

from bridge.config import BACKEND_DIR, Settings
from bridge.main import create_app

OPENAPI_PATH = BACKEND_DIR / "openapi.json"
_ZERO_KEY = SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")  # 32 zero bytes: shape-valid, never a real key
_PLACEHOLDER = SecretStr("openapi-export-placeholder-not-a-secret-0000")


def render() -> str:
    settings = Settings(
        app_env="test",
        database_url=SecretStr("postgresql+psycopg://openapi@localhost/openapi"),
        secret_key=_PLACEHOLDER,
        data_encryption_key=_ZERO_KEY,
    )
    schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or check backend/openapi.json")
    parser.add_argument("--check", action="store_true", help="fail if the committed file differs")
    args = parser.parse_args(argv)
    current = render()
    if args.check:
        committed = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else ""
        if committed != current:
            sys.stderr.write("backend/openapi.json is stale: run `make openapi` and commit the result.\n")
            return 1
        return 0
    OPENAPI_PATH.write_text(current, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
