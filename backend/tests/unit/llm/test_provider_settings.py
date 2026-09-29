"""REQ-LLM-01 P7 (D-37): the LLM provider settings for local prototype runs.

``LLM_PROVIDER`` picks the provider family (fake | free | anthropic); each free provider slot is a base URL, key, model
and daily request cap, all set together or all left empty (fail closed). Staging and production never send data to a
free provider, and production runs Anthropic only. Nothing here reaches a provider.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from bridge.config import BACKEND_DIR, LLM_FREE_SLOTS, FreeSlot, Settings
from tests.unit.llm.helpers import settings

SLOT_1: dict[str, Any] = {
    "llm_free_1_base_url": "https://free-one.example/v1/",
    "llm_free_1_api_key": SecretStr("free-one-key-not-real"),
    "llm_free_1_model": "vendor/demo-model-8b:free",
    "llm_free_1_daily_requests": 50,
}
SLOT_1_PARTS = ("llm_free_1_base_url", "llm_free_1_api_key", "llm_free_1_model", "llm_free_1_daily_requests")
PRODUCTION: dict[str, Any] = {
    "app_env": "production",
    "email_provider": "postmark",
    "postmark_server_token": SecretStr("pm"),
    "public_base_url": "https://bridge.example",
    "embedder": "bge-m3",
    "anthropic_api_key": SecretStr("test-anthropic-key-not-real"),
}


def test_tests_run_on_the_fake_provider() -> None:
    """The test conftest blanks the provider variables (a shell or .env value never leaks in), and an unset provider
    is the fake under APP_ENV=test, even with a complete slot: no test reaches a provider by default."""
    assert settings().llm_provider is None
    assert settings().llm_free_slots() == ()
    assert settings().llm_effective_provider == "fake"
    assert settings(**SLOT_1).llm_effective_provider == "fake"
    assert settings(llm_provider="free", **SLOT_1).llm_effective_provider == "free"  # only when a test asks


def test_a_complete_slot_is_parsed_with_its_defaults() -> None:
    cfg = settings(**SLOT_1)
    (slot,) = cfg.llm_free_slots()
    assert slot == FreeSlot(
        number=1,
        base_url="https://free-one.example/v1",  # the trailing slash is dropped
        api_key=SecretStr("free-one-key-not-real"),
        model="vendor/demo-model-8b:free",
        daily_requests=50,
        response_format="json_object",
    )
    assert slot.name == "free1"
    assert "free-one-key-not-real" not in repr(slot)
    assert "free-one-key-not-real" not in str(slot)
    assert LLM_FREE_SLOTS == (1, 2, 3)


def test_slots_are_listed_in_order_and_empty_ones_are_skipped() -> None:
    cfg = settings(
        llm_free_3_base_url="http://127.0.0.1:11434/v1",
        llm_free_3_api_key=SecretStr("local"),
        llm_free_3_model="qwen2.5:7b",
        llm_free_3_daily_requests=1000,
        llm_free_3_response_format="none",
        **SLOT_1,
    )
    assert [(s.number, s.response_format) for s in cfg.llm_free_slots()] == [(1, "json_object"), (3, "none")]


@pytest.mark.parametrize("missing", SLOT_1_PARTS)
def test_a_half_configured_slot_stops_start_up(missing: str) -> None:
    values = {k: v for k, v in SLOT_1.items() if k != missing}
    with pytest.raises(ValidationError, match="LLM_FREE_1_BASE_URL, LLM_FREE_1_API_KEY, LLM_FREE_1_MODEL and"):
        settings(**values)


def test_a_response_format_without_its_slot_stops_start_up() -> None:
    with pytest.raises(ValidationError, match="LLM_FREE_2_RESPONSE_FORMAT is set but slot 2 is not"):
        settings(llm_free_2_response_format="json_schema")


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://free-one.example/v1", "https"),
        ("ftp://free-one.example/v1", "https"),
        ("https://user:pass@free-one.example/v1", "credentials"),
        ("https://free-one.example/v1?key=abc", "query"),
        ("https://free-one.example/v1#x", "query"),
        ("https:///v1", "host"),
        ("not a url", "https"),
    ],
)
def test_a_slot_url_is_https_without_credentials_or_query(url: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(**{**SLOT_1, "llm_free_1_base_url": url})


@pytest.mark.parametrize("url", ["http://localhost:1234/v1", "http://127.0.0.1:11434/v1", "http://[::1]:8080/v1"])
def test_plain_http_is_allowed_on_loopback_only(url: str) -> None:
    (slot,) = settings(**{**SLOT_1, "llm_free_1_base_url": url}).llm_free_slots()
    assert slot.base_url == url


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"llm_free_1_daily_requests": 0}, "LLM_FREE_1_DAILY_REQUESTS must be 1 or more"),
        ({"llm_free_1_model": "m" * 75}, "LLM_FREE_1_MODEL"),
        ({"llm_free_1_model": "two words"}, "LLM_FREE_1_MODEL"),
        ({"llm_free_1_api_key": SecretStr("   ")}, "LLM_FREE_1_BASE_URL, LLM_FREE_1_API_KEY"),
    ],
)
def test_slot_values_are_checked(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(**{**SLOT_1, **changes})


def test_empty_values_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``NAME=`` as in ``.env.example`` leaves a slot (and the provider choice) unset."""
    for name in (
        "LLM_PROVIDER",
        "LLM_FREE_1_BASE_URL",
        "LLM_FREE_1_API_KEY",
        "LLM_FREE_1_MODEL",
        "LLM_FREE_1_DAILY_REQUESTS",
        "LLM_FREE_1_RESPONSE_FORMAT",
    ):
        monkeypatch.setenv(name, "")
    cfg = settings()  # read from the environment (the helper passes no provider value)
    assert isinstance(cfg, Settings)
    assert cfg.llm_provider is None
    assert cfg.llm_free_slots() == ()


