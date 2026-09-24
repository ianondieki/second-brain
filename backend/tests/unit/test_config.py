"""REQ-FND-02: the app fails closed when a secret is missing or weak."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from bridge.config import Settings

GOOD = "x" * 32


def make(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr(GOOD),
        "data_encryption_key": SecretStr(GOOD),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_valid_settings_load() -> None:
    assert make().app_env in {"dev", "test"}


@pytest.mark.parametrize("name", ["secret_key", "data_encryption_key"])
def test_short_secret_is_refused(name: str) -> None:
    with pytest.raises(ValidationError, match=name.upper()):
        make(**{name: SecretStr("short")})


def test_missing_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr("postgresql+psycopg://x"), data_encryption_key=SecretStr(GOOD), _env_file=None)


def test_postmark_needs_its_token() -> None:
    with pytest.raises(ValidationError, match="POSTMARK_SERVER_TOKEN"):
        make(email_provider="postmark")


def test_production_refuses_smtp_http_and_insecure_cookies() -> None:
    with pytest.raises(ValidationError) as info:
        make(app_env="production", email_provider="smtp", public_base_url="http://x", cookie_secure=False)
    text = str(info.value)
    assert "Postmark" in text
    assert "https" in text
    assert "COOKIE_SECURE" in text


def test_feature_flags_default_off() -> None:
    settings = make()
    assert settings.feature_tier2_enabled is False
    assert settings.feature_deals_enabled is False
