"""One line of plain text a person typed: a recommendation's note, a declaration's evidence title and a developer's
KECOBO and KIPI references (P27; revision 0013's CHECKs behind them: not blank, a length cap, no control character).

Refused (``ValueError`` naming the rule, never the text), never removed or rewritten silently, so what is stored is
what was typed and what the database's rule accepts: a control character (Unicode Cc: line breaks and tabs included,
the text is one line), a format character (Cf: zero-width spaces and joiners U+200B to U+200F, the bidi embeddings and
overrides U+202A to U+202E and isolates U+2066 to U+2069, the byte-order mark U+FEFF), a space other than the ASCII
space (Zs: the no-break space included), the line and paragraph separators, and surrogate or private-use characters
(the security review of revision 0013). Then trimmed of ASCII spaces; nothing left is no text.
"""

from __future__ import annotations

import unicodedata
from typing import Final

REFUSED: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
RULE: Final = "one line of plain text: no line break, control or format character and no space but the ASCII space"


def is_plain(text: str) -> bool:
    """Whether every character of ``text`` may be stored (the rule above; the ASCII space is the one space)."""
    for char in text:
        category = unicodedata.category(char)
        if category in REFUSED or (category == "Zs" and char != " "):
            return False
    return True


def one_line(value: str | None, limit: int) -> str | None:
    """``value`` as stored: trimmed of ASCII spaces, None when nothing is left; ``ValueError`` when it breaks a
    rule."""
    if value is None:
        return None
    if not is_plain(value):
        raise ValueError(RULE)
    text = value.strip(" ")
    if not text:
        return None
    if len(text) > limit:
        raise ValueError(f"at most {limit} characters")
    return text
