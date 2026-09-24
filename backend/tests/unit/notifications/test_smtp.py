"""REQ-NOT-01: the SMTP adapter (Mailpit in dev and CI). The classification table is ported from
``reminder/notify.py`` ``send_email``: disconnects, connect errors and ``OSError`` (DNS, no network, timeouts) are
transient; any other SMTP error is transient only for a 4xx reply code; refused recipients are permanent.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import smtplib
import socket
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from types import TracebackType
from typing import Any

import pytest

from bridge.notifications.email import DeliveryError, EmailMessage, SendResult, SmtpEmailProvider

SENDER = "Bridge <no-reply@bridge.test>"
ADDRESS = "dev@example.com"


@dataclass
class FakeSmtp:
    """Stands in for ``smtplib.SMTP``: records what was sent and raises what the test scripts."""

    on_connect: BaseException | None = None
    on_send: BaseException | None = None
    refused: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    sent: list[MimeMessage] = field(default_factory=list)
    connections: list[tuple[str, int, float]] = field(default_factory=list)

    def connect(self, host: str, port: int, timeout: float) -> FakeSmtp:
        self.connections.append((host, port, timeout))
        if self.on_connect is not None:
            raise self.on_connect
        return self

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    def send_message(self, msg: MimeMessage) -> dict[str, tuple[int, bytes]]:
        if self.on_send is not None:
            raise self.on_send
        self.sent.append(msg)
        return self.refused


def message(**overrides: Any) -> EmailMessage:
    values: dict[str, Any] = {"to": ADDRESS, "subject": "Your proposal", "text": "Hello"}
    values.update(overrides)
    return EmailMessage(**values)


def provider(fake: FakeSmtp) -> SmtpEmailProvider:
    return SmtpEmailProvider(host="mailpit", port=1025, sender=SENDER, timeout=7.0, smtp_factory=fake.connect)


async def test_send_builds_a_multipart_message_with_tag_and_headers() -> None:
    fake = FakeSmtp()
    full = message(html="<p>Hello</p>", tag="em2", headers={"List-Unsubscribe": "<https://bridge.test/u/1>"})
    result = await provider(fake).send(full)

    assert fake.connections == [("mailpit", 1025, 7.0)]
    [sent] = fake.sent
    assert sent["From"] == SENDER
    assert sent["To"] == ADDRESS
    assert sent["Subject"] == "Your proposal"
    assert sent["Date"]
    assert sent["X-Tags"] == "em2"  # Mailpit tags messages from X-Tags (mailpit.axllent.org/docs/usage/tagging/)
    assert sent["List-Unsubscribe"] == "<https://bridge.test/u/1>"
    assert sent.get_content_type() == "multipart/alternative"
    text_part = sent.get_body(("plain",))
    html_part = sent.get_body(("html",))
    assert text_part is not None
    assert html_part is not None
    assert isinstance(text_part, MimeMessage)
    assert isinstance(html_part, MimeMessage)
    assert text_part.get_content().strip() == "Hello"
    assert html_part.get_content().strip() == "<p>Hello</p>"
    assert result == SendResult(provider="smtp", message_id=sent["Message-ID"].strip("<>"))
    assert result.message_id.endswith("@bridge.test")


async def test_a_text_only_message_is_a_single_plain_part_without_tags() -> None:
    fake = FakeSmtp()
    await provider(fake).send(message())
    [sent] = fake.sent
    assert sent.get_content_type() == "text/plain"
    assert "X-Tags" not in sent


@pytest.mark.parametrize(
    ("stage", "error", "transient", "code"),
    [
        pytest.param("connect", ConnectionRefusedError(10061, "refused"), True, None, id="connection-refused"),
        pytest.param("connect", TimeoutError("timed out"), True, None, id="timeout"),
        pytest.param("connect", socket.gaierror(11001, "getaddrinfo failed"), True, None, id="dns"),
        pytest.param("connect", smtplib.SMTPConnectError(554, b"no service"), True, 554, id="connect-error"),
        pytest.param("send", smtplib.SMTPServerDisconnected("gone"), True, None, id="disconnected"),
        pytest.param("send", smtplib.SMTPResponseException(451, b"4.3.0 try later"), True, 451, id="4xx-reply"),
        pytest.param("send", smtplib.SMTPSenderRefused(452, b"4.3.1 full", SENDER), True, 452, id="4xx-sender"),
        pytest.param("send", smtplib.SMTPDataError(554, b"5.7.1 rejected"), False, 554, id="5xx-data"),
        pytest.param("send", smtplib.SMTPSenderRefused(550, b"5.7.1 denied", SENDER), False, 550, id="5xx-sender"),
        pytest.param("send", smtplib.SMTPHeloError(501, b"bad helo"), False, 501, id="5xx-helo"),
        pytest.param("send", smtplib.SMTPNotSupportedError("no SMTPUTF8"), False, None, id="no-reply-code"),
        pytest.param(
            "send",
            smtplib.SMTPRecipientsRefused({ADDRESS: (550, b"5.1.1 <dev@example.com> unknown")}),
            False,
            550,
            id="recipient-refused-5xx",
        ),
        pytest.param(
            "send",
            smtplib.SMTPRecipientsRefused({ADDRESS: (450, b"4.2.1 busy")}),
            False,
            450,
            id="recipient-refused-4xx-is-permanent-as-in-notify",
        ),
    ],
)
async def test_smtp_errors_are_classified(stage: str, error: BaseException, transient: bool, code: int | None) -> None:
    fake = FakeSmtp(on_connect=error) if stage == "connect" else FakeSmtp(on_send=error)
    with pytest.raises(DeliveryError) as info:
        await provider(fake).send(message())
    assert info.value.transient is transient
    assert info.value.code == code
    assert ADDRESS not in str(info.value)


async def test_a_partly_refused_send_is_permanent() -> None:
    fake = FakeSmtp(refused={ADDRESS: (550, b"5.1.1 unknown")})
    with pytest.raises(DeliveryError) as info:
        await provider(fake).send(message())
    assert info.value.transient is False
    assert info.value.code == 550
    assert ADDRESS not in str(info.value)


class SmtpStub:
    """A minimal SMTP server on loopback, enough for smtplib: EHLO, MAIL, RCPT, DATA, QUIT."""

    def __init__(self) -> None:
        self.messages: list[bytes] = []
        self.envelopes: list[list[bytes]] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"220 stub ESMTP\r\n")
        envelope: list[bytes] = []
        data: list[bytes] | None = None
        while line := await reader.readline():
            if data is not None:
                if line == b".\r\n":
                    self.messages.append(b"".join(data))
                    self.envelopes.append(envelope)
                    envelope, data = [], None
                    writer.write(b"250 2.0.0 queued\r\n")
                else:
                    data.append(line[1:] if line.startswith(b"..") else line)
                continue
            verb = line[:4].upper()
            if verb == b"EHLO":
                writer.write(b"250-stub\r\n250 8BITMIME\r\n")
            elif verb in {b"MAIL", b"RCPT"}:
                envelope.append(line.strip().lower())  # smtplib sends lower-case verbs
                writer.write(b"250 2.1.0 ok\r\n")
            elif verb == b"DATA":
                data = []
                writer.write(b"354 end with <CRLF>.<CRLF>\r\n")
            elif verb == b"QUIT":
                writer.write(b"221 2.0.0 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 ok\r\n")
            await writer.drain()
        writer.close()


async def test_round_trip_through_a_loopback_smtp_server() -> None:
    stub = SmtpStub()
    server = await asyncio.start_server(stub.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        smtp = SmtpEmailProvider(host="127.0.0.1", port=port, sender=SENDER, timeout=10.0)
        result = await smtp.send(message(html="<p>Habari</p>", tag="em7"))

    [raw] = stub.messages
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    assert parsed["To"] == ADDRESS
    assert parsed["X-Tags"] == "em7"
    assert parsed["Message-ID"].strip("<>") == result.message_id
    assert parsed.get_content_type() == "multipart/alternative"
    assert stub.envelopes == [[b"mail from:<no-reply@bridge.test>", b"rcpt to:<dev@example.com>"]]


async def test_a_closed_port_is_a_transient_failure() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # bound but not listening: connecting is refused
        smtp = SmtpEmailProvider(host="127.0.0.1", port=port, sender=SENDER, timeout=5.0)
        with pytest.raises(DeliveryError) as info:
            await smtp.send(message())
    assert info.value.transient is True
