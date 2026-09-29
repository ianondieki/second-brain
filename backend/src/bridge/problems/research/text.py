"""Text rules shared by the research agent's loaders and checks (REQ-RES-01).

``collapse`` is the P11 operating rule of revision 0005 (``REQ-SCOUT-01`` card): every run of whitespace (newlines,
tabs, non-breaking spaces) in model output becomes one space before ``app_create_research_candidate``, which refuses
control characters. What is left of a control character afterwards (NUL, U+0001-U+0008, U+000E-U+001F, U+007F, and
the C1 range U+0080-U+009F, which Python does not count as whitespace) refuses the text. Quotes are compared
Unicode-exact after collapsing only: curly apostrophes and en dashes are never folded (research note).
"""

from __future__ import annotations

import re
from typing import Final

_WHITESPACE: Final = re.compile(r"\s+")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def collapse(value: str) -> str:
    """Every run of whitespace as one space, trimmed."""
    return _WHITESPACE.sub(" ", value).strip()


def has_control(value: str) -> bool:
    return _CONTROL.search(value) is not None


def word_count(value: str) -> int:
    return len(collapse(value).split(" ")) if collapse(value) else 0
