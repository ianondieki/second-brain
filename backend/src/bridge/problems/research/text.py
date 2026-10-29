"""Text rules shared by the research agent's loaders and checks (REQ-RES-01).

``collapse`` is the P11 operating rule of revision 0005 (``REQ-SCOUT-01`` card), hardened after the P11 review
(MAJOR 2): the text is NFKC-normalised first (compatibility forms fold: a non-breaking hyphen U+2011 becomes U+2010,
full-width letters become ASCII, a non-breaking space a space), then every run of whitespace becomes one space and
the text is trimmed. ``has_control`` then refuses anything invisible or steering that is left: C0 and C1 controls
(NUL, U+0001-U+001F, U+007F-U+009F) and every format character (Unicode category Cf: the soft hyphen U+00AD, zero-width
spaces and joiners, bidi overrides and isolates such as U+202E, the byte-order mark) and every other
default-ignorable code point (fix round 2: U+034F, variation selectors, Hangul fillers, the braille blank). Such a
character could hide a name from the D-45 detection (``Safari\\u200bcom``) or reorder a title on screen, so a text
carrying one is refused, never repaired. ``non_latin`` refuses look-alike letters from other scripts in a card's
text. The saved excerpts are unchanged by NFKC (checked in the tests), so their quotes are still compared
Unicode-exact after collapsing: curly apostrophes and en dashes are never folded (research note).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_WHITESPACE: Final = re.compile(r"\s+")
_C0_C1: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Unicode's Default_Ignorable_Code_Point property (DerivedCoreProperties.txt, Unicode 15/16; Python's unicodedata has
# no accessor), plus U+2800 BRAILLE PATTERN BLANK, which renders as a blank letter-width space. Many are not Cf (the
# combining grapheme joiner U+034F and the variation selectors are Mn; the Hangul fillers are Lo; U+2065 and
# U+FFF0-U+FFF8 are unassigned), and NFKC leaves them all as they are: each could hide a name (P11 re-review MINOR 1).
_IGNORABLE: Final = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f"
    "\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0000-\U000e0fff]"
)


def normalise(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


def collapse(value: str) -> str:
    """NFKC, then every run of whitespace as one space, trimmed."""
    return _WHITESPACE.sub(" ", normalise(value)).strip()


def invisible(char: str) -> bool:
    """A format (Cf) or default-ignorable character, or the braille blank: nothing a reader sees."""
    return unicodedata.category(char) == "Cf" or _IGNORABLE.match(char) is not None


def has_control(value: str) -> bool:
    """Whether ``value`` holds a C0 or C1 control, a format (Cf) character or a default-ignorable one. Checked on the
    text as given: NFKC maps no character into those sets (tested over every code point), so the NFKC form holds one
    exactly when the text does."""
    return _C0_C1.search(value) is not None or any(invisible(c) for c in value)


def non_latin(value: str) -> bool:
    """Whether ``value`` holds a letter outside the Latin script, a combining mark or a non-ASCII digit (after NFKC,
    which folds full-width forms). A card's own text is English or Swahili: a Cyrillic or Greek look-alike
    ("S\u0430faricom" with U+0430) would hide a name from the D-45 detection, so such text is refused (P11 re-review
    MINOR 1; simpler and stricter than a confusables skeleton). Punctuation, symbols and spaces pass."""
    for char in normalise(value):
        category = unicodedata.category(char)
        if category.startswith("L") and not unicodedata.name(char, "").startswith("LATIN"):
            return True
        if category.startswith("M") or (category == "Nd" and not "0" <= char <= "9"):
            return True
    return False


def word_count(value: str) -> int:
    return len(collapse(value).split(" ")) if collapse(value) else 0
