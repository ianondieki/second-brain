"""SMS delivery behind one seam (REQ-PROV-04; docs/spec/06 6.4 item 8: D1 phone codes through ``SmsProvider``).

Two adapters:

- ``FakeSmsProvider`` (in memory): dev, test and CI (``SMS_PROVIDER=fake``); tests read its ``outbox``.
- ``AfricasTalkingSmsProvider``: Africa's Talking's SMS API, for staging and production once the vendor account exists
  (gate G1). No test reaches it: unit tests drive it through respx and the egress guard refuses any other connection
  (AC-SEC-5).

``sms_provider_from_settings`` fails closed: production needs the vendor adapter on a live (not sandbox) account, the
test environment may only use the fake, and the adapter needs its username and API key.

Privacy (docs/spec/08 Observability; DPA 2019): a message's number and text never reach a log line, an exception
message or a ``repr``. ``SmsError`` carries only the provider's status and a reason with phone numbers redacted.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from bridge.config import Settings

E164 = re.compile(r"\+[1-9][0-9]{6,14}")
MAX_SMS_CHARS = 160  # one GSM-7 segment: codes are short, fixed texts
MAX_ERROR_CHARS = 300
DEFAULT_TIMEOUT_SECONDS = 10.0

# Africa's Talking SMS API ("Sending messages": POST /version1/messaging, form-encoded username/to/message/from,
# ``apiKey`` header; reply ``SMSMessageData.Recipients[]`` with ``statusCode``, ``status``, ``messageId``). Confirm
# against the account's documentation at gate G1 before the first live send.
AT_LIVE_URL = "https://api.africastalking.com/version1/messaging"
AT_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"
AT_SANDBOX_USERNAME = "sandbox"
AT_ACCEPTED = frozenset({100, 101, 102})  # Processed, Sent, Queued
# InternalServerError and GatewayError clear up on their own; every other refusal (RiskHold, InvalidSenderId,
# InvalidPhoneNumber, UnsupportedNumberType, InsufficientBalance, UserInBlacklist, CouldNotRoute,
# DoNotDisturbRejection, RejectedByGateway) needs a person or a different number.
AT_TRANSIENT = frozenset({500, 501})

# Runs of 7 or more digits, possibly split by spaces, dots, hyphens or parentheses, with an optional leading "+".
_PHONE_LIKE = re.compile(r"\+?\d[\d\s().\-]{4,}\d")
_MIN_PHONE_DIGITS = 7


def redact_phones(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    """``text`` with every phone-like number replaced by ``[phone]``, cut to ``limit`` characters. Vendor errors
    often quote the recipient; this keeps numbers out of logs and error messages."""

    def replace(match: re.Match[str]) -> str:
        digits = sum(ch.isdigit() for ch in match.group())
        return "[phone]" if digits >= _MIN_PHONE_DIGITS else match.group()

    redacted = _PHONE_LIKE.sub(replace, text)
    return redacted if len(redacted) <= limit else redacted[: limit - 1] + "…"


class SmsError(Exception):
    """The provider refused the message or could not be reached. ``str()`` carries no number, text or key, so it is
    safe to log. ``transient`` marks failures that clear up on their own; ``code`` is the provider's status code."""

    def __init__(self, message: str, transient: bool = False, code: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.code = code


@dataclass(frozen=True, repr=False)
class SmsMessage:
    """One SMS to one E.164 number: a single segment of printable ASCII (validated on construction)."""

    to: str
    text: str

    def __post_init__(self) -> None:
        if not E164.fullmatch(self.to):
            raise ValueError("the recipient must be an E.164 number such as +254712345678")
        if not self.text or len(self.text) > MAX_SMS_CHARS or not (self.text.isascii() and self.text.isprintable()):
            raise ValueError(f"the text must be 1-{MAX_SMS_CHARS} printable ASCII characters on one line")

    def __repr__(self) -> str:
        return "SmsMessage(to=[phone], text=[redacted])"


@dataclass(frozen=True)
class SmsResult:
    provider: str
    message_id: str


class SmsProvider(Protocol):
    """Sends one ``SmsMessage``. A refused or failed send raises ``SmsError`` and nothing else."""

    @property
    def name(self) -> str: ...

    async def send(self, message: SmsMessage) -> SmsResult: ...


# ------------------------------------------------------------------------------------------------------------ Fake


class FakeSmsProvider:
    """In-memory provider (``SMS_PROVIDER=fake``): ``outbox`` holds what was sent and ``attempts`` counts every call.
    ``failures`` scripts the next calls: each queued ``SmsError`` is raised once, in order."""

    name = "fake"

    def __init__(self, failures: Iterable[SmsError] = ()) -> None:
        self.outbox: list[SmsMessage] = []
        self.attempts = 0
        self._failures: deque[SmsError] = deque(failures)

    def fail_next(self, *errors: SmsError) -> None:
        self._failures.extend(errors)

    async def send(self, message: SmsMessage) -> SmsResult:
        self.attempts += 1
        if self._failures:
            raise self._failures.popleft()
        self.outbox.append(message)
        return SmsResult(provider=self.name, message_id=f"fake-sms-{len(self.outbox)}")


# ------------------------------------------------------------------------------------------------ Africa's Talking


def _first_recipient(body: Any) -> dict[str, Any] | None:
    data = body.get("SMSMessageData") if isinstance(body, dict) else None
    recipients = data.get("Recipients") if isinstance(data, dict) else None
    if isinstance(recipients, list) and recipients and isinstance(recipients[0], dict):
        return recipients[0]
    return None


def _summary(body: Any) -> str:
    data = body.get("SMSMessageData") if isinstance(body, dict) else None
    message = data.get("Message") if isinstance(data, dict) else None
    return redact_phones(message, limit=120) if isinstance(message, str) else ""


class AfricasTalkingSmsProvider:
    """Africa's Talking SMS API. The ``sandbox`` username talks to the sandbox endpoint (simulator only, never a real
    phone); ``sms_provider_from_settings`` refuses it in production. ``sender_id`` is the approved alphanumeric
    sender (optional: the account's default shortcode otherwise)."""

    name = "africastalking"

    def __init__(
        self,
        *,
        username: str,
        api_key: SecretStr,
        sender_id: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not username.strip():
            raise ValueError("AFRICASTALKING_USERNAME is required for the Africa's Talking adapter")
        if not api_key.get_secret_value().strip():
            raise ValueError("AFRICASTALKING_API_KEY is required for the Africa's Talking adapter")
        self._username = username.strip()
        self._key = api_key
        self._sender_id = sender_id or None
        self._url = base_url or (AT_SANDBOX_URL if self.is_sandbox else AT_LIVE_URL)
        self._timeout = timeout
        self._client = client

    @property
    def is_sandbox(self) -> bool:
        return self._username == AT_SANDBOX_USERNAME

    def __repr__(self) -> str:
        return f"AfricasTalkingSmsProvider(url={self._url!r})"

    async def send(self, message: SmsMessage) -> SmsResult:
        form = {"username": self._username, "to": message.to, "message": message.text}
        if self._sender_id:
            form["from"] = self._sender_id
        headers = {"Accept": "application/json", "apiKey": self._key.get_secret_value()}
        try:
            if self._client is not None:
                response = await self._client.post(self._url, data=form, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(self._url, data=form, headers=headers)
        except httpx.RequestError as exc:  # no network, DNS, TLS, timeouts, dropped connections
            raise SmsError(f"Africa's Talking unreachable: {type(exc).__name__}", transient=True) from exc
        return self._result(response)

    def _result(self, response: httpx.Response) -> SmsResult:
        status = response.status_code
        if not response.is_success:
            reason = redact_phones(response.text, limit=120)
            raise SmsError(
                f"Africa's Talking HTTP {status}" + (f": {reason}" if reason else ""),
                transient=status == 429 or status >= 500,
                code=status,
            )
        try:
            body = json.loads(response.content)
        except ValueError as exc:  # a success status with a body that is not JSON (a proxy or portal page)
            raise SmsError(f"Africa's Talking HTTP {status} with an unreadable body", transient=True) from exc
        entry = _first_recipient(body)
        if entry is None:
            summary = _summary(body)
            raise SmsError("Africa's Talking accepted no recipient" + (f": {summary}" if summary else ""))
        code = entry.get("statusCode")
        if not isinstance(code, int) or isinstance(code, bool):
            raise SmsError("Africa's Talking returned no recipient status code")
        if code not in AT_ACCEPTED:
            label = entry.get("status")
            detail = f" ({redact_phones(label, limit=40)})" if isinstance(label, str) and label else ""
            raise SmsError(f"Africa's Talking status {code}{detail}", transient=code in AT_TRANSIENT, code=code)
        message_id = entry.get("messageId")
        if not isinstance(message_id, str) or not message_id:
            raise SmsError("Africa's Talking accepted the message but returned no messageId")
        return SmsResult(provider=self.name, message_id=message_id)


# ------------------------------------------------------------------------------------------------------- Selection


def sms_provider_from_settings(settings: Settings) -> SmsProvider:
    """The adapter named by ``SMS_PROVIDER``. Fails closed:

    - ``africastalking`` needs ``AFRICASTALKING_USERNAME`` and ``AFRICASTALKING_API_KEY`` and is refused when
      ``APP_ENV=test`` (tests and CI never reach the vendor, AC-SEC-5). Production refuses the sandbox account.
    - ``fake`` is refused in production, where D1 codes must reach a real phone. Staging may use it until the vendor
      account exists (gate G1).
    """
    if settings.sms_provider == "africastalking":
        if settings.app_env == "test":
            raise ValueError("SMS_PROVIDER=africastalking is not allowed when APP_ENV=test: tests and CI use the fake")
        username, key = settings.africastalking_username, settings.africastalking_api_key
        if not username or key is None:
            raise ValueError(
                "AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY are required when SMS_PROVIDER=africastalking"
            )
        if settings.app_env == "production" and username.strip() == AT_SANDBOX_USERNAME:
            raise ValueError("production needs a live Africa's Talking account, not the sandbox")
        return AfricasTalkingSmsProvider(username=username, api_key=key, sender_id=settings.africastalking_sender_id)
    if settings.app_env == "production":
        raise ValueError(
            "SMS_PROVIDER=fake is not allowed when APP_ENV=production: configure Africa's Talking (gate G1)"
        )
    return FakeSmsProvider()
