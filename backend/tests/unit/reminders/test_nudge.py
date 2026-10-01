"""REQ-REM-01 (docs/spec/06 6.10, 6.11): the developer's EM7 is composed by code from fact tuples. Needs you, Waiting
on the other party, Health with code-computed reasons, drafts, one featured next step; quiet when nothing needs the
developer; party text quoted and defanged; the LLM sees counts, codes, dates and the developer's own titles only;
the email marks which wording it carries."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from bridge.reminders.health import Health
from bridge.reminders.nudge import (
    AI_LABEL,
    KIND,
    WORDING_HEADER,
    DeveloperFacts,
    Wording,
    compose_nudge,
    fallback_wording,
    in_app_body,
    render_nudge,
)
from bridge.reminders.render import defang, eat_date, platform_url, quote
from tests.unit.reminders.builders import BASE_URL, DEV, MONDAY, NO_HOLIDAYS, ORG, M, S, days, engagement, milestone

USER = uuid4()


def facts(*engagements: object, drafts: tuple[str | None, ...] = ()) -> DeveloperFacts:
    return DeveloperFacts(USER, MONDAY, tuple(engagements), drafts)  # type: ignore[arg-type]


def test_the_sections_are_code_rendered_from_the_facts() -> None:
    building = engagement(
        milestones=(milestone(days(1)), milestone(days(40), M.PLANNED, seq=2, deliverable="Scale to three counties"))
    )
    review = engagement(
        S.SUBMITTED, title="Farm data", org_name="Bank B", awaiting=frozenset({ORG}), stage_deadline_on=days(8)
    )
    nda = engagement(
        S.NDA_PENDING,
        title="Till reconciler",
        org_name="Sacco C",
        awaiting=frozenset({DEV, ORG}),
        stage_deadline_on=days(-2),
    )
    nudge = compose_nudge(facts(building, review, nda, drafts=("Draft one", None)), NO_HOLIDAYS)
    assert nudge.needs_you == (
        "Milestone 1 “Pilot for one county” of “Solar cold rooms”: submit it for review by 6 Oct 2026.",
        "“Till reconciler” with Sacco C: sign the mutual NDA (due 3 Oct 2026).",
    )
    assert nudge.waiting == (
        "“Farm data”: waiting for Bank B to start the review (due 13 Oct 2026).",
        "“Till reconciler”: waiting for Sacco C to sign the mutual NDA (due 3 Oct 2026).",
    )
    assert [row.line for row in nudge.health] == [
        "“Solar cold rooms” with Telco A (fixture): At risk. Milestone 1 “Pilot for one county” is due 6 Oct 2026"
        " (1 business day left) and not submitted yet.",
        "“Farm data” with Bank B: On track.",
        "“Till reconciler” with Sacco C: At risk. Your step (Mutual NDA: awaiting signatures) was due 3 Oct 2026 and is"
        " 2 days overdue; Sacco C's step (Mutual NDA: awaiting signatures) was due 3 Oct 2026 and is 2 days overdue.",
    ]
    assert nudge.health_of() == {building.id: Health.AT_RISK, review.id: Health.ON_TRACK, nda.id: Health.AT_RISK}
    assert nudge.drafts == ("“Draft one”", "“Untitled draft”")
    # the most urgent of the developer's own items, worst first then earliest
    assert nudge.next_step == "Sign the mutual NDA for “Till reconciler”: it was due 3 Oct 2026."
    assert nudge.fallback_headline == "2 things need you today, and 2 engagements need attention."


def test_a_later_milestone_is_one_line_with_its_date() -> None:
    later = engagement(milestones=(milestone(days(40), M.PLANNED),))
    assert compose_nudge(facts(later), NO_HOLIDAYS).needs_you == (
        "“Solar cold rooms” with Telco A (fixture): work on the milestones (due 14 Nov 2026).",
    )


def test_waiting_on_the_other_party_alone_is_quiet() -> None:
    waiting = engagement(S.UNDER_REVIEW, awaiting=frozenset({ORG}), stage_deadline_on=days(20))
    nudge = compose_nudge(facts(waiting, engagement(S.CLOSED)), NO_HOLIDAYS)
    assert nudge.empty
    assert [row.engagement_id for row in nudge.health] == [waiting.id]  # a closed engagement is not listed


@pytest.mark.parametrize(
    ("items", "headline", "step"),
    [
        (
            {"drafts": ("Idea",)},
            "You have 1 draft not published yet.",
            "Finish and publish your draft “Idea”.",
        ),
        (
            {"engagements": (engagement(S.ORG_INTEREST),)},
            "1 thing needs you today.",
            "Accept or decline the interest for “Solar cold rooms”.",
        ),
        (
            {"engagements": (engagement(S.UNDER_REVIEW, awaiting=frozenset({ORG}), stage_deadline_on=days(-9)),)},
            "Nothing needs you today, but 1 engagement needs attention.",
            "Nothing needs you today: look over your tracker when you have a moment.",
        ),
        (
            {"engagements": (engagement(milestones=(milestone(days(-3)),)),)},
            "1 thing needs you today, and 1 engagement needs attention.",
            "Submit milestone 1 of “Solar cold rooms” for review: it was due 2 Oct 2026.",
        ),
        (
            {"engagements": (engagement(milestones=(milestone(days(30), rework_loops=2),)),)},
            "1 thing needs you today, and 1 engagement needs attention.",
            "Agree what milestone 1 of “Solar cold rooms” still needs before you resubmit it.",
        ),
        (
            {"engagements": (engagement(S.AGREEMENT_SIGNING, stage_deadline_on=days(1)),)},
            "1 thing needs you today, and 1 engagement needs attention.",
            "Sign the agreement for “Solar cold rooms” by 6 Oct 2026.",
        ),
        (
            {"engagements": (engagement(repo_linked=True, last_repo_activity_on=days(-10)),)},
            "1 thing needs you today, and 1 engagement needs attention.",
            "Pick up “Solar cold rooms” where you left off.",
        ),
    ],
)
def test_the_fallback_headline_and_next_step(items: dict[str, tuple[object, ...]], headline: str, step: str) -> None:
    nudge = compose_nudge(facts(*items.get("engagements", ()), drafts=items.get("drafts", ())), NO_HOLIDAYS)  # type: ignore[arg-type]
    assert (nudge.fallback_headline, nudge.next_step) == (headline, step)
    wording = fallback_wording(nudge, "demo_fallback:fake_provider")
    assert (wording.headline, wording.next_step, wording.source, wording.ai_drafted) == (
        headline,
        step,
        "fallback",
        False,
    )


def test_the_llm_facts_hold_no_organisation_text_or_deliverable() -> None:
    e = engagement(org_name="Secret Org Ltd", milestones=(milestone(days(1), deliverable="Confidential pilot"),))
    nudge = compose_nudge(facts(e), NO_HOLIDAYS)
    text = "\n".join(nudge.fact_lines)
    assert "Secret Org" not in text
    assert "Confidential pilot" not in text
    assert "“Solar cold rooms”" in text  # the developer's own title
    assert nudge.fact_lines[-1] == f"Suggested next step: {nudge.next_step}"


def test_the_email_is_escaped_defanged_and_links_only_to_the_platform() -> None:
    hostile = engagement(
        title="<script>x</script> 5 < 6 & 7 call 0712 345 678 or mail a@b.co.ke at evil.example https://evil.example/p",
        org_name="Acme.co.ke",
        milestones=(milestone(days(1), deliverable="Ship <b>it</b> via www.evil.example"),),
    )
    nudge = compose_nudge(facts(hostile), NO_HOLIDAYS)
    message = render_nudge(nudge, fallback_wording(nudge, "x"), to="dev@example.com", base_url=BASE_URL)
    for part in (message.text, message.html or ""):
        assert "0712" not in part
        assert "a@b" not in part
        assert "evil.example" not in part
        assert "Acme.co.ke" not in part
        assert "<script>" not in part
        links = re.findall(r"https?://[^\s\"<>]+", part)
        assert links
        assert all(link.startswith(BASE_URL + "/") for link in links)
    assert "evil[.]example" in message.text
    assert "Ship it via [link removed]" in message.text
    assert "5 &lt; 6 &amp; 7" in (message.html or "")  # escaped, never markup
    assert (message.tag, message.headers[WORDING_HEADER]) == (KIND, "fallback")


def test_the_email_labels_ai_wording_and_never_the_fallback() -> None:
    nudge = compose_nudge(facts(engagement(milestones=(milestone(days(1)),))), NO_HOLIDAYS)
    model = Wording("Morning! One milestone is close.", "Submit milestone 1 by 6 Oct 2026.", "model")
    worded = render_nudge(nudge, model, to="dev@example.com", base_url=BASE_URL)
    assert worded.text.startswith(f"Morning! One milestone is close.\n{AI_LABEL}\n")
    assert AI_LABEL in (worded.html or "")
    assert worded.headers[WORDING_HEADER] == "model"
    assert "NEXT STEP\nSubmit milestone 1 by 6 Oct 2026.\n" in worded.text
    fixed = render_nudge(nudge, fallback_wording(nudge, "x"), to="dev@example.com", base_url=BASE_URL)
    assert AI_LABEL not in fixed.text
    assert AI_LABEL not in (fixed.html or "")
    assert fixed.subject == worded.subject == "Your day on Wazo (5 Oct 2026): 1 needs you, 1 at risk"


def test_the_in_app_summary_is_code_rendered() -> None:
    nudge = compose_nudge(facts(engagement(milestones=(milestone(days(-9)),))), NO_HOLIDAYS)
    assert in_app_body(nudge) == (
        "1 needs you, 1 off track. Next step: Submit milestone 1 of “Solar cold rooms” for review: it was due"
        " 26 Sep 2026."
    )


def test_defang_and_quote() -> None:
    assert defang("see example.com or www.x.org/p, mail j@x.io, call +254 712 345 678, v1.2 e.g. 3.5") == (
        "see example[.]com or [link removed] mail [email removed], call [phone number removed], v1.2 e.g. 3.5"
    )
    assert defang("tel:0712345678 and 0712-345-678 and a@b") == "[link removed] and [phone number removed] and a[at]b"
    assert defang("office 020 2345678 or (0203) 123-456 or +254 41 222 3344") == (
        "office [phone number removed] or [phone number removed] or [phone number removed]"
    )
    assert quote("x" * 200).endswith("…”")
    assert quote("  ​spaced\u0007 out\n text ") == "“spaced out text”"
    assert quote(None, fallback="Untitled") == "“Untitled”"
    assert eat_date(MONDAY) == "5 Oct 2026"


@pytest.mark.parametrize(
    ("fact", "line"),
    [
        (
            engagement(S.CONTACT_MADE, awaiting=frozenset({DEV, ORG})),
            "“Solar cold rooms” with Telco A (fixture): send the mutual NDA.",
        ),
        (
            engagement(S.CONTACT_MADE),
            "“Solar cold rooms” with Telco A (fixture): confirm first contact.",
        ),
        (
            engagement(milestones=(milestone(days(-3), M.ACCEPTED),)),
            "“Solar cold rooms” with Telco A (fixture): submit the final delivery.",
        ),
        (
            engagement(S.PAYMENT_FINAL, stage_deadline_on=days(4)),
            "“Solar cold rooms” with Telco A (fixture): confirm the payment received (due 9 Oct 2026).",
        ),
    ],
)
def test_the_developers_action_follows_the_stage(fact: object, line: str) -> None:
    assert compose_nudge(facts(fact), NO_HOLIDAYS).needs_you == (line,)


def test_links_are_platform_paths_only() -> None:
    assert platform_url(BASE_URL + "/", "/engagements") == f"{BASE_URL}/engagements"
    for path in ("https://evil.example", "//evil.example", "engagements"):
        with pytest.raises(ValueError, match="platform path"):
            platform_url(BASE_URL, path)


def test_the_email_opens_the_developers_own_engagements() -> None:
    """There is no shared /engagements page: the CTA opens the developer's portal."""
    nudge = compose_nudge(facts(engagement(S.ORG_INTEREST)), NO_HOLIDAYS)
    message = render_nudge(nudge, fallback_wording(nudge, "x"), to="dev@example.com", base_url=BASE_URL)
    assert f"Open your tracker: {BASE_URL}/dev/engagements\n" in message.text
    assert f'href="{BASE_URL}/dev/engagements"' in (message.html or "")


def test_the_product_name_reaches_the_nudge_html() -> None:
    nudge = compose_nudge(facts(engagement(milestones=(milestone(days(3)),))), NO_HOLIDAYS)
    message = render_nudge(nudge, fallback_wording(nudge, "x"), to="dev@example.com", base_url=BASE_URL, product="Acme")
    assert message.html is not None
    assert ">Acme<" in message.html  # the frame's wordmark and footer line