def test_an_unset_provider_is_free_with_a_slot_and_fake_without_in_dev() -> None:
    assert settings(app_env="dev", llm_provider=None).llm_effective_provider == "fake"
    assert settings(app_env="dev", llm_provider=None, **SLOT_1).llm_effective_provider == "free"
    # Anthropic is used only when chosen explicitly, even with a key (D-37).
    keyed = settings(app_env="dev", llm_provider=None, anthropic_api_key=SecretStr("test-anthropic-key-not-real"))
    assert keyed.llm_effective_provider == "fake"
    assert settings(app_env="dev", llm_provider="anthropic", **SLOT_1).llm_effective_provider == "anthropic"
    assert settings(app_env="dev", llm_provider="fake", **SLOT_1).llm_effective_provider == "fake"


def test_the_demo_fallback_is_for_dev_and_test_only() -> None:
    assert settings(app_env="dev").llm_demo_fallback is True
    assert settings(app_env="test").llm_demo_fallback is True
    assert settings(app_env="staging", llm_provider=None).llm_demo_fallback is False
    assert settings(**PRODUCTION, llm_provider=None).llm_demo_fallback is False


def test_production_never_uses_a_free_provider() -> None:
    with pytest.raises(ValidationError, match="never send data to free providers"):
        settings(**PRODUCTION, llm_provider="free")
    with pytest.raises(ValidationError, match="LLM_FREE_1_"):
        settings(**PRODUCTION, llm_provider="anthropic", **SLOT_1)
    with pytest.raises(ValidationError, match="production uses LLM_PROVIDER=anthropic"):
        settings(**PRODUCTION, llm_provider="fake")
    cfg = settings(**PRODUCTION, llm_provider=None)
    assert cfg.llm_effective_provider == "anthropic"
    assert settings(**PRODUCTION, llm_provider="anthropic").llm_effective_provider == "anthropic"


def test_staging_never_uses_a_free_provider() -> None:
    with pytest.raises(ValidationError, match="never send data to free providers"):
        settings(app_env="staging", llm_provider="free")
    with pytest.raises(ValidationError, match="LLM_FREE_1_"):
        settings(app_env="staging", llm_provider=None, **SLOT_1)
    assert settings(app_env="staging", llm_provider=None).llm_effective_provider == "anthropic"


def test_the_prototype_total_is_five_dollars_on_local_runs_and_explicit_elsewhere() -> None:
    """D-37's USD 5 is the prototype's: dev and test default to it; staging and production have no total unless it
    is set explicitly (a lifetime cap would stop a hosted app, and summing the whole ledger per call is not free)."""
    assert Settings.model_fields["llm_prototype_total_cap_usd"].default is None
    for env in ("dev", "test"):
        assert settings(app_env=env, llm_prototype_total_cap_usd=None).llm_total_cap_usd == Decimal("5.00")
    assert settings(app_env="dev", llm_prototype_total_cap_usd=Decimal(0)).llm_total_cap_usd == 0
    assert settings(app_env="staging", llm_prototype_total_cap_usd=None).llm_total_cap_usd is None
    assert settings(**PRODUCTION, llm_prototype_total_cap_usd=None).llm_total_cap_usd is None
    assert settings(**PRODUCTION, llm_prototype_total_cap_usd=Decimal(20)).llm_total_cap_usd == 20
    with pytest.raises(ValidationError, match="LLM_PROTOTYPE_TOTAL_CAP_USD must be zero or more"):
        settings(llm_prototype_total_cap_usd=Decimal("-0.01"))


def test_every_new_variable_is_documented_by_name_only() -> None:
    """``backend/.env.example`` names every provider variable and never carries a key, URL or model value."""
    example = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    assigned = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in example if "=" in line and line[0] != "#"}
    names = ["LLM_PROVIDER", "LLM_PROTOTYPE_TOTAL_CAP_USD"]
    for n in LLM_FREE_SLOTS:
        names += [f"LLM_FREE_{n}_{part}" for part in ("BASE_URL", "API_KEY", "MODEL", "DAILY_REQUESTS")]
        names.append(f"LLM_FREE_{n}_RESPONSE_FORMAT")
    for name in names:
        assert name in assigned, name
        if name.startswith("LLM_FREE_") or name == "LLM_PROVIDER":
            assert assigned[name] == "", f"{name} has a value in .env.example"
    assert assigned["LLM_GLOBAL_DAILY_CAP_USD"] == "1.00"
    assert assigned["LLM_PROTOTYPE_TOTAL_CAP_USD"] == "5.00"
    text = " ".join(" ".join(example).split())
    assert "per UTC day through this slot across every account (platform-wide" in text  # app_llm_calls_since
    assert Path(BACKEND_DIR / ".env.example").is_file()
