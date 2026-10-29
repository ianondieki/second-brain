"""Developer handles (REQ-AUTH-01): the pseudonym an organisation sees until INTEREST_CONFIRMED (docs/spec/06 6.1).

A handle is random and never derived from personal data: ``dev-`` and eight lowercase Crockford base32 characters
(digits and letters without i, l, o and u, so it reads and types unambiguously), about 40 bits. ``new_handle`` takes
no argument, so neither the display name nor the email address can reach it. Signup gives each developer profile one
(``service.create_account``, retrying a taken handle); the developer neither chooses nor edits it (``bridge_app`` holds
no UPDATE on ``developer_profiles.handle``), and every registered version carries it as ``owner_handle``
(``proposal_versions_guard``).

Until this module, the handle was the display name slugged (``"Achieng Otieno"`` → ``achieng-otieno-2b2356``), which
named the developer on every Tier-1 surface (THREAT_MODEL §5).
"""

from __future__ import annotations

import re
import secrets
from random import Random
from typing import Final

PREFIX: Final = "dev-"
ALPHABET: Final = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lower case
LENGTH: Final = 8
PATTERN: Final = re.compile(rf"{PREFIX}[{ALPHABET}]{{{LENGTH}}}")

# The operating system's CSPRNG (what ``secrets.choice`` uses); a test may replace it with a seeded ``Random``.
_rng: Random = secrets.SystemRandom()


def new_handle() -> str:
    """A fresh random handle. It may already be taken: the caller retries on the unique constraint."""
    return PREFIX + "".join(_rng.choice(ALPHABET) for _ in range(LENGTH))
