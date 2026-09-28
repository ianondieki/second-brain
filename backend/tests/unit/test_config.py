"""REQ-FND-02: the app fails closed when a secret is missing or weak."""

from __future__ import annotations

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
    assert (secure.oauth_cookie_name, plain.oauth_cookie_name) == ("__Host-bridge_oauth", "bridge_oauth")


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


def test_oauth_providers_default_off() -> None:
    settings = make()
    assert settings.github_client_id is None
    assert settings.google_client_secret is None


@pytest.mark.parametrize("provider", ["github", "google"])
@pytest.mark.parametrize("half", ["id", "secret"])
def test_half_an_oauth_configuration_is_refused(provider: str, half: str) -> None:
    """REQ-AUTH-02: a client id without its secret (or the reverse) stops the app instead of half-enabling it."""
    with pytest.raises(ValidationError, match=f"{provider.upper()}_CLIENT_ID and {provider.upper()}_CLIENT_SECRET"):
        make(**{f"{provider}_client_{half}": SecretStr("configured-value")})


def test_blank_oauth_values_count_as_unset() -> None:
    settings = make(github_client_id=SecretStr(""), github_client_secret=SecretStr("  "))
    assert settings.github_client_id is not None  # present but blank: the provider stays off (bridge.auth.oauth)
