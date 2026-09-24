"""Auth email wording (English; Swahili later). [[COPY-REVIEW]] for G2/G5: plain transactional copy, no claims."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Wording:
    subject: str
    text: str


def verify_email(product: str, link: str, minutes: int) -> Wording:
    return Wording(
        f"Confirm your email for {product}",
        f"Welcome to {product}.\n\nOpen this link to confirm your email address and sign in:\n{link}\n\n"
        f"The link works once and expires in {minutes} minutes. If you did not create an account, ignore this email.",
    )


def login_link(product: str, link: str, minutes: int) -> Wording:
    return Wording(
        f"Your {product} sign-in link",
        f"Open this link to sign in to {product}:\n{link}\n\n"
        f"The link works once and expires in {minutes} minutes. If you did not ask for it, ignore this email; "
        "your account is safe.",
    )


def account_exists(product: str, login_url: str) -> Wording:
    return Wording(
        f"You already have a {product} account",
        f"Someone tried to create a {product} account with this email address, which already has one.\n\n"
        f"To sign in, go to {login_url}. If this was not you, you can ignore this email.",
    )
