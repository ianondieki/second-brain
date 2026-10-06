"""Where the demo seed and its helper run (P9 ``make demo``; REQ-FND-02, REQ-DIR-02): dev and test only.

The demo accounts have public credentials (one password, TOTP secrets derived from the address), so the seed and
``python -m bridge.demo`` refuse staging, production and an ``APP_ENV`` left to the settings default, before anything
is read or written.
"""

from __future__ import annotations

import base64
import re

import pyotp
import pytest
from pydantic import SecretStr

from bridge.config import Settings, get_settings
from bridge.demo import __main__ as demo_command
from bridge.seed import __main__ as seed_command
from bridge.seed.demo import DemoSeedRefused, demo_refusal, ensure_demo_allowed, totp_code
from bridge.seed.demo.data import DEMO_PASSWORD, DEVELOPERS, ORGS, PROPOSALS, all_accounts, totp_secret

OWNER_URL = SecretStr("postgresql+psycopg://owner@localhost/bridge")


def settings_for(app_env: str) -> Settings:
    return get_settings().model_copy(update={"app_env": app_env, "database_owner_url": OWNER_URL})


def settings_without_app_env() -> Settings:
    settings = settings_for("dev")
    return type(settings).model_construct(_fields_set=set(settings.model_fields_set) - {"app_env"}, **dict(settings))


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_dev_and_test_allow_the_demo(app_env: str) -> None:
    assert demo_refusal(settings_for(app_env)) is None
    ensure_demo_allowed(settings_for(app_env))


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_staging_and_production_refuse_the_demo(app_env: str) -> None:
    with pytest.raises(DemoSeedRefused, match=f"APP_ENV={app_env}.*never in staging or production"):
        ensure_demo_allowed(settings_for(app_env))


def test_the_settings_default_refuses_the_demo() -> None:
    settings = settings_without_app_env()
    assert settings.app_env == "dev"  # the default, which a forgotten APP_ENV would give
    with pytest.raises(DemoSeedRefused, match="APP_ENV is not set"):
        ensure_demo_allowed(settings)


@pytest.mark.parametrize("app_env", ["staging", "production", None])
def test_the_seed_command_refuses_demo_before_writing_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], app_env: str | None
) -> None:
    settings = settings_without_app_env() if app_env is None else settings_for(app_env)

    async def must_not_run(*_: object) -> None:
        raise AssertionError("nothing may be seeded when --demo is refused")

    monkeypatch.setattr(seed_command, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_command, "run", must_not_run)
    monkeypatch.setattr(seed_command, "run_demo", must_not_run)
    assert seed_command.main(["--demo"]) == 2
    assert "--demo refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command", [["totp"], ["totp", DEVELOPERS[0].email], ["logins"], ["cert-id"], ["clock", "--days", "1"]]
)
@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_the_demo_helper_refuses_outside_dev_and_test(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: list[str], app_env: str
) -> None:
    monkeypatch.setattr(demo_command, "get_settings", lambda: settings_for(app_env))
    assert demo_command.main(command) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bridge.demo refused" in captured.err


def test_the_logins_list_every_demo_account_and_point_to_the_password_without_printing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo_command, "get_settings", lambda: settings_for("dev"))
    assert demo_command.main(["logins"]) == 0
    out = capsys.readouterr().out
    assert DEMO_PASSWORD not in out  # CodeQL py/clear-text-logging-sensitive-data: the README documents it
    assert "README.md" in out
    for email, name, _ in all_accounts():
        assert email in out
        assert name in out


def test_totp_secrets_are_fixed_per_address_and_codes_match_an_authenticator_app() -> None:
    secrets = {email: totp_secret(email) for email, _, _ in all_accounts()}
    assert len(set(secrets.values())) == len(secrets)
    for email, secret in secrets.items():
        assert re.fullmatch(r"[A-Z2-7]{32}", secret)
        assert len(base64.b32decode(secret)) == 20
        assert totp_secret(email.upper()) == secret
        assert totp_code(email, at=1_800_000_000) == pyotp.TOTP(secret).at(1_800_000_000)


def test_the_dataset_names_only_fixtures_at_reserved_domains() -> None:
    accounts = all_accounts()
    # 11 people, the P11 staff admin, the P15 staff moderator and P22's two more developers (Peers)
    assert len(accounts) == len({email for email, _, _ in accounts}) == 15
    assert all(email.endswith(".example") for email, _, _ in accounts)
    assert all(org.legal_name.endswith("(fixture)") for org in ORGS)
    assert {org.verification.value for org in ORGS} == {"e2", "e1", "unclaimed"}
    assert all(proposal.owner in {dev.email for dev in DEVELOPERS} for proposal in PROPOSALS)


def test_the_clock_only_moves_forward(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(demo_command, "get_settings", lambda: settings_for("dev"))
    assert demo_command.main(["clock", "--days", "-1"]) == 2
    assert "only moves forward" in capsys.readouterr().err
