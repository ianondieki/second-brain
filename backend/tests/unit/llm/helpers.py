"""Shared helpers for the LLM-layer unit tests (no network: fakes and synthetic cassettes only, D-18)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from bridge.config import Settings, get_settings
from bridge.llm import registry
from bridge.llm.registry import Registry

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
ORG = UUID("01900000-0000-7000-8000-00000000000a")
USER = UUID("01900000-0000-7000-8000-00000000000b")
OWNER = UUID("01900000-0000-7000-8000-00000000000c")
OTHER_OWNER = UUID("01900000-0000-7000-8000-00000000000d")


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        "recovery_code_pepper": SecretStr("y" * 32),
        "llm_global_daily_cap_usd": Decimal("100"),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def real_registry() -> Registry:
    return registry.load(get_settings().llm_models_file)
