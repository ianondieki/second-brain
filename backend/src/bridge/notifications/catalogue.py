"""The notification choices a person can change (REQ-NOT-03 "email per preference"; docs/spec/06 6.10;
REQUIREMENTS.md §5 "Mutable").

One entry per (kind, channel) the settings page offers, with the value that holds while the person has made no
choice (``notification_preferences`` keeps explicit choices only). ``preferences.channel_enabled`` reads a missing row
as this default, and as on for a kind the catalogue does not list (the mutable notices built before it). In-app is
always on and is never a choice; the 🔒 transactional notices (approval, signatures, decline, dispute, termination)
are never listed. Add an entry here when a notice becomes a choice; the settings API serves exactly these.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from bridge.models.enums import NotificationChannel

Audience = Literal["developer", "org", "both"]


@dataclass(frozen=True, slots=True)
class Choice:
    kind: str  # notification_preferences.kind (and the notice's kind)
    channel: NotificationChannel
    default: bool  # what holds until the person chooses
    audience: Audience  # who receives it: the settings page shows the rows that apply to the person


CHOICES: Final[tuple[Choice, ...]] = (
    # N18 (REQ-ENG-11, D-57 (2)): a new message in an engagement's thread, by email (at most one per engagement per
    # 30 minutes, never the text). Mutable, on by default.
    Choice("engagement.n18", NotificationChannel.EMAIL, default=True, audience="both"),
)
BY_KEY: Final[dict[tuple[str, NotificationChannel], Choice]] = {(c.kind, c.channel): c for c in CHOICES}


def default_for(kind: str, channel: NotificationChannel) -> bool:
    """The value a (kind, channel) has while the person made no choice: the catalogue's, else on."""
    choice = BY_KEY.get((kind, channel))
    return True if choice is None else choice.default
