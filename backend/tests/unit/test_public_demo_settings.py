"""REQ-FND-04 (P28 track PD, AT-PD-2): the public demo's settings. ``PUBLIC_DEMO`` is off and ``PUBLIC_DEMO_CONTENT``
fictional by default; ``PUBLIC_DEMO=true`` is refused at start-up unless ``APP_ENV`` is set explicitly to dev or test
(staging, production and the settings default refuse it); both variables are documented in ``backend/.env.example``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from bridge.config import BACKEND_DIR, Settings, get_settings


def settings_of(**values: Any) -> Settings:
    """Settings from these values only (no environment file); the test environment supplies the secrets."""
    base = get_settings()
    secrets = {
        "database_url": base.database_url,
        "secret_key": base.secret_key,
        "data_encryption_key": base.data_encryption_key,
        "recovery_code_pepper": base.recovery_code_pepper,
    }
    return Settings(_env_file=None, **{**secrets, **values})


def test_the_mode_is_off_and_fictional_by_default() -> None:
    settings = settings_of(app_env="test")
    assert (settings.public_demo, settings.public_demo_content) == (False, "fictional")


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_dev_and_test_may_run_the_public_demo(app_env: str) -> None:
    settings = settings_of(app_env=app_env, public_demo=True, public_demo_content="full")
    assert (settings.public_demo, settings.public_demo_content) == (True, "full")


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_staging_and_production_refuse_the_public_demo_at_start_up(app_env: str) -> None:
    production = {
        "email_provider": "postmark",
        "postmark_server_token": SecretStr("pm-unit-test-token"),
        "public_base_url": "https://bridge.test",
        "embedder": "bge-m3",
        "llm_kill_switch": True,
    }
    extra = production if app_env == "production" else {}
    settings_of(app_env=app_env, **extra)  # valid without the demo
    with pytest.raises(ValidationError, match="PUBLIC_DEMO=true runs only with APP_ENV set explicitly to dev or test"):
        settings_of(app_env=app_env, public_demo=True, **extra)


def test_the_settings_default_app_env_refuses_the_public_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV defaults to dev; a process that never set it does not get the public demo (fail closed)."""
    monkeypatch.delenv("APP_ENV", raising=False)
    assert settings_of().app_env == "dev"
    with pytest.raises(ValidationError, match="PUBLIC_DEMO=true"):
        settings_of(public_demo=True)


def test_the_environment_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("PUBLIC_DEMO_CONTENT", "full")
    settings = settings_of()
    assert (settings.app_env, settings.public_demo, settings.public_demo_content) == ("test", True, "full")
    monkeypatch.setenv("PUBLIC_DEMO_CONTENT", "everything")
    with pytest.raises(ValidationError):
        settings_of()


def test_the_variables_are_documented() -> None:
    example = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "PUBLIC_DEMO=false" in example
    assert "PUBLIC_DEMO_CONTENT=fictional" in example
