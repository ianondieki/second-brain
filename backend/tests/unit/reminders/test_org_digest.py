"""REQ-REM-02 (docs/spec/06 6.10, 6.11): the organisation's progress digest is rendered by code from fact tuples only.
AC-REM-2 ("No update from {dev} since {date}", never a percentage), the AC-MAIL-5 checks on this digest (escaped,
defanged, platform links only) and the health agreement with the developer's reminder (AC-REM-3, unit half)."""

from __future__ import annotations

import ast
import inspect
import re
from uuid import uuid4

import pytest

import bridge.reminders.org_digest as org_digest
from bridge.reminders.health import Health
from bridge.reminders.nudge import DeveloperFacts, compose_nudge
from bridge.reminders.org_digest import OrgFacts, compose_digest, period_start, render_digest
from tests.unit.reminders.builders import BASE_URL, MONDAY, NO_HOLIDAYS, ORG, M, S, days, engagement, milestone

ORG_ID = uuid4()


def facts(*engagements: object, cadence: str = "daily", today: object = MONDAY) -> OrgFacts:
    return OrgFacts(ORG_ID, "Telco A (fixture)", today, cadence, tuple(engagements))  # type: ignore[arg-type]


def test_no_update_from_the_developer_for_six_days_is_said_and_never_a_percentage() -> None:
    """AC-REM-2."""
    quiet = engagement(milestones=(milestone(days(20)),), last_developer_update_on=days(-6))
    digest = compose_digest(facts(quiet), NO_HOLIDAYS)
    message = render_digest(digest, to="org@example.com", base_url=BASE_URL)
    for part in (message.text, message.html or ""):
        assert "No update from Wanjiru since 29 Sep 2026." in part
        assert "%" not in part.replace("100%", "")  # no guessed percentage anywhere (the HTML has no width styles)
        assert "percent" not in part.lower()
    active = compose_digest(facts(engagement(last_developer_update_on=days(-1))), NO_HOLIDAYS)
    assert "No update" not in render_digest(active, to="org@example.com", base_url=BASE_URL).text


def test_the_digest_is_the_fixed_layout_filled_with_the_facts() -> None:
    building = engagement(
        milestones=(milestone(days(1)), milestone(days(30), M.PLANNED, seq=2)), last_developer_update_on=days(-6)
    )
    upcoming = engagement(
        title="Kiosk app",
        milestones=(milestone(days(9), seq=1, deliverable="Beta"), milestone(days(12), M.ACCEPTED, seq=2)),
        last_developer_update_on=MONDAY,
    )
    tagged = engagement(
        S.SUBMITTED,
        title="Farm data",
        developer_name="Otieno",
        tagged=True,
        created_on=MONDAY,
        awaiting=frozenset({ORG}),
        stage_deadline_on=days(8),
        last_developer_update_on=MONDAY,
    )
    review = engagement(
        title="Ledger",
        milestones=(milestone(days(-10), M.SUBMITTED_FOR_REVIEW, review_due_on=days(-13)),),
        awaiting=frozenset({ORG}),
        last_developer_update_on=days(-1),
    )
    digest = compose_digest(facts(building, tagged, review, upcoming, engagement(S.CLOSED)), NO_HOLIDAYS)
    message = render_digest(digest, to="org@example.com", base_url=BASE_URL)
    assert message.subject == "Telco A (fixture): progress digest, 5 Oct 2026"
    assert message.tag == "em7_org"
    assert message.text == (
        "4 active engagements, 2 on track, 1 at risk, 1 off track, 2 awaiting you, 1 new tagged proposal.\n"
        "\n"
        "NEEDS US\n"
        "- “Farm data” by Otieno: start the review by 13 Oct 2026.\n"
        "- Milestone 1 “Pilot for one county” of “Ledger” by Wanjiru: review it.\n"
        "\n"
        "NEW TAGGED PROPOSALS\n"
        "- “Farm data” by Otieno, submitted 5 Oct 2026.\n"
        "\n"
        "OVERDUE\n"
        "- “Ledger” by Wanjiru: The review of milestone 1 was due 22 Sep 2026 and is 13 days overdue.\n"
        "\n"
        "ENGAGEMENTS\n"
        "- “Ledger” by Wanjiru (Implementation): Off track. The review of milestone 1 was due 22 Sep 2026 and is"
        " 13 days overdue.\n"
        "- “Solar cold rooms” by Wanjiru (Implementation): At risk. Milestone 1 “Pilot for one county” is due"
        " 6 Oct 2026 (1 business day left) and not submitted yet. No update from Wanjiru since 29 Sep 2026.\n"
        "- “Farm data” by Otieno (Proposal submitted): On track.\n"
        "- “Kiosk app” by Wanjiru (Implementation): On track. Milestones due: milestone 1 “Beta” due 14 Oct 2026.\n"
        "\n"
        f"Open your organisation's tracker: {BASE_URL}/org/engagements?org={ORG_ID}\n"
        "\n"
        "--\n"
        "You get this daily digest for Telco A (fixture) because you turned reminders on.\n"
        f"Manage notifications: {BASE_URL}/settings/notifications · Help: {BASE_URL}/help · Nairobi, Kenya\n"
    )
    assert digest.health_of() == {
        review.id: Health.OFF_TRACK,
        building.id: Health.AT_RISK,
        tagged.id: Health.ON_TRACK,
        upcoming.id: Health.ON_TRACK,
    }


