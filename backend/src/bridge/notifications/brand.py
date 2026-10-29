"""The branded HTML frame for short transactional emails (D-52): the auth emails get an HTML part from here, with the
same paper, bands, wordmark, sheet and button as every other email (templates/_brand.html.j2)."""

from __future__ import annotations

from typing import Final

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

PRODUCT_DEFAULT: Final = "Wazo"

_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def simple_html(
    *,
    product: str,
    subject: str,
    paragraphs: list[str],
    button: tuple[str, str] | None = None,
    help_url: str | None = None,
) -> str:
    """The HTML part of a short email: the paragraphs, one button (label, address) when there is a link."""
    return _ENV.get_template("simple.html.j2").render(
        product=product,
        subject=subject,
        paragraphs=paragraphs,
        button_label=button[0] if button else None,
        button_url=button[1] if button else None,
        settings_url=None,
        help_url=help_url,
    )
