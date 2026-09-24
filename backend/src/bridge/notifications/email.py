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

import asyncio
import re
import smtplib
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid, parseaddr
from types import MappingProxyType, TracebackType
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from bridge.config import Settings

# Postmark Email API, read 2026-09-24: https://postmarkapp.com/developer/api/email-api ("Send a single email": request
# and response fields) and https://postmarkapp.com/developer/api/overview ("HTTP response codes", "API error codes").
POSTMARK_API_URL = "https://api.postmarkapp.com"
POSTMARK_AUTH_HEADER = "X-Postmark-Server-Token"
POSTMARK_ERROR_CODE_HEADER = "X-PM-ApiErrorCode"
# ErrorCode 100 (HTTP 503, offline for maintenance) and 101 (HTTP 500, unexpected error) clear up on their own. Every
# sending code (300 invalid request, 406 inactive recipient, 10 bad token, ...) needs a person, so it is permanent.
POSTMARK_TRANSIENT_ERROR_CODES = frozenset({100, 101})
DEFAULT_TIMEOUT_SECONDS = 30.0

MAX_ADDRESS_CHARS = 254  # RFC 5321 path limit (256 octets including the angle brackets)
MAX_LOCAL_PART_CHARS = 64  # RFC 5321 section 4.5.3.1.1
MAX_SUBJECT_CHARS = 2000  # Postmark's Subject limit
MAX_ERROR_CHARS = 500

# A recipient is an RFC 5321 Mailbox restricted to what no MIME parser can reinterpret: a dot-atom local part (no
# quoted strings, no comments) at an LDH domain of two or more labels (IDNA A-labels, xn--..., are LDH). "=?" is refused
# too: an RFC 2047 encoded-word is valid atext, and a parser decodes =?utf-8?q?victim?=@example.com to a different
# address from the one checked against email_suppressions.
_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]"
_LOCAL_PART = re.compile(rf"{_ATEXT}+(?:\.{_ATEXT}+)*")
_LDH_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_DOMAIN = re.compile(rf"{_LDH_LABEL}(?:\.{_LDH_LABEL})+")
_ENCODED_WORD_START = "=?"
_ANY_ADDRESS = re.compile(r"""[^\s@<>()\[\]",;:]+@[^\s@<>()\[\]"',;:]+""")
_TAG = re.compile(r"[A-Za-z0-9._-]{1,100}")  # fits Postmark Tag and Mailpit's allowed tag characters
_HEADER_NAME = re.compile(r"[!-9;-~]+")  # RFC 5322 field-name: printable ASCII except ':'
# Unicode categories that must never reach a header: controls (incl. CR, LF, VT, FF, NEL, TAB), line and paragraph
# separators. The email package raises ValueError on some of them at send time; the others split a header visually.
_NOT_IN_A_LINE = frozenset({"Cc", "Zl", "Zp"})

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


def is_mailbox(value: str) -> bool:
    """True when ``value`` is one bare address that every consumer reads the same way (see ``_ATEXT`` above)."""
    local, at, domain = value.rpartition("@")
    return (
        bool(at)
        and len(value) <= MAX_ADDRESS_CHARS
        and len(local) <= MAX_LOCAL_PART_CHARS
        and _ENCODED_WORD_START not in value
        and _LOCAL_PART.fullmatch(local) is not None
        and _DOMAIN.fullmatch(domain) is not None
    )


def _is_one_line(value: str) -> bool:
    return len(value.splitlines()) <= 1 and not any(unicodedata.category(char) in _NOT_IN_A_LINE for char in value)


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
        if not is_mailbox(self.to):
            raise ValueError(
                "the recipient must be one bare address: a dot-atom local part at an LDH domain, with no display name,"
                f" quotes, comments or encoded-words, at most {MAX_ADDRESS_CHARS} characters"
            )
        if not self.subject or len(self.subject) > MAX_SUBJECT_CHARS or not _is_one_line(self.subject):
            raise ValueError(f"the subject must be one non-empty line of at most {MAX_SUBJECT_CHARS} characters")
        if not self.text:
            raise ValueError("a plain-text part (text) is required")
        if self.tag is not None and not _TAG.fullmatch(self.tag):
            raise ValueError("a tag is 1-100 characters from A-Z a-z 0-9 . _ -")
        for name, value in self.headers.items():
            if not _HEADER_NAME.fullmatch(name) or not _is_one_line(value):
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


# --------------------------------------------------------------------------------------------------------- Postmark


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:  # empty, HTML or otherwise not JSON
        return None
    return body if isinstance(body, dict) else None


