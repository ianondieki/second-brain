"""The proposal routes' dependencies are built from settings once and fail closed (503 ``not_configured``) when the
Tier-2 key or an allowed scanner is missing (REQ-PROP-01; ADR-007; D-36)."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from bridge.config import Settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.errors import ApiError
from bridge.proposals.deps import get_key_wrapper, get_object_store, get_prescreen, get_scanner
from bridge.proposals.prescreen import RulesPreScreen
from bridge.storage.objects import InMemoryObjectStore
from bridge.storage.scanner import FakeScanner

KEY = base64.b64encode(bytes(range(32))).decode()


def request(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(KEY),
        "recovery_code_pepper": SecretStr("p" * 32),
        "_env_file": None,
    }
    settings = Settings(**(values | overrides))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


def test_built_once_from_settings() -> None:
    req = request(tier2_local_kek=SecretStr(KEY), object_store="memory", app_env="test")
    wrapper = get_key_wrapper(req)
    assert isinstance(wrapper, LocalKeyWrapper)
    assert get_key_wrapper(req) is wrapper
    store = get_object_store(req)
    assert isinstance(store, InMemoryObjectStore)
    assert get_object_store(req) is store
    scanner = get_scanner(req)
    assert isinstance(scanner, FakeScanner)
    assert get_scanner(req) is scanner
    prescreen = get_prescreen(req)
    assert isinstance(prescreen, RulesPreScreen)
    assert get_prescreen(req) is prescreen


def test_no_tier2_key_is_503() -> None:
    with pytest.raises(ApiError) as caught:
        get_key_wrapper(request(tier2_local_kek=None))
    assert caught.value.status_code == 503
    detail: Any = caught.value.detail
    assert detail["code"] == "not_configured"


def test_the_fake_scanner_outside_dev_and_test_is_503() -> None:
    with pytest.raises(ApiError) as caught:
        get_scanner(request(app_env="staging"))
    assert caught.value.status_code == 503
