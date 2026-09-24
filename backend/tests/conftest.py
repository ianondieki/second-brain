"""Shared test configuration. The egress guard is installed before any test module is imported."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from tests import egress

egress.install()

# Unit tests never read a developer's backend/.env: settings come from here or from the test itself.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://bridge_app:bridge_app@localhost:5432/bridge_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef0123456789")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "dGVzdC1kYXRhLWtleS0wMTIzNDU2Nzg5YWJjZGVmMDE=")
os.environ.setdefault("EMAIL_PROVIDER", "fake")


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """psycopg's async driver needs a selector event loop; Windows defaults to the proactor loop."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined,unused-ignore]
    return asyncio.DefaultEventLoopPolicy()
