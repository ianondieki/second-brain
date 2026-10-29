"""REQ-NOT-01: an ``EmailMessage`` has exactly one recipient and cannot smuggle more in through headers, because
``email_suppressions`` is checked per address before every send."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.notifications.email import DeliveryError, EmailMessage, is_mailbox, redact_addresses


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
        # RFC 2047 encoded-words: checked for suppression as written, but a MIME parser decodes them to
        # victim@example.com. Both the Q and the B forms are refused.
        pytest.param("=?utf-8?q?victim?=@example.com", id="encoded-word-q"),
        pytest.param("=?utf-8?b?dmljdGlt?=@example.com", id="encoded-word-b"),
        pytest.param("dev@=?utf-8?q?example.com?=", id="encoded-word-in-domain"),
        pytest.param('"dev ops"@example.com', id="quoted-local-part"),
        pytest.param("dev(comment)@example.com", id="comment"),
        pytest.param(".dev@example.com", id="leading-dot"),
        pytest.param("dev.@example.com", id="trailing-dot"),
        pytest.param("dev..ops@example.com", id="double-dot"),
        pytest.param("d" * 65 + "@example.com", id="local-part-longer-than-64"),
        pytest.param("dev@localhost", id="single-label-domain"),
        pytest.param("dev@-example.com", id="label-starts-with-hyphen"),
        pytest.param("dev@example-.com", id="label-ends-with-hyphen"),
        pytest.param("dev@exa_mple.com", id="underscore-in-domain"),
        pytest.param("dev@example..com", id="empty-label"),
        pytest.param("dev@[127.0.0.1]", id="address-literal"),
        pytest.param("dev@exämple.com", id="unicode-domain-not-idna-ascii"),
        pytest.param("dév@example.com", id="unicode-local-part"),
        pytest.param("dev@" + "a" * 64 + ".com", id="label-longer-than-63"),
    ],
)
def test_the_recipient_must_be_one_bare_address(to: str) -> None:
    with pytest.raises(ValueError, match="recipient"):
        make(to=to)


@pytest.mark.parametrize(
    "to",
    [
        "dev@example.com",
        "o'brien+bridge@example.co.ke",
        "first.last@sub.example.io",
        "x_y-z!#$%&*/?^=`{|}~@example.com",
        "dev@xn--exmple-cua.com",
        "DEV@EXAMPLE.COM",
        "d" * 64 + "@" + "a" * 63 + ".ke",
    ],
)
def test_dot_atom_addresses_on_ldh_domains_are_accepted(to: str) -> None:
    assert make(to=to).to == to


# Everything str.splitlines() breaks on, plus other Unicode Cc (control), Zl and Zp characters: none may reach a
# header, where the email package would raise ValueError at send time or a reader could see a second line.
NOT_ONE_LINE = [
    pytest.param("\n", id="LF"),
    pytest.param("\r", id="CR"),
    pytest.param("\r\n", id="CRLF"),
    pytest.param("\x0b", id="VT"),
    pytest.param("\x0c", id="FF"),
    pytest.param("\x1c", id="FS"),
    pytest.param("\x1d", id="GS"),
    pytest.param("\x1e", id="RS"),
    pytest.param("\x85", id="NEL"),
    pytest.param("\u2028", id="LINE-SEPARATOR"),
    pytest.param("\u2029", id="PARAGRAPH-SEPARATOR"),
    pytest.param("\x00", id="NUL"),
    pytest.param("\t", id="TAB"),
    pytest.param("\x7f", id="DEL"),
    pytest.param("\x9b", id="CSI"),
]


@pytest.mark.parametrize("subject", ["", "s" * 2001])
def test_the_subject_is_non_empty_and_bounded(subject: str) -> None:
    with pytest.raises(ValueError, match="subject"):
        make(subject=subject)


@pytest.mark.parametrize("breaker", NOT_ONE_LINE)
def test_the_subject_is_one_line(breaker: str) -> None:
    with pytest.raises(ValueError, match="subject"):
        make(subject=f"Line one{breaker}Bcc: x@example.com")


@pytest.mark.parametrize("breaker", NOT_ONE_LINE)
def test_header_values_are_one_line(breaker: str) -> None:
    with pytest.raises(ValueError, match="header"):
        make(headers={"List-Unsubscribe": f"<https://bridge.test/u/1>{breaker}Bcc: x@example.com"})


@pytest.mark.parametrize("surrogate", [pytest.param("\ud800", id="high"), pytest.param("\udfff", id="low")])
@pytest.mark.parametrize(
    ("field", "match"),
    [("subject", "subject"), ("headers", "header"), ("text", "text"), ("html", "html")],
)
def test_lone_surrogates_are_refused_everywhere(field: str, match: str, surrogate: str) -> None:
    # A lone surrogate cannot be encoded as UTF-8: the adapters would raise UnicodeEncodeError at send time.
    value = f"Hello {surrogate} there"
    overrides: dict[str, Any] = {"headers": {"X-Bridge-Note": value}} if field == "headers" else {field: value}
    with pytest.raises(ValueError, match=match):
        make(**overrides)


def test_is_mailbox_is_public_for_other_modules() -> None:
    # Auth signup validates addresses with the same rule, imported from bridge.notifications.email.
    assert is_mailbox("dev@example.com")
    assert not is_mailbox("=?utf-8?q?victim?=@example.com")
    assert not is_mailbox("Dev <dev@example.com>")


def test_non_ascii_single_line_text_is_accepted() -> None:
    message = make(subject="Karibu \u2014 ombi lako limepokelewa \u2713", headers={"X-Bridge-Note": "caf\u00e9"})
    assert message.subject.endswith("\u2713")


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
