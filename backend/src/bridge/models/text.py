"""One-line plain text: the one rule the database's CHECKs and the API's validators share (revision 0013; the P27-M
security review).

A one-line field (a recommendation's note, a declaration's evidence title, a KECOBO or KIPI reference) holds at least
one character other than the ASCII space, and none of:

- control characters (C0, DEL and C1: U+0000 to U+001F, U+007F to U+009F), so no tab or line break;
- Unicode format characters that hide, join or reorder text (Cf): the soft hyphen U+00AD, the Arabic letter mark
  U+061C, the Mongolian vowel separator U+180E, U+200B to U+200F (zero-width space, joiners, LRM, RLM), U+202A to
  U+202E (bidirectional embeddings and overrides), U+2060 to U+206F (word joiner, invisible operators, bidirectional
  isolates U+2066 to U+2069, deprecated format characters), U+FEFF (the byte order mark), U+FFF9 to U+FFFB (interlinear
  annotation) and the tag characters U+E0001 to U+E007F;
- every space but the ASCII one (Zs: U+00A0 no-break space, U+1680, U+2000 to U+200A, U+202F, U+205F, U+3000) and the
  line and paragraph separators U+2028 and U+2029.

``FORBIDDEN_TEXT_CHARS`` is written once, in escapes that PostgreSQL's regular expressions (ARE) and Python's ``re``
read alike, so the CHECKs (``one_line_sql``, ``reference_sql``; revision 0013 restates them verbatim) and the API
(``is_one_line``) refuse exactly the same strings.
"""

from __future__ import annotations

import re
from typing import Final

FORBIDDEN_TEXT_CHARS: Final = (
    r"[\u0000-\u001F\u007F-\u009F\u00A0\u00AD\u061C\u1680\u180E\u2000-\u200F\u2028-\u202F\u205F-\u206F\u3000\uFEFF"
    r"\uFFF9-\uFFFB\U000E0001-\U000E007F]"
)
NOT_BLANK: Final = "[^ ]"  # a character other than the ASCII space (every other space is forbidden)

_FORBIDDEN: Final = re.compile(FORBIDDEN_TEXT_CHARS)
_NOT_BLANK: Final = re.compile(NOT_BLANK)


def one_line_sql(column: str, max_chars: int) -> str:
    """The CHECK expression of a required one-line column of at most ``max_chars`` characters."""
    return f"{column} ~ '{NOT_BLANK}' AND char_length({column}) <= {max_chars} AND {column} !~ '{FORBIDDEN_TEXT_CHARS}'"


def reference_sql(column: str) -> str:
    """The CHECK expression of an optional one-line column whose length its varchar type bounds."""
    return f"{column} IS NULL OR ({column} ~ '{NOT_BLANK}' AND {column} !~ '{FORBIDDEN_TEXT_CHARS}')"


def is_one_line(value: str, max_chars: int) -> bool:
    """Whether ``value`` passes the one-line CHECK as it is (the API strips the ends first, then asks)."""
    return len(value) <= max_chars and bool(_NOT_BLANK.search(value)) and not _FORBIDDEN.search(value)


__all__ = ["FORBIDDEN_TEXT_CHARS", "NOT_BLANK", "is_one_line", "one_line_sql", "reference_sql"]
