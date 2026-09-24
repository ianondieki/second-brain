"""REQ-NOT-01 / ADR-004: ``EMAIL_PROVIDER`` picks the adapter; the choice fails closed (AC-SEC-5)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from bridge.config import AppEnv, Settings
from bridge.notifications.email import (
    FakeEmailProvider,
    PostmarkEmailProvider,
    SmtpEmailProvider,
    provider_from_settings,
)

GOOD = "x" * 32


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr(GOOD),
        "data_encryption_key": SecretStr(GOOD),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_fake_is_picked_for_unit_tests() -> None:
    provider = provider_from_settings(settings(app_env="test", email_provider="fake"))
    assert isinstance(provider, FakeEmailProvider)
    assert provider.name == "fake"


def test_smtp_is_picked_for_mailpit() -> None:
    provider = provider_from_settings(settings(app_env="dev", email_provider="smtp", smtp_host="mailpit"))
    assert isinstance(provider, SmtpEmailProvider)
    assert provider.name == "smtp"


def test_postmark_is_picked_with_its_token() -> None:
    provider = provider_from_settings(
        settings(app_env="staging", email_provider="postmark", postmark_server_token=SecretStr("pm-test-token"))
    )
    assert isinstance(provider, PostmarkEmailProvider)
    assert provider.name == "postmark"


def test_postmark_is_refused_under_app_env_test() -> None:
    # AC-SEC-5: nothing run by make check or CI may reach a real provider, even with a token in the environment.
    with pytest.raises(ValueError, match="APP_ENV=test"):
        provider_from_settings(
            settings(app_env="test", email_provider="postmark", postmark_server_token=SecretStr("pm-test-token"))
        )


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_the_fake_is_refused_where_mail_must_really_go_out(app_env: AppEnv) -> None:
    # Settings already forces Postmark in production; this second fence also stops staging dropping mail silently.
    built = settings(app_env="dev", email_provider="fake")
    built.app_env = app_env  # plain assignment is not re-validated, so this reaches provider_from_settings
    with pytest.raises(ValueError, match="EMAIL_PROVIDER=fake"):
        provider_from_settings(built)
