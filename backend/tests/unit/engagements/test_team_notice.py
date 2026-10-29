"""REQ-ENG-15 (P27, N30): the assignee's in-app title names who assigned and the idea, within the bell's 200
characters, on one line."""

from __future__ import annotations

from bridge.engagements.team import ASSIGNED_TITLE, assigned_title, default_title, first_role
from bridge.models.enums import OrgRole
from bridge.notifications.in_app import MAX_TITLE_CHARS


def test_the_title_names_who_assigned_and_the_idea() -> None:
    assert assigned_title("Amina Otieno", "Cold-chain alerts") == 'Amina Otieno assigned you "Cold-chain alerts"'
    assert ASSIGNED_TITLE.format(who="A", title="B") == 'A assigned you "B"'


def test_a_long_title_is_shortened_to_the_bell() -> None:
    title = assigned_title("Amina Otieno", "x" * 400)
    assert len(title) == MAX_TITLE_CHARS
    assert title.startswith("Amina Otieno assigned you")
    assert title.endswith('…"')


def test_line_breaks_never_reach_the_bell() -> None:
    assert "\n" not in assigned_title("Amina\nOtieno", "Cold\nchain")


def test_the_team_sheet_names_a_member_by_their_first_triage_role() -> None:
    assert first_role([OrgRole.REVIEWER, OrgRole.ADMIN]) is OrgRole.ADMIN
    assert first_role([OrgRole.SIGNATORY, OrgRole.REVIEWER]) is OrgRole.SIGNATORY
    assert first_role([OrgRole.FINANCE, OrgRole.VIEWER]) is None


def test_a_niche_default_s_title_names_the_idea_within_the_bell() -> None:
    """REQ-TEN-02 (P28 track C): N30 for an assignment by the organisation's niche default."""
    assert default_title("Cold-chain alerts") == 'Assigned to you as the niche\'s default reviewer: "Cold-chain alerts"'
    long = default_title("x" * 400)
    assert len(long) == MAX_TITLE_CHARS
    assert long.endswith('…"')
    assert "\n" not in default_title("Cold\nchain")
