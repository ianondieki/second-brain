"""REQ-REM-01 (docs/spec/09 progress reporter: factual consistency; P6 review MAJOR 1): the model's lines are used only
when every word is grounded. An allowlist, not a denylist: each word is a neutral vocabulary word or a word of the
facts; numbers (digits, cardinal and ordinal words, amounts) and dates match a fact as a whole unit (a count with its
noun and status, a milestone with its number, a day with its month); capitalised words are in the facts or are a
vocabulary word opening a sentence; anything else answers with the fixed text.

The facts of ``nudge()``: today 5 Oct 2026; 2 things need the developer; 1 engagement waits on the other party;
2 engagements at risk; 2 items overdue; next step "Sign the mutual NDA for “Till reconciler”: it was due 3 Oct 2026."
"""

from __future__ import annotations

import pytest

from bridge.reminders.nudge import DeveloperFacts, Nudge, compose_nudge
from bridge.reminders.wording import NudgeWording, check_wording
from tests.unit.llm.helpers import USER
from tests.unit.reminders.builders import DEV, MONDAY, NO_HOLIDAYS, ORG, S, days, engagement, milestone

STEP = "Sign the mutual NDA for “Till reconciler”: it was due 3 Oct 2026."


def nudge() -> Nudge:
    building = engagement(org_name="Secret Org Ltd", milestones=(milestone(days(1), deliverable="Confidential pilot"),))
    nda = engagement(
        S.NDA_PENDING,
        title="Till reconciler",
        org_name="Sacco C",
        awaiting=frozenset({DEV, ORG}),
        stage_deadline_on=days(-2),
    )
    return compose_nudge(DeveloperFacts(USER, MONDAY, (building, nda)), NO_HOLIDAYS)


def verdict(headline: str, next_step: str = STEP) -> str | None:
    return check_wording(NudgeWording(injection_suspected=False, headline=headline, next_step=next_step), nudge())


def test_the_facts_state_counts_as_units_the_checker_can_match() -> None:
    assert nudge().fact_lines == (
        "Today is 5 Oct 2026.",
        "2 things need the developer.",
        "1 engagement waits on the other party.",
        "2 engagements at risk.",
        "2 items overdue.",
        f"Suggested next step: {STEP}",
    )


@pytest.mark.parametrize(
    ("headline", "reason"),
    [
        # the reviewer's probes (P6 review, MAJOR 1)
        ("Sacco is waiting on your signature.", "invented_word"),
        ("Two things need you; Safaricom has paid you already.", "invented_word"),
        ("Twenty things need you today.", "invented_number"),
        ("Your third milestone needs you.", "invented_number"),
        ("You are owed 2026 shillings.", "invented_number"),
        ("Two things need you since 2 Oct.", "invented_date"),
        ("Submit it within a week or the agreement is cancelled.", "invented_date"),
        # more of the same kinds
        ("Two drafts need you today.", "invented_number"),  # the count is the things', not drafts'
        ("Three things need you today.", "invented_number"),
        ("Two parties need you today.", "invented_number"),
        ("Milestone 2 needs you today.", "invented_number"),
        ("Two things need you, worth KES 50,000.", "invented_number"),
        ("It was due in October.", "invented_date"),  # a month without its day
        ("Sign it by Friday.", "invented_date"),
        ("Do it tomorrow.", "invented_date"),
        ("Two things need you this morning.", "invented_date"),
        ("The engagement is off track.", "invented_status"),
        ("Two engagements are on track.", "invented_number"),
        ("Great news: your agreement is approved.", "invented_word"),
        ("Two things need you; the payment arrived.", "invented_word"),
        ("Nothing needs you today.", "invented_word"),  # a negation the facts do not hold
        ("You don't need to sign anything.", "invented_word"),
        ("Two things need you, Wanjiru.", "invented_word"),  # a name the facts do not hold
        ("Two things need YOU.", "invented_word"),  # capitalised mid-sentence and not in the facts
        ("You are 80% done.", "headline_symbol"),
        ("**Two** things need you.", "headline_symbol"),
        ("Two things need you #today.", "headline_symbol"),
    ],
)
def test_a_line_with_an_ungrounded_word_number_or_date_is_refused(headline: str, reason: str) -> None:
    assert verdict(headline) == reason


@pytest.mark.parametrize(
    "headline",
    [
        "Two things need you today, and two engagements are at risk.",
        "Today 2 things need you and 1 engagement waits on the other party.",
        "Two items are overdue, so please check your tracker now.",
        "You have two things to look at today.",
        "Please sign the mutual NDA for “Till reconciler” today.",
        "Sign the mutual NDA for Till reconciler: it was due on 3 October 2026.",
        "It's busy today: 2 things need you.",
    ],
)
def test_a_line_that_only_rewords_the_facts_is_used(headline: str) -> None:
    assert verdict(headline) is None


@pytest.mark.parametrize(
    ("step", "reason"),
    [
        ("Please sign the mutual NDA for “Till reconciler” now: it was due 3 Oct 2026.", None),
        ("Sign the mutual NDA for “Till reconciler”, which was due on 3 Oct.", None),  # the year may go
        ("Sign the mutual NDA for “Till reconciler” now.", "next_step_changed"),  # the date went
        ("Sign the mutual NDA now: it was due 3 Oct 2026.", "next_step_changed"),  # the title went
        ("Sign the mutual NDA for “Till reconciler”: it was due 4 Oct 2026.", "invented_date"),
        ("Sign the mutual NDA for “Till reconciler”: it was due 3 Oct 2025.", "invented_date"),
        ("Sign the mutual NDA for “Other thing”: it was due 3 Oct 2026.", "invented_word"),
        ("Submit the NDA for “Till reconciler” by 3 Oct 2026.", "invented_word"),  # "submit" is not in these facts
        ("Sign milestone 1 of “Till reconciler” by 3 Oct 2026.", "invented_number"),  # no milestone in the facts
    ],
)
def test_the_next_step_keeps_its_units_and_adds_none(step: str, reason: str | None) -> None:
    assert verdict("Two things need you today.", step) == reason


@pytest.mark.parametrize("space", ["\u2028", "\u2029", "\u00a0", "\t", "\u3000", "\u200b"])
def test_every_whitespace_other_than_a_space_is_refused(space: str) -> None:
    assert verdict(f"Two things{space}need you today.") == "headline_not_one_line"
