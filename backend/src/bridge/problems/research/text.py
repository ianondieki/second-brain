"""Text rules shared by the research agent's loaders and checks (REQ-RES-01).

``collapse`` is the P11 operating rule of revision 0005 (``REQ-SCOUT-01`` card), hardened after the P11 review
(MAJOR 2): the text is NFKC-normalised first (compatibility forms fold: a non-breaking hyphen U+2011 becomes U+2010,
full-width letters become ASCII, a non-breaking space a space), then every run of whitespace becomes one space and
the text is trimmed. ``has_control`` then refuses anything invisible or steering that is left: C0 and C1 controls
(NUL, U+0001-U+001F, U+007F-U+009F) and every format character (Unicode category Cf: the soft hyphen U+00AD, zero-width
spaces and joiners, bidi overrides and isolates such as U+202E, the byte-order mark). Such a character could hide a
name from the D-45 detection (``Safari\\u200bcom``) or reorder a title on screen, so a text carrying one is refused,
never repaired. The saved excerpts are unchanged by NFKC (checked in the tests), so their quotes are still compared
Unicode-exact after collapsing: curly apostrophes and en dashes are never folded (research note).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_WHITESPACE: Final = re.compile(r"\s+")
_C0_C1: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def normalise(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


def collapse(value: str) -> str:
    """NFKC, then every run of whitespace as one space, trimmed."""
    return _WHITESPACE.sub(" ", normalise(value)).strip()


def has_control(value: str) -> bool:
    """Whether ``value`` holds a C0 or C1 control or a format (Cf) character. Checked on the text as given: NFKC maps
    no character into those sets (tested over every code point), so the NFKC form holds one exactly when the text
    does."""
    return _C0_C1.search(value) is not None or any(unicodedata.category(c) == "Cf" for c in value)


def word_count(value: str) -> int:
    return len(collapse(value).split(" ")) if collapse(value) else 0
