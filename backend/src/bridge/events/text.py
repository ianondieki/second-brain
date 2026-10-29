"""An event's text and links, cleaned before they are stored (REQ-DEV-02; D-60; the 0010 security review's MINOR).

Everything a poster writes is shown to developers once staff publish it, so it is made plain first, as the research
agent's texts are (``bridge.problems.research.text``): NFKC (compatibility forms fold: a full-width letter becomes
ASCII, a non-breaking space a space), then every format character (Unicode category Cf: bidi overrides, zero-width
spaces and joiners, the byte-order mark) and every other default-ignorable one is removed. A one-line field (the title,
the venue) then has its whitespace collapsed; the description keeps its line breaks (at most one blank line in a row)
and its tabs. A control character left after that (``\\x07``, ``\\x1b``, a C1 control) refuses the field
(``control_character``): it is never repaired silently. A title, venue or description that is empty after cleaning is
``blank``; one over its length (revision 0010's CHECKs: 120, 160 and 1,000 characters) ``too_long``.

A link (the join address of an online event, the event's own page) is an https URL on an ASCII host with no user
info, whitespace or control character, of at most 400 characters (``app_research_source_is_valid``'s rule, revision
0010's CHECK); anything else is ``invalid_url``. Errors name the field and a code, never the refused text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Final

from bridge.errors import ApiError
from bridge.events.models import DESCRIPTION_MAX_CHARS, TITLE_MAX_CHARS, URL_MAX_CHARS, VENUE_MAX_CHARS
from bridge.problems.research.text import invisible
from bridge.proposals.sanitise import FieldError

MAX_CHARS: Final[Mapping[str, int]] = {
    "title": TITLE_MAX_CHARS,
    "venue": VENUE_MAX_CHARS,
    "description": DESCRIPTION_MAX_CHARS,
}
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_BLOCK_CONTROL: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # a description keeps tab and line feed
_WHITESPACE: Final = re.compile(r"\s+")
_TRAILING: Final = re.compile(r"[^\S\n]+\n")
_BLANK_LINES: Final = re.compile(r"\n{3,}")
_URL: Final = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/\S*)?")

# [[COPY-REVIEW]] the field sentences of a refused event (shown next to the field; never the refused text).
MESSAGES: Final[Mapping[str, str]] = {
    "blank": "Write this part of the event.",
    "control_character": "Remove the hidden or control characters from this text.",
    "invalid_url": "Use a full https:// address of at most 400 characters, such as https://example.com/event.",
    "unknown_county": "Choose a county from the list.",
    "start_past": "Choose a start time that has not passed.",
    "end_before_start": "The event must end after it starts.",
    "span_too_long": "An event lasts at most 3 days.",
    "join_url_required": "Add the address people join the online event at.",
    "venue_required": "Add the venue of the event.",
    "county_required": "Choose the county of the venue.",
    "online_has_place": "An online event has no venue or county.",
    "venue_has_join_url": "An event at a venue has no join address.",
}
TOO_LONG: Final = "Keep this to {limit} characters or fewer."
INVALID: Final = "Some details of the event need attention."


def error(field: str, code: str) -> FieldError:
    if code == "too_long":
        return FieldError(field, code, TOO_LONG.format(limit=MAX_CHARS[field]))
    return FieldError(field, code, MESSAGES[code])


def invalid(errors: Sequence[FieldError]) -> ApiError:
    body = [{"field": e.field, "code": e.code, "message": e.message} for e in errors]
    return ApiError(422, "invalid_event", INVALID, errors=body)


def visible(value: str) -> str:
    """NFKC, then without format (Cf) and other default-ignorable characters."""
    return "".join(char for char in unicodedata.normalize("NFKC", value) if not invisible(char))


def one_line(value: str) -> str:
    """A one-line field: visible characters, whitespace collapsed, trimmed."""
    return _WHITESPACE.sub(" ", visible(value)).strip()


def block(value: str) -> str:
    """The description: visible characters, line breaks as ``\\n``, no trailing spaces on a line, at most one blank
    line in a row, trimmed."""
    text = visible(value).replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def text_field(field: str, value: str, errors: list[FieldError]) -> str:
    """``value`` cleaned for ``field`` (title, venue or description); its errors appended to ``errors``."""
    cleaned = block(value) if field == "description" else one_line(value)
    control = _BLOCK_CONTROL if field == "description" else _CONTROL
    if not cleaned:
        errors.append(error(field, "blank"))
    elif control.search(cleaned):
        errors.append(error(field, "control_character"))
    elif len(cleaned) > MAX_CHARS[field]:
        errors.append(error(field, "too_long"))
    return cleaned


def link(field: str, value: str | None, errors: list[FieldError]) -> str | None:
    """An optional https link cleaned (None when absent or blank); ``invalid_url`` appended when it breaks the rule."""
    if value is None:
        return None
    cleaned = visible(value).strip()
    if not cleaned:
        return None
    if (
        len(cleaned) > URL_MAX_CHARS
        or not cleaned.isascii()
        or _CONTROL.search(cleaned)
        or _URL.fullmatch(cleaned) is None
    ):
        errors.append(error(field, "invalid_url"))
    return cleaned
