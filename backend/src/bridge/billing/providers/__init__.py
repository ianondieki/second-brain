"""Payment providers behind the ``PaymentProvider`` interface (docs/spec/05; REQ-BIL-04 interface only; D-36).

``payment_provider_from_settings`` builds the one ``PAYMENT_PROVIDER`` names and fails closed: no provider in
staging and production until a real rail exists (after G4), and the fake only in dev and test.
"""

from __future__ import annotations

from datetime import timedelta

from bridge.billing.providers.base import PaymentProvider
from bridge.billing.providers.fake import FakePaymentProvider
from bridge.config import ConfigurationError, Settings


def payment_provider_from_settings(settings: Settings) -> PaymentProvider:
    """The provider for ``settings``; ``ConfigurationError`` when there is none here (checkouts then answer 503)."""
    provider = settings.payment_effective_provider
    if provider is None:
        raise ConfigurationError("no payment provider is configured here (PAYMENT_PROVIDER)")
    if provider == "fake":
        if settings.app_env not in ("dev", "test"):
            raise ConfigurationError("the fake payment provider runs only in dev and test (D-36)")
        return FakePaymentProvider(delay=timedelta(seconds=settings.fake_payment_delay_seconds))
    raise ConfigurationError("unknown payment provider (PAYMENT_PROVIDER)")