def _postmark_error_code(response: httpx.Response, body: Mapping[str, Any] | None) -> int | None:
    value = body.get("ErrorCode") if body is not None else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    header = response.headers.get(POSTMARK_ERROR_CODE_HEADER, "").strip()
    return int(header) if header.isdigit() else None


class PostmarkEmailProvider:
    """Postmark Email API (ADR-004). ``message_stream`` picks the transactional or the broadcast stream. Opens and
    links are never tracked: link tracking rewrites every link to a Postmark domain, and emails must link only to the
    platform (AC-MAIL-5)."""

    name = "postmark"

    def __init__(
        self,
        *,
        server_token: SecretStr,
        sender: str,
        message_stream: str = "outbound",
        base_url: str = POSTMARK_API_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not server_token.get_secret_value().strip():
            raise ValueError("POSTMARK_SERVER_TOKEN is required for the Postmark adapter")
        self._token = server_token
        self._sender = sender
        self._stream = message_stream
        self._url = f"{base_url.rstrip('/')}/email"
        self._timeout = timeout
        self._client = client

    def __repr__(self) -> str:
        return f"PostmarkEmailProvider(url={self._url!r}, stream={self._stream!r})"

    def _payload(self, message: EmailMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "From": self._sender,
            "To": message.to,
            "Subject": message.subject,
            "TextBody": message.text,
        }
        if message.html is not None:
            payload["HtmlBody"] = message.html
        if message.tag is not None:
            payload["Tag"] = message.tag
        if message.headers:
            payload["Headers"] = [{"Name": name, "Value": value} for name, value in message.headers.items()]
        payload["MessageStream"] = self._stream
        payload["TrackOpens"] = False
        payload["TrackLinks"] = "None"
        return payload

    async def send(self, message: EmailMessage) -> SendResult:
        payload = self._payload(message)
        headers = {"Accept": "application/json", POSTMARK_AUTH_HEADER: self._token.get_secret_value()}
        try:
            if self._client is not None:
                response = await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(self._url, json=payload, headers=headers)
        except httpx.RequestError as exc:  # no network, DNS, TLS, timeouts, dropped connections
            detail = redact_addresses(f"Postmark unreachable: {type(exc).__name__}: {exc}")
            raise DeliveryError(detail, transient=True) from exc
        return self._result(response)

    @staticmethod
    def _result(response: httpx.Response) -> SendResult:
        status = response.status_code
        body = _json_object(response)
        code = _postmark_error_code(response, body)
        reason = str(body.get("Message") or "") if body is not None else ""
        detail = redact_addresses(
            f"Postmark HTTP {status}" + (f", code {code}" if code else "") + (f": {reason}" if reason else "")
        )
        if not response.is_success:
            # 429 and 5xx clear up on their own; other 4xx (token, sender, recipient, payload) need a person.
            transient = status == 429 or status >= 500 or code in POSTMARK_TRANSIENT_ERROR_CODES
            raise DeliveryError(detail, transient=transient, code=code)
        if body is None:  # ported: a success status with a body that is not JSON (a proxy or portal page)
            raise DeliveryError(f"Postmark HTTP {status} with an unreadable body", transient=True)
        if code:
            raise DeliveryError(detail, transient=code in POSTMARK_TRANSIENT_ERROR_CODES, code=code)
        message_id = body.get("MessageID")
        if not isinstance(message_id, str) or not message_id:
            raise DeliveryError(f"Postmark HTTP {status} accepted the call but returned no MessageID")
        return SendResult(provider=PostmarkEmailProvider.name, message_id=message_id)


# ------------------------------------------------------------------------------------------------------------ SMTP


class SmtpClient(Protocol):
    """The part of ``smtplib.SMTP`` the adapter uses (a seam for tests)."""

    def __enter__(self) -> SmtpClient: ...

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None, /
    ) -> None: ...

    def send_message(
        self, msg: MimeMessage, /, *, from_addr: str, to_addrs: Sequence[str]
    ) -> dict[str, tuple[int, bytes]]: ...


SmtpFactory = Callable[[str, int, float], SmtpClient]


def _smtp_code(exc: BaseException) -> int | None:
    code = getattr(exc, "smtp_code", None)
    return code if isinstance(code, int) and code > 0 else None


def _smtp_detail(exc: BaseException) -> str:
    code = _smtp_code(exc)
    reply = getattr(exc, "smtp_error", None)
    text = reply.decode("utf-8", "replace") if isinstance(reply, bytes) else str(exc)
    return redact_addresses(f"SMTP {type(exc).__name__}" + (f" {code}" if code else "") + (f": {text}" if text else ""))


