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


def test_the_tracker_nudges_mutable_emails_are_offered_and_em5_never_is() -> None:
    """P28 (REQ-NOT-05; REQUIREMENTS.md §5): N05's emails (escalations, EM6, the route chosen) and N12's (a milestone
    review escalated) are settable, on by default, N12's to organisation members only; N07's EM5 is 🔒: the
    catalogue never offers it, and the nudge rules ignore preferences for it."""
    from bridge.engagements import nudges

    email = {info.kind: info for info in preferences.CATALOGUE if info.channel is NotificationChannel.EMAIL}
    for kind in (preferences.ENGAGEMENT_CONTACT, preferences.ENGAGEMENT_MILESTONES):
        assert (email[kind].mutable, email[kind].default, email[kind].developer_only) == (True, True, False)
    assert email[preferences.ENGAGEMENT_CONTACT].org_only is False  # EM6 and the route chosen reach developers
    assert email[preferences.ENGAGEMENT_MILESTONES].org_only is True
    assert "engagement.n07" not in email
    mutable = {rule.matrix_kind for rule in nudges.RULES.values() if rule.mutable and rule.email}
    assert mutable == {preferences.ENGAGEMENT_CONTACT, preferences.ENGAGEMENT_MILESTONES}
    assert {rule.matrix_kind for rule in nudges.RULES.values() if not rule.mutable} == {"engagement.n07"}