def test_the_organisations_stage_step_and_its_overdue_step_are_its_own() -> None:
    late = engagement(
        S.UNDER_REVIEW, awaiting=frozenset({ORG}), stage_deadline_on=days(-3), last_developer_update_on=MONDAY
    )
    digest = compose_digest(facts(late), NO_HOLIDAYS)
    assert digest.needs_us == ("“Solar cold rooms” by Wanjiru: decide on the proposal by 2 Oct 2026.",)
    assert digest.overdue == (
        "“Solar cold rooms” by Wanjiru: Your organisation's step (Under review) was due 2 Oct 2026 and is 3 days"
        " overdue.",
    )
    soon = engagement(
        S.NDA_PENDING, awaiting=frozenset({ORG}), stage_deadline_on=days(1), last_developer_update_on=MONDAY
    )
    (entry,) = compose_digest(facts(soon), NO_HOLIDAYS).entries
    assert "Your organisation's step (Mutual NDA: awaiting signatures) is due 6 Oct 2026." in entry.line
    developer_turn = engagement(S.ORG_INTEREST, stage_deadline_on=days(-1), last_developer_update_on=MONDAY)
    (entry,) = compose_digest(facts(developer_turn), NO_HOLIDAYS).entries
    assert "Wanjiru's step (Organisation interested) was due 4 Oct 2026 and is 1 day overdue." in entry.line
    review_soon = engagement(
        milestones=(milestone(days(3), M.SUBMITTED_FOR_REVIEW, review_due_on=days(1)),),
        awaiting=frozenset({ORG}),
        last_developer_update_on=MONDAY,
    )
    (entry,) = compose_digest(facts(review_soon), NO_HOLIDAYS).entries
    assert "The review of milestone 1 is due 6 Oct 2026." in entry.line


def test_nothing_active_is_quiet() -> None:
    assert compose_digest(facts(engagement(S.CLOSED), engagement(S.DECLINED)), NO_HOLIDAYS).empty
    assert not compose_digest(facts(engagement(last_developer_update_on=MONDAY)), NO_HOLIDAYS).empty


def test_a_weekly_digest_covers_the_iso_week_and_its_new_proposals() -> None:
    thursday = days(3)
    assert period_start(thursday, "weekly") == MONDAY
    assert period_start(thursday, "daily") == thursday
    new = engagement(
        S.SUBMITTED, tagged=True, created_on=days(-3), awaiting=frozenset({ORG}), stage_deadline_on=days(20)
    )
    old = engagement(
        S.SUBMITTED, tagged=True, created_on=days(-9), awaiting=frozenset({ORG}), stage_deadline_on=days(20)
    )
    weekly = compose_digest(facts(new, old, cadence="weekly", today=thursday), NO_HOLIDAYS)
    assert weekly.new_tagged == ("“Solar cold rooms” by Wanjiru, submitted 2 Oct 2026.",)
    assert render_digest(weekly, to="o@example.com", base_url=BASE_URL).subject == (
        "Telco A (fixture): weekly progress digest, week of 5 Oct 2026"
    )
    daily = compose_digest(facts(new, old, today=thursday), NO_HOLIDAYS)
    assert daily.new_tagged == ()


def test_developer_text_is_quoted_attributed_and_never_auto_linkable() -> None:
    """AC-MAIL-5 on the org digest: a teaser with a bare domain, an email and a Kenyan phone number."""
    hostile = engagement(
        S.SUBMITTED,
        title="Solar kiosks: coldchain.co.ke, jane@coldchain.co.ke, 0712 345 678, 020 2345678 <img src=x>",
        developer_name="Jane <b>www.jane.dev</b>",
        tagged=True,
        created_on=MONDAY,
        awaiting=frozenset({ORG}),
        milestones=(milestone(days(1), deliverable="Call +254 712 345 678 or see https://x.example"),),
    )
    message = render_digest(compose_digest(facts(hostile), NO_HOLIDAYS), to="o@example.com", base_url=BASE_URL)
    for part in (message.text, message.html or ""):
        assert (
            re.search(r"coldchain\.co|jane@|0712|712 345|020 2345678|2345678|www\.|x\.example|<img|<b>", part) is None
        )
        assert all(link.startswith(BASE_URL + "/") for link in re.findall(r"https?://[^\s\"<>]+", part))
    assert "“Solar kiosks: coldchain[.]co[.]ke, [email removed], [phone number removed], [phone number removed]”" in (
        message.text
    )


def test_both_reminders_agree_on_health_for_the_same_facts() -> None:
    """AC-REM-3, unit half: the digest and the developer's reminder read one assessment."""
    rows = (
        engagement(milestones=(milestone(days(1)),)),
        engagement(milestones=(milestone(days(-8)),)),
        engagement(S.NDA_PENDING, awaiting=frozenset({ORG}), stage_deadline_on=days(10)),
    )
    developer = compose_nudge(DeveloperFacts(uuid4(), MONDAY, rows), NO_HOLIDAYS).health_of()
    organisation = compose_digest(facts(*rows), NO_HOLIDAYS).health_of()
    assert developer == organisation
    assert sorted(h.value for h in organisation.values()) == ["at_risk", "off_track", "on_track"]


def test_the_digest_uses_no_llm() -> None:
    tree = ast.parse(inspect.getsource(org_digest))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(module and module.startswith("bridge.llm") for module in imported)
    assert not any(module and module.startswith("bridge.reminders.wording") for module in imported)


@pytest.mark.parametrize("cadence", ["daily", "weekly"])
def test_the_footer_names_the_cadence(cadence: str) -> None:
    digest = compose_digest(facts(engagement(last_developer_update_on=MONDAY), cadence=cadence), NO_HOLIDAYS)
    assert (
        f"You get this {cadence} digest for Telco A (fixture)"
        in render_digest(digest, to="o@example.com", base_url=BASE_URL).text
    )