def _refusal(refused: Mapping[str, tuple[int, bytes]]) -> tuple[int | None, str]:
    """The first refused recipient's reply code and a message without the address."""
    for code, reply in refused.values():
        text = reply.decode("utf-8", "replace") if isinstance(reply, bytes) else str(reply)
        return code, redact_addresses(f"SMTP refused the recipient ({code}: {text})")
    return None, "SMTP refused the recipient"


class SmtpEmailProvider:
    """Plain SMTP without authentication or TLS, for the Mailpit sink in dev and CI (ADR-004). ``Settings`` refuses
    it in production. ``smtplib`` blocks, so each send runs in a worker thread."""

    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        smtp_factory: SmtpFactory | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._envelope_sender = parseaddr(sender)[1]
        self._domain = self._envelope_sender.rpartition("@")[2] or "localhost"
        self._timeout = timeout
        self._smtp_factory = smtp_factory

    def __repr__(self) -> str:
        return f"SmtpEmailProvider(host={self._host!r}, port={self._port})"

    def _connect(self, host: str, port: int, timeout: float) -> SmtpClient:
        # EHLO with the sender's domain: the default, socket.getfqdn(), can wait on a reverse DNS lookup.
        return smtplib.SMTP(host, port, local_hostname=self._domain, timeout=timeout)

    def _build(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self._sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime["Date"] = formatdate(usegmt=True)
        mime["Message-ID"] = make_msgid(domain=self._domain)
        if message.tag is not None:
            mime["X-Tags"] = message.tag  # Mailpit tags messages from X-Tags (mailpit.axllent.org/docs/usage/tagging/)
        for name, value in message.headers.items():
            mime[name] = value
        mime.set_content(message.text)
        if message.html is not None:
            mime.add_alternative(message.html, subtype="html")
        return mime

    def _deliver(self, mime: MimeMessage, recipient: str) -> None:
        connect = self._smtp_factory or self._connect
        try:
            with connect(self._host, self._port, self._timeout) as smtp:
                # The envelope is explicit: send_message would otherwise re-derive it from the parsed (and RFC 2047
                # decoded) headers, which need not be the address that was checked against email_suppressions.
                refused = smtp.send_message(mime, from_addr=self._envelope_sender, to_addrs=[recipient])
        # Order matters (as in reminder/notify.py): every smtplib exception is also an OSError, so the generic network
        # clause comes last.
        except smtplib.SMTPRecipientsRefused as exc:
            code, detail = _refusal(exc.recipients)
            raise DeliveryError(detail, code=code) from exc
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as exc:
            raise DeliveryError(_smtp_detail(exc), transient=True, code=_smtp_code(exc)) from exc
        except smtplib.SMTPException as exc:
            code = _smtp_code(exc)
            # SMTP 4xx means "try again later" by definition; 5xx (or no code) is permanent.
            raise DeliveryError(_smtp_detail(exc), transient=code is not None and 400 <= code < 500, code=code) from exc
        except OSError as exc:  # DNS, no network, connection refused, timeouts
            raise DeliveryError(f"SMTP unreachable: {type(exc).__name__}", transient=True) from exc
        if refused:
            code, detail = _refusal(refused)
            raise DeliveryError(detail, code=code)

    async def send(self, message: EmailMessage) -> SendResult:
        mime = self._build(message)
        await asyncio.to_thread(self._deliver, mime, message.to)
        return SendResult(provider=self.name, message_id=str(mime["Message-ID"]).strip("<>"))


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


# ------------------------------------------------------------------------------------------------------- Selection


def provider_from_settings(settings: Settings) -> EmailProvider:
    """The adapter named by ``EMAIL_PROVIDER``. Fails closed: Postmark needs its token and is never used under
    ``APP_ENV=test`` (AC-SEC-5); the in-memory fake is refused in staging and production, where mail must go out."""
    choice = settings.email_provider
    if choice == "postmark":
        if settings.app_env == "test":
            raise ValueError("EMAIL_PROVIDER=postmark is not allowed when APP_ENV=test (AC-SEC-5); use smtp or fake")
        token = settings.postmark_server_token
        if token is None:
            raise ValueError("POSTMARK_SERVER_TOKEN is required when EMAIL_PROVIDER=postmark")
        return PostmarkEmailProvider(
            server_token=token, sender=settings.email_from, message_stream=settings.postmark_message_stream
        )
    if choice == "smtp":
        return SmtpEmailProvider(host=settings.smtp_host, port=settings.smtp_port, sender=settings.email_from)
    if settings.app_env in ("staging", "production"):
        raise ValueError(f"EMAIL_PROVIDER=fake is not allowed when APP_ENV={settings.app_env}")
    return FakeEmailProvider()
