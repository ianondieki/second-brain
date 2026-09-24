"""Email delivery behind one seam (REQ-NOT-01, ADR-004).

``EmailProvider`` has three adapters: ``PostmarkEmailProvider`` (async httpx; staging and production),
``SmtpEmailProvider`` (Mailpit in dev and CI; stdlib ``smtplib`` in a worker thread) and ``FakeEmailProvider``
(in-memory, unit tests). No test and no ``make check`` step reaches a real provider (AC-SEC-5).
``bridge.notifications.deliveries.send_email`` wraps every send in the ``notification_deliveries`` ledger.

A failed send raises ``DeliveryError(transient, code)``, ported from ``reminder/notify.py`` (the backend never imports
``reminder/``): network errors, timeouts, HTTP 429 and 5xx and SMTP 4xx replies are transient and retried; other HTTP
4xx, SMTP 5xx and refused recipients are permanent.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

MAX_ADDRESS_CHARS = 320  # notification_deliveries.to_address
MAX_SUBJECT_CHARS = 2000  # Postmark's Subject limit
MAX_ERROR_CHARS = 500

# One bare addr-spec: no display name, no list separators, no whitespace or control characters.
_ADDRESS_CHAR = r"""[^@\s,;:<>()\[\]\\"'\x00-\x1f\x7f]"""
_SINGLE_ADDRESS = re.compile(rf"{_ADDRESS_CHAR}+@{_ADDRESS_CHAR}+")
_ANY_ADDRESS = re.compile(r"""[^\s@<>()\[\]"',;:]+@[^\s@<>()\[\]"',;:]+""")
_TAG = re.compile(r"[A-Za-z0-9._-]{1,100}")  # fits Postmark Tag and Mailpit's allowed tag characters
_HEADER_NAME = re.compile(r"[!-9;-~]+")  # RFC 5322 field-name: printable ASCII except ':'
_LINE_BREAK = re.compile(r"[\r\n\x00]")

# Set by the adapters, or able to add recipients: smtplib's send_message takes the envelope from To/Cc/Bcc (or the
# Resent-* block), which would bypass the per-address suppression check.
RESERVED_HEADERS = frozenset(
    {
        "from",
        "sender",
        "to",
        "cc",
        "bcc",
        "reply-to",
        "subject",
        "date",
        "message-id",
        "mime-version",
        "content-type",
        "content-transfer-encoding",
        "return-path",
        "x-tags",
    }
)


def redact_addresses(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    """``text`` with every email address replaced by ``[address]``, cut to ``limit`` characters. Provider errors
    often quote the recipient; this keeps addresses out of logs and ``notification_deliveries.last_error``."""
    redacted = _ANY_ADDRESS.sub("[address]", text)
    return redacted if len(redacted) <= limit else redacted[: limit - 1] + "…"


class DeliveryError(Exception):
    """A provider refused the message or could not be reached. ``str()`` carries no address, body or secret, so it
    is safe to log and to store.

    ``transient`` marks failures that clear up on their own (no network, timeouts, HTTP 429 and 5xx, SMTP 4xx); those
    are retried. ``code`` is the provider's own numeric code when it gave one (Postmark ``ErrorCode``, SMTP reply
    code). Ported from ``reminder/notify.py``."""

    def __init__(self, message: str, transient: bool = False, code: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.code = code


@dataclass(frozen=True)
class EmailMessage:
    """One rendered email to one recipient. Validated on construction, so nothing downstream can add a recipient
    (``email_suppressions`` is checked per address) or inject a header. ``headers`` becomes read-only."""

    to: str
    subject: str
    text: str
    html: str | None = None
    tag: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if len(self.to) > MAX_ADDRESS_CHARS or not _SINGLE_ADDRESS.fullmatch(self.to):
            raise ValueError(
                f"the recipient must be one bare address (local@domain), at most {MAX_ADDRESS_CHARS} chars"
            )
        if not self.subject or len(self.subject) > MAX_SUBJECT_CHARS or _LINE_BREAK.search(self.subject):
            raise ValueError(f"the subject must be one non-empty line of at most {MAX_SUBJECT_CHARS} characters")
        if not self.text:
            raise ValueError("a plain-text part (text) is required")
        if self.tag is not None and not _TAG.fullmatch(self.tag):
            raise ValueError("a tag is 1-100 characters from A-Z a-z 0-9 . _ -")
        for name, value in self.headers.items():
            if not _HEADER_NAME.fullmatch(name) or _LINE_BREAK.search(value):
                raise ValueError(f"malformed header {name!r}")
            lowered = name.lower()
            if lowered in RESERVED_HEADERS or lowered.startswith("resent-"):
                raise ValueError(f"the {name} header is set by the provider and cannot be overridden")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True)
class SendResult:
    provider: str
    message_id: str


class EmailProvider(Protocol):
    """Sends one ``EmailMessage``. A refused or failed send raises ``DeliveryError`` and nothing else."""

    @property
    def name(self) -> str: ...

    async def send(self, message: EmailMessage) -> SendResult: ...


# ------------------------------------------------------------------------------------------------------------ Fake


class FakeEmailProvider:
    """In-memory provider for unit tests (``EMAIL_PROVIDER=fake``). ``outbox`` holds what was sent and ``attempts``
    counts every call. ``failures`` scripts the next calls: each queued ``DeliveryError`` is raised once, in order,
    before sends succeed again."""

    name = "fake"

    def __init__(self, failures: Iterable[DeliveryError] = ()) -> None:
        self.outbox: list[EmailMessage] = []
        self.attempts = 0
        self._failures: deque[DeliveryError] = deque(failures)

    def fail_next(self, *errors: DeliveryError) -> None:
        self._failures.extend(errors)

    async def send(self, message: EmailMessage) -> SendResult:
        self.attempts += 1
        if self._failures:
            raise self._failures.popleft()
        self.outbox.append(message)
        return SendResult(provider=self.name, message_id=f"fake-{len(self.outbox)}")
