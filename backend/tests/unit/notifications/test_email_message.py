"""REQ-NOT-01: an ``EmailMessage`` has exactly one recipient and cannot smuggle more in through headers, because
``email_suppressions`` is checked per address before every send."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.notifications.email import DeliveryError, EmailMessage, redact_addresses


def make(**overrides: Any) -> EmailMessage:
    values: dict[str, Any] = {"to": "dev@example.com", "subject": "Your proposal", "text": "Hello"}
    values.update(overrides)
    return EmailMessage(**values)


def test_a_valid_message_keeps_its_fields_and_freezes_its_headers() -> None:
    message = make(html="<p>Hello</p>", tag="em2", headers={"List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
    assert message.to == "dev@example.com"
    assert message.html == "<p>Hello</p>"
    assert message.headers == {"List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    with pytest.raises(TypeError):
        message.headers["Bcc"] = "someone@example.com"  # type: ignore[index]


def test_defaults_are_text_only_untagged_and_headerless() -> None:
    message = make()
    assert message.html is None
    assert message.tag is None
    assert dict(message.headers) == {}


@pytest.mark.parametrize(
    "to",
    [
        pytest.param("a@example.com, b@example.com", id="comma-list"),
        pytest.param("a@example.com;b@example.com", id="semicolon-list"),
        pytest.param("Dev <dev@example.com>", id="display-name"),
        pytest.param("dev.example.com", id="no-at"),
        pytest.param("dev@@example.com", id="two-at"),
        pytest.param("dev@example.com\r\nBcc: x@example.com", id="crlf-injection"),
        pytest.param("dev @example.com", id="space"),
        pytest.param("", id="empty"),
        pytest.param("d" * 310 + "@example.com", id="longer-than-320"),
    ],
)
def test_the_recipient_must_be_one_bare_address(to: str) -> None:
    with pytest.raises(ValueError, match="recipient"):
        make(to=to)


@pytest.mark.parametrize("subject", ["", "Line one\nBcc: x@example.com", "Carriage\rreturn", "s" * 2001])
def test_the_subject_is_one_non_empty_line(subject: str) -> None:
    with pytest.raises(ValueError, match="subject"):
        make(subject=subject)


def test_a_plain_text_part_is_required() -> None:
    with pytest.raises(ValueError, match="text"):
        make(text="")


@pytest.mark.parametrize("tag", ["", "em2,bcc", "em 2", "t" * 101, "em2\n"])
def test_tags_are_short_simple_labels(tag: str) -> None:
    with pytest.raises(ValueError, match="tag"):
        make(tag=tag)


@pytest.mark.parametrize(
    "name",
    ["Bcc", "cc", "To", "From", "Sender", "Reply-To", "Subject", "Message-ID", "Content-Type", "Resent-To", "X-Tags"],
)
def test_reserved_headers_cannot_be_set(name: str) -> None:
    with pytest.raises(ValueError, match="header"):
        make(headers={name: "value"})


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"X-Bad:Name": "v"}, id="colon-in-name"),
        pytest.param({"X Space": "v"}, id="space-in-name"),
        pytest.param({"X-Ok": "v\r\nBcc: x@example.com"}, id="crlf-in-value"),
        pytest.param({"": "v"}, id="empty-name"),
    ],
)
def test_malformed_headers_are_refused(headers: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="header"):
        make(headers=headers)


def test_redact_addresses_hides_addresses_and_caps_length() -> None:
    text = "Invalid 'To' address: 'Dev.Name+x@Example.co.ke'. Contact <ops@bridge.test> " + "x" * 600
    redacted = redact_addresses(text)
    assert "Example.co.ke" not in redacted
    assert "ops@bridge.test" not in redacted
    assert "[address]" in redacted
    assert len(redacted) <= 500


def test_delivery_error_carries_the_ported_classification() -> None:
    error = DeliveryError("rate limited", transient=True, code=429)
    assert str(error) == "rate limited"
    assert error.transient is True
    assert error.code == 429
    assert DeliveryError("refused").transient is False
    assert DeliveryError("refused").code is None
