"""P21: the notification preferences catalogue names the kinds the senders use (REQ-ENG-11 N18, REQ-PERS-03)."""

from __future__ import annotations

from bridge.engagements import message_notify
from bridge.models.enums import NotificationChannel
from bridge.notifications import preferences


def test_n18_email_is_offered_to_both_sides_on_by_default_and_mutable() -> None:
    """Given the catalogue, Then N18's email entry carries the kind the thread's notifier sends, on by default,
    mutable, and offered to developers and organisation members alike."""
    assert preferences.ENGAGEMENT_MESSAGE == message_notify.KIND
    entry = next(
        info
        for info in preferences.CATALOGUE
        if info.kind == message_notify.KIND and info.channel is NotificationChannel.EMAIL
    )
    assert (entry.mutable, entry.default, entry.developer_only) == (True, True, False)
