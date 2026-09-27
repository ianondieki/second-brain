"""REQ-FND-02: the app fails closed when a secret is missing or weak."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from bridge.config import Settings

GOOD = "x" * 32
GOOD_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # base64 of 32 bytes


def make(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr(GOOD),
        "data_encryption_key": SecretStr(GOOD_KEY),
        "recovery_code_pepper": SecretStr(GOOD),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_valid_settings_load() -> None:
    assert make().app_env in {"dev", "test"}


@pytest.mark.parametrize("name", ["secret_key", "data_encryption_key", "recovery_code_pepper"])
def test_short_secret_is_refused(name: str) -> None:
    with pytest.raises(ValidationError, match=name.upper()):
        make(**{name: SecretStr("short")})


def test_missing_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr("postgresql+psycopg://x"), data_encryption_key=SecretStr(GOOD_KEY), _env_file=None
        )


def test_cookie_names_follow_cookie_secure() -> None:
    secure, plain = make(cookie_secure=True), make(cookie_secure=False)
    assert (secure.session_cookie_name, secure.csrf_cookie_name, secure.signup_cookie_name) == (
        "__Host-bridge_session",
        "__Host-bridge_csrf",
        "__Host-bridge_signup",
    )
    assert (plain.session_cookie_name, plain.csrf_cookie_name, plain.signup_cookie_name) == (
        "bridge_session",
        "bridge_csrf",
        "bridge_signup",
    )


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


def test_data_key_must_decode_to_32_bytes() -> None:
    with pytest.raises(ValidationError, match="base64 of exactly 32 bytes"):
        make(data_encryption_key=SecretStr("this is not base64 but it is long enough!!"))


def test_llm_settings_start_without_an_anthropic_key() -> None:
    """REQ-LLM-01: dev and test start with no key; the adapter refuses at call time instead."""
    settings = make()
    assert settings.anthropic_api_key is None
    assert settings.llm_kill_switch is False
    assert settings.llm_global_daily_cap_usd == Decimal("0")
    assert settings.llm_models_file.name == "models.yaml"
    assert settings.embedder == "fake"


def test_kill_switch_reads_one_as_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_KILL_SWITCH", "1")
    monkeypatch.setenv("LLM_GLOBAL_DAILY_CAP_USD", "5.00")
    settings = make()
    assert settings.llm_kill_switch is True
    assert settings.llm_global_daily_cap_usd == Decimal("5.00")


def test_negative_global_cap_is_refused() -> None:
    with pytest.raises(ValidationError, match="LLM_GLOBAL_DAILY_CAP_USD"):
        make(llm_global_daily_cap_usd=Decimal("-1"))


def test_production_refuses_the_fake_embedder() -> None:
    """REQ-EMB-01: production fails closed without a real embedder."""
    with pytest.raises(ValidationError, match="EMBEDDER=bge-m3"):
        make(app_env="production", email_provider="postmark", postmark_server_token=SecretStr("pm"), embedder="fake")


PRODUCTION: dict[str, Any] = {
    "app_env": "production",
    "email_provider": "postmark",
    "postmark_server_token": SecretStr("pm"),
    "public_base_url": "https://bridge.example",
    "embedder": "bge-m3",
}


def test_production_accepts_bge_m3_and_a_key() -> None:
    settings = make(**PRODUCTION, anthropic_api_key=SecretStr("test-anthropic-key-not-real"))
    assert settings.embedder == "bge-m3"


def test_production_needs_an_anthropic_key_unless_the_kill_switch_is_on() -> None:
    """REQ-LLM-01: production fails closed at start-up without a key; the kill switch is the only way to run keyless."""
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required in production"):
        make(**PRODUCTION)
    assert make(**PRODUCTION, llm_kill_switch=True).anthropic_api_key is None


def test_blank_anthropic_key_means_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    assert make().anthropic_api_key is None
