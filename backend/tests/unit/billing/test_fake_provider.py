"""REQ-BIL-04 (interface only) and REQ-BIL-08 (P14; D-36): ``FakePaymentProvider`` and the ``PAYMENT_PROVIDER``
setting.

The fake answers pending until its delay has passed on the clock the caller passes (the app clock), then its scripted
outcome; it never verifies a callback. The fake runs only in dev and test: staging and production refuse
``PAYMENT_PROVIDER=fake`` at start-up and build no provider when it is unset (fail closed). Nothing here reaches a
network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from bridge.billing.providers import payment_provider_from_settings
from bridge.billing.providers.base import (
    FAILURE_CODE_PATTERN,
    CheckoutRequest,
    PaymentProvider,
    ProviderStatus,
    SimulatedOutcome,
)
from bridge.billing.providers.fake import MAX_CHECKOUTS, OUTCOMES, UNKNOWN_CHECKOUT, FakePaymentProvider
from bridge.config import ConfigurationError, Settings

NOW = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
DELAY = timedelta(seconds=4)
PRODUCTION: dict[str, Any] = {
    "email_provider": "postmark",
    "postmark_server_token": SecretStr("pm"),
    "public_base_url": "https://bridge.example",
    "embedder": "bge-m3",
    "anthropic_api_key": SecretStr("test-anthropic-key-not-real"),
}


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        "recovery_code_pepper": SecretStr("y" * 32),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def request(ref: str = "fk_0123456789abcdef", outcome: SimulatedOutcome | None = None) -> CheckoutRequest:
    return CheckoutRequest(
        provider_ref=ref, amount_kes_minor=49_900, plan_code="dev_pro_monthly", simulated_outcome=outcome
    )


async def test_a_checkout_is_pending_until_the_delay_has_passed_on_the_callers_clock() -> None:
    fake = FakePaymentProvider(delay=DELAY)
    started = await fake.initiate(request(), now=NOW)
    assert started.status is ProviderStatus.PENDING
    assert started.provider_ref == "fk_0123456789abcdef"
    for elapsed in (timedelta(0), DELAY - timedelta(microseconds=1)):
        assert (await fake.query("fk_0123456789abcdef", now=NOW + elapsed)).status is ProviderStatus.PENDING
    done = await fake.query("fk_0123456789abcdef", now=NOW + DELAY)
    assert (done.status, done.amount_kes_minor, done.failure_code) == (ProviderStatus.SUCCEEDED, 49_900, None)
    # Asked again (a repeated poll), the answer is the same.
    assert await fake.query("fk_0123456789abcdef", now=NOW + timedelta(days=3)) == done


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (SimulatedOutcome.SUCCEED, ProviderStatus.SUCCEEDED, None),
        (SimulatedOutcome.FAIL, ProviderStatus.FAILED, "insufficient_funds"),
        (SimulatedOutcome.CANCEL, ProviderStatus.CANCELLED, "cancelled_by_customer"),
    ],
)
async def test_the_scripted_outcome_comes_after_the_delay(
    outcome: SimulatedOutcome, status: ProviderStatus, code: str | None
) -> None:
    fake = FakePaymentProvider(delay=DELAY)
    await fake.initiate(request(outcome=outcome), now=NOW)
    assert (await fake.query("fk_0123456789abcdef", now=NOW)).status is ProviderStatus.PENDING
    result = await fake.query("fk_0123456789abcdef", now=NOW + DELAY)
    assert (result.status, result.failure_code) == (status, code)
    assert result.amount_kes_minor == (49_900 if status is ProviderStatus.SUCCEEDED else None)


def test_failure_codes_are_codes() -> None:
    import re

    codes = [code for _, code in OUTCOMES.values() if code is not None] + [UNKNOWN_CHECKOUT]
    assert all(re.fullmatch(FAILURE_CODE_PATTERN, code) for code in codes)


async def test_an_unknown_reference_fails_rather_than_staying_pending() -> None:
    fake = FakePaymentProvider(delay=DELAY)
    result = await fake.query("fk_never_started_here", now=NOW)
    assert (result.status, result.failure_code) == (ProviderStatus.FAILED, UNKNOWN_CHECKOUT)


async def test_a_reference_starts_once_and_old_checkouts_are_forgotten_first() -> None:
    fake = FakePaymentProvider(delay=timedelta(0))
    await fake.initiate(request("fk_first_reference_x"), now=NOW)
    with pytest.raises(ValueError, match="already started"):
        await fake.initiate(request("fk_first_reference_x"), now=NOW)
    for n in range(MAX_CHECKOUTS):
        await fake.initiate(request(f"fk_bulk_{n:012d}"), now=NOW)
    assert (await fake.query("fk_first_reference_x", now=NOW)).failure_code == UNKNOWN_CHECKOUT
    assert (await fake.query(f"fk_bulk_{MAX_CHECKOUTS - 1:012d}", now=NOW)).status is ProviderStatus.SUCCEEDED


async def test_the_fake_never_verifies_a_callback() -> None:
    fake = FakePaymentProvider(delay=DELAY)
    await fake.initiate(request(), now=NOW)
    body = b'{"provider_ref": "fk_0123456789abcdef", "status": "succeeded"}'
    verdict = await fake.verify_callback({"x-signature": "anything"}, body)
    assert (verdict.verified, verdict.provider_ref, verdict.event_id) == (False, None, None)


def test_the_fake_is_a_payment_provider_and_says_it_is_simulated() -> None:
    fake: PaymentProvider = FakePaymentProvider(delay=DELAY)
    assert (fake.name, fake.simulated) == ("fake", True)
    with pytest.raises(ValueError, match="negative"):
        FakePaymentProvider(delay=timedelta(seconds=-1))


# --- PAYMENT_PROVIDER (D-36) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_and_test_run_the_fake_set_or_unset(env: str) -> None:
    for configured in (None, "fake"):
        s = settings(app_env=env, payment_provider=configured, fake_payment_delay_seconds=2.5)
        assert s.payment_effective_provider == "fake"
        provider = payment_provider_from_settings(s)
        assert isinstance(provider, FakePaymentProvider)
        assert provider.delay == timedelta(seconds=2.5)


def test_an_empty_value_is_unset() -> None:
    assert settings(app_env="test", payment_provider="").payment_provider is None


@pytest.mark.parametrize("env", ["staging", "production"])
def test_staging_and_production_refuse_the_fake_at_start_up(env: str) -> None:
    extra = PRODUCTION if env == "production" else {}
    with pytest.raises(ValidationError, match=r"PAYMENT_PROVIDER=fake is for dev and test only"):
        settings(app_env=env, payment_provider="fake", **extra)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_staging_and_production_have_no_provider_when_unset(env: str) -> None:
    extra = PRODUCTION if env == "production" else {}
    s = settings(app_env=env, **extra)
    assert s.payment_effective_provider is None
    with pytest.raises(ConfigurationError, match="no payment provider"):
        payment_provider_from_settings(s)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_the_builder_refuses_the_fake_even_past_the_settings_check(env: str) -> None:
    """Settings built without validation (``model_construct``) still never get the fake outside dev and test."""
    s = settings(app_env="test").model_copy(update={"app_env": env, "payment_provider": "fake"})
    with pytest.raises(ConfigurationError, match="only in dev and test"):
        payment_provider_from_settings(s)


def test_the_delay_is_bounded() -> None:
    for bad in (-1, 301):
        with pytest.raises(ValidationError, match="fake_payment_delay_seconds"):
            settings(app_env="test", fake_payment_delay_seconds=bad)
