"""The ownership attestations made at each registration (docs/spec/06 6.4 item 7; REQ-PROV-04, REQ-PROV-05).

The owner confirms three statements before publishing; each registration stores one ``attestations`` row (append-only,
timed by the database) with the text version and the SHA-256 of the exact text shown, and the registration manifest
names that row. Changing any wording means a new ``VERSION``: a publish sent with an older version is refused.

[[COPY-REVIEW]] draft wording for the G2 legal review; it paraphrases the spec's three statements and makes no claim.
"""

from __future__ import annotations

import hashlib
from typing import Final

VERSION: Final = "2026-09-29.1"
STATEMENTS: Final = (
    ("created_it", "I created this proposal."),
    ("not_owned_by_employer_or_client", "It is not owned by my employer, a university or a client."),
    ("no_third_party_confidential", "It contains no confidential information that belongs to anyone else."),
)


def text_digest() -> bytes:
    """SHA-256 of the version and the three statements exactly as shown, one per line."""
    shown = "\n".join([VERSION, *(statement for _, statement in STATEMENTS)])
    return hashlib.sha256(shown.encode("utf-8")).digest()
