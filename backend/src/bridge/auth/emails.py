"""Auth email wording (English; Swahili later). [[COPY-REVIEW]] for G2/G5: plain transactional copy, no claims."""

from __future__ import annotations

from dataclasses import dataclass

from bridge.notifications.brand import simple_html


@dataclass(frozen=True, slots=True)
class Wording:
    subject: str
    text: str
    html: str | None = None


def verify_email(product: str, link: str, minutes: int) -> Wording:
    subject = f"Confirm your email for {product}"
    expiry = (
        f"The link works once and expires in {minutes} minutes. If you did not create an account, ignore this email."
    )
    return Wording(
        subject,
        f"Welcome to {product}.\n\nOpen this link to confirm your email address and sign in:\n{link}\n\n{expiry}",
        simple_html(
            product=product,
            subject=subject,
            paragraphs=[f"Welcome to {product}.", "Open this link to confirm your email address and sign in.", expiry],
            button=("Confirm my email", link),
        ),
    )


def login_link(product: str, link: str, minutes: int) -> Wording:
    subject = f"Your {product} sign-in link"
    expiry = (
        f"The link works once and expires in {minutes} minutes. If you did not ask for it, ignore this email; "
        "your account is safe."
    )
    return Wording(
        subject,
        f"Open this link to sign in to {product}:\n{link}\n\n{expiry}",
        simple_html(
            product=product,
            subject=subject,
            paragraphs=[f"Open this link to sign in to {product}.", expiry],
            button=("Sign in", link),
        ),
    )


def account_exists(product: str, login_url: str) -> Wording:
    subject = f"You already have a {product} account"
    first = f"Someone tried to create a {product} account with this email address, which already has one."
    return Wording(
        subject,
        f"{first}\n\nTo sign in, go to {login_url}. If this was not you, you can ignore this email.",
        simple_html(
            product=product,
            subject=subject,
            paragraphs=[first, "If this was not you, you can ignore this email."],
            button=("Sign in", login_url),
        ),
    )


def security_notice(product: str, what: str) -> Wording:
    """Sent after a password or two-step sign-in change, so a hijacked session cannot change them silently."""
    subject = f"Security change on your {product} account"
    text = (
        f"{what}\n\nIf this was you, no action is needed. If it was not, sign in with an emailed link, set a new "
        "password and contact support."
    )
    return Wording(subject, text, simple_html(product=product, subject=subject, paragraphs=text.split("\n\n")))
