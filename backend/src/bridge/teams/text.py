"""A team-up note and a team message as the API takes them (REQ-DEV-03; revision 0011's CHECKs behind them).

Both are plain text a developer typed, made comparable first: NFKC (a full-width letter becomes ASCII, a non-breaking
space a space) and line breaks as ``\\n``. The contact-details rule of the engagement thread does not apply between
developers (D-58: they may share a phone number or a link; the report and block rules apply instead).

- A **note** (an invitation's): trimmed; empty after that is no note; at most 300 characters; line breaks and tabs
  allowed, and no other control character (Unicode Cc) or format character (Cf: bidi overrides, zero-width spaces and
  joiners, the byte-order mark), which are refused (422), never removed silently.
- A **message** body: 1 to 4,000 characters, not blank; line breaks and tabs allowed, no other control character
  (refused, 422). Format characters stay (an emoji sequence joins with one).

Errors name the rule, never the refused text.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from bridge.teams.models import MESSAGE_MAX_CHARS, NOTE_MAX_CHARS

RAW_NOTE_MAX_CHARS: Final = 2000  # before normalising: a huge note is refused unread
RAW_MESSAGE_MAX_CHARS: Final = 16_000
_KEPT: Final = frozenset("\n\t")


def _plain(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")


def _has(value: str, categories: frozenset[str]) -> bool:
    return any(char not in _KEPT and unicodedata.category(char) in categories for char in value)


def clean_note(value: str | None) -> str | None:
    """The note as stored, None for no note; ``ValueError`` (the rule broken) otherwise."""
    if value is None:
        return None
    note = _plain(value).strip()
    if not note:
        return None
    if _has(note, frozenset({"Cc", "Cf"})):
        raise ValueError("a note has no control or format characters")
    if len(note) > NOTE_MAX_CHARS:
        raise ValueError(f"a note has at most {NOTE_MAX_CHARS} characters")
    return note


def clean_message(value: str) -> str:
    """The message body as stored; ``ValueError`` (the rule broken) otherwise."""
    body = _plain(value)
    if not body.strip():
        raise ValueError("a message is not blank")
    if _has(body, frozenset({"Cc"})):
        raise ValueError("a message has no control characters but line breaks and tabs")
    if len(body) > MESSAGE_MAX_CHARS:
        raise ValueError(f"a message has at most {MESSAGE_MAX_CHARS} characters")
    return body
