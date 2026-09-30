"""The pieces of a person's name or email address that a pseudonymous handle must never contain (REQ-AUTH-01).

For each value: its words in lower case (Unicode), the same words folded to ASCII (``Wanjĩrũ`` → ``wanjiru``) and the
ASCII fragments the old name-derived handle kept (``[^a-z0-9]+`` split: ``Wanjĩrũ`` → ``wanj``). Pieces shorter than
three characters are left out: they occur in any text by chance.
"""

from __future__ import annotations

import re
import unicodedata

MIN_LENGTH = 3


def name_tokens(*values: str) -> set[str]:
    found: set[str] = set()
    for value in values:
        lowered = value.lower()
        folded = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")
        pieces = [*re.split(r"[\W_]+", lowered), *re.split(r"[\W_]+", folded), *re.split(r"[^a-z0-9]+", lowered)]
        found.update(piece for piece in pieces if len(piece) >= MIN_LENGTH)
    return found


def leaked(text: str, *values: str) -> list[str]:
    """The tokens of ``values`` found in ``text`` (case-insensitive), sorted; empty when none is."""
    lowered = text.lower()
    return sorted(token for token in name_tokens(*values) if token in lowered)
