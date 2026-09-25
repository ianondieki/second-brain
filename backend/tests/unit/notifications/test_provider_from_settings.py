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
        "data_encryption_key": SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
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


def test_postmark_is_picked_in_production_with_its_token() -> None:
    provider = provider_from_settings(
        settings(
            app_env="production",
            email_provider="postmark",
            postmark_server_token=SecretStr("pm-test-token"),
            public_base_url="https://bridge.test",
        )
    )
    assert isinstance(provider, PostmarkEmailProvider)
    assert provider.name == "postmark"


@pytest.mark.parametrize("app_env", ["dev", "test", "staging"])
def test_postmark_is_refused_outside_production(app_env: AppEnv) -> None:
    # ADR-004 decisions 1-2 and gate G7: dev, test and staging send through Mailpit (smtp) or the fake, even with a
    # Postmark token in the environment; AC-SEC-5 for test. Staging moves to Postmark only by a later ADR change.
    with pytest.raises(ValueError, match="only when APP_ENV=production"):
        provider_from_settings(
            settings(app_env=app_env, email_provider="postmark", postmark_server_token=SecretStr("pm-test-token"))
        )


def test_smtp_is_accepted_in_staging() -> None:
    assert isinstance(provider_from_settings(settings(app_env="staging", email_provider="smtp")), SmtpEmailProvider)


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_the_fake_is_refused_where_mail_must_really_go_out(app_env: AppEnv) -> None:
    # Settings already forces Postmark in production; this second fence also stops staging dropping mail silently.
    built = settings(app_env="dev", email_provider="fake")
    built.app_env = app_env  # plain assignment is not re-validated, so this reaches provider_from_settings
    with pytest.raises(ValueError, match="EMAIL_PROVIDER=fake"):
        provider_from_settings(built)
