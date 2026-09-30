"""Shared test configuration. The egress guard is installed, and proxies are disabled, before any test module is
imported (AC-SEC-5: the guard allows loopback, so a loopback proxy must not be able to relay a request)."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable

import pytest

from bridge.config import Settings
from tests import egress

egress.install()
egress.disable_proxies()

# Tests never read a developer's backend/.env (``make demo`` writes one, with PAYMENT_PROVIDER=fake and the demo's
# URLs): settings come from here, from the environment or from the test itself (REQ-FND-01, P16-E1 item 7). A
# subprocess a test starts gets its environment from the test.
Settings.model_config["env_file"] = None
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://bridge_app:bridge_app@localhost:5432/bridge_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef0123456789")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "dGVzdC1kYXRhLWtleS0wMTIzNDU2Nzg5YWJjZGVmMDE=")
os.environ.setdefault("EMAIL_PROVIDER", "fake")
os.environ.setdefault("RECOVERY_CODE_PEPPER", "test-recovery-pepper-0123456789abcdef012345")
# D-37: tests never read a shell's or a backend/.env's LLM provider settings (an empty value is unset, and an unset
# provider is the fake under APP_ENV=test); a test that needs a provider builds its own settings.
os.environ["LLM_PROVIDER"] = ""
for _slot in (1, 2, 3):
    for _part in ("BASE_URL", "API_KEY", "MODEL", "DAILY_REQUESTS", "RESPONSE_FORMAT"):
        os.environ[f"LLM_FREE_{_slot}_{_part}"] = ""


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """psycopg's async driver needs a selector event loop; Windows defaults to the proactor loop."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}
