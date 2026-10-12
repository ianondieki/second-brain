"""One line of plain text a person typed: a recommendation's note, a declaration's evidence title and a developer's
KECOBO and KIPI references (P27). The rule is ``bridge.models.text``'s, the one the database's CHECKs restate (revision
0013, after its security review): at least one character other than the ASCII space, a length cap, and no control
character (line breaks and tabs included: the text is one line), no format character that hides, joins or reorders
text (zero-width characters, bidi embeddings, overrides and isolates, the byte-order mark ...) and no space but the
ASCII space (the no-break space included).

ASCII spaces at the ends are trimmed; nothing left is no text. Any other refused character, wherever it is, is refused
(``ValueError`` naming the rule, never the text), never removed or rewritten silently: what is stored is what was
typed.
"""

from __future__ import annotations

from typing import Final

from bridge.models.text import is_one_line

RULE: Final = "one line of plain text: no line break, control or format character and no space but the ASCII space"


def one_line(value: str | None, limit: int) -> str | None:
    """``value`` as stored: trimmed of ASCII spaces, None when nothing is left; ``ValueError`` when it breaks a
    rule."""
    if value is None:
        return None
    text = value.strip(" ")
    if not text:
        return None
    if len(text) > limit:
        raise ValueError(f"at most {limit} characters")
    if not is_one_line(text, limit):
        raise ValueError(RULE)
    return text
