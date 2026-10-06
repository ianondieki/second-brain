"""REQ-DEV-02 (D-60; P22 card B test B6, the checks part): the trends' checks in code decide.

Given the week's excerpts, a clean three-trend answer is kept whole with its sources as saved; each scripted fault
(``bridge.problems.trends.fakes.VARIANTS``) refuses the answer with its own reason code; an unverified citation is
dropped and lowers the agreement; a vendor named in a quote from its own site passes, one named only by the model or
only in the card's text fails; a version number needs the word that follows it in the quote; ``injection_suspected``
refuses every trend; drafts over the limit are discarded; ``low_confidence`` applies under a stricter policy.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from bridge.problems.research.checks import Citation
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import TECH, CatalogueKind, Excerpt, get_catalogue
from bridge.problems.trends import fakes
from bridge.problems.trends.checks import (
    AnswerDraft,
    Discarded,
    KeptTrend,
    Reason,
    TrendDraft,
    check_answer,
    check_trend,
    sentence_count,
    unsourced_capitalised,
)
from bridge.problems.trends.policy import get_trends_policy
from bridge.problems.trends.synthesis import select_excerpts

WEEK: Final = date(2026, 10, 5)
CATALOGUE: Final = get_catalogue(CatalogueKind.TRENDS)
ALLOWLIST: Final = CATALOGUE.allowlists[TECH]
SCORING: Final = get_trends_policy().scoring(get_research_policy())
SENT: Final[dict[str, Excerpt]] = {
    e.id: e for e in select_excerpts(CATALOGUE, WEEK, SCORING, get_trends_policy().max_excerpts)
}


def verdict(answer: AnswerDraft, *, max_cards: int = 3) -> tuple[Reason | None, tuple[Reason, ...], int]:
    result = check_answer(answer, SENT, ALLOWLIST, SCORING, WEEK, max_cards=max_cards)
    return result.refused, result.discarded, len(result.kept)


def one(draft: TrendDraft) -> KeptTrend | Discarded:
    return check_trend(draft, SENT, ALLOWLIST, SCORING, WEEK)


def security(**changes: object) -> TrendDraft:
    return dataclasses.replace(fakes.SECURITY.draft(), **changes)  # type: ignore[arg-type]


def test_a_clean_answer_is_kept_whole_with_its_sources_as_saved() -> None:
    result = check_answer(fakes.answer().draft(), SENT, ALLOWLIST, SCORING, WEEK, max_cards=3)
    assert (result.refused, result.discarded) == (None, ())
    assert [k.topic_slug for k in result.kept] == ["security", "databases", "kenya-ict"]
    first = result.kept[0]
    assert first.title == fakes.SECURITY.title
    assert first.named_orgs == ("GitHub",)  # "npm" is GitHub's alias, declared too: named once
    [source] = first.sources
    assert source.excerpt is SENT["tr-sec-001"]
    assert source.support == "now expire 48 hours after creation"
    assert result.kept[1].named_orgs == ("PostgreSQL",)  # "pgvector": its quote names it on postgresql.org
    # Official source (1.0), one publisher of three (0.333), fresh (1), every citation verified (1).
    assert {k.confidence for k in result.kept} == {Decimal("0.833")}
    assert {k.agreement for k in result.kept} == {Decimal(1)}


REASON_VARIANTS: Final = [
    (name, Reason(name)) for name in fakes.VARIANTS if name in {r.value for r in Reason} and name != "over_card_limit"
] + [
    ("one_sentence", Reason.TEXT_OUT_OF_BOUNDS),
    ("named_org_declared_only", Reason.NAMED_ORG_WITHOUT_OFFICIAL),
    ("host_in_text", Reason.LINK_IN_TEXT),
]


@pytest.mark.parametrize(("variant", "reason"), REASON_VARIANTS, ids=[v for v, _ in REASON_VARIANTS])
def test_each_check_refuses_its_case(variant: str, reason: Reason) -> None:
    refused, discarded, kept = verdict(fakes.answer(variant).draft())
    assert (refused, kept) == (reason, 0)
    assert set(discarded) <= {reason}


def test_every_reason_but_two_unreachable_ones_has_a_scripted_case() -> None:
    covered = {reason for _, reason in REASON_VARIANTS} | {Reason.OVER_CARD_LIMIT, Reason.LOW_CONFIDENCE}
    # Every TECH source is official, so the research source rule never fails for a trend.
    assert set(Reason) - covered == {Reason.NEEDS_OFFICIAL_OR_TWO_PUBLISHERS}


def test_a_partly_valid_answer_keeps_the_good_trends() -> None:
    assert verdict(fakes.answer("partly_valid").draft()) == (None, (Reason.UNKNOWN_EXCERPT,), 2)


def test_drafts_over_the_limit_are_discarded() -> None:
    assert verdict(fakes.answer("over_card_limit").draft()) == (None, (Reason.OVER_CARD_LIMIT,), 3)
    assert verdict(fakes.answer().draft(), max_cards=1) == (None, (Reason.OVER_CARD_LIMIT,) * 2, 1)


def test_injection_suspected_refuses_every_trend() -> None:
    assert verdict(fakes.answer("injection_suspected").draft()) == (
        Reason.INJECTION_SUSPECTED,
        (Reason.INJECTION_SUSPECTED,) * 3,
        0,
    )


def test_an_unverified_citation_is_dropped_and_lowers_the_agreement() -> None:
    citations = (
        Citation("tr-sec-001", "now expire 48 hours after creation"),
        Citation("tr-sec-003", "secret scanning finds every leaked key"),  # not in tr-sec-003's quote
    )
    kept = one(security(citations=citations))
    assert isinstance(kept, KeptTrend)
    assert [s.excerpt.id for s in kept.sources] == ["tr-sec-001"]
    assert kept.agreement == Decimal("0.5")
    assert kept.confidence == Decimal("0.733")  # 0.35 + 0.0833 + 0.20 + 0.10


def test_a_support_shorter_than_the_minimum_is_not_verified() -> None:
    assert one(security(citations=(Citation("tr-sec-001", "now expire"),))) == Discarded(Reason.NO_VERIFIED_CITATION)


def test_a_vendor_named_in_a_quote_from_its_own_site_passes() -> None:
    draft = TrendDraft(
        title="Amazon Aurora DSQL now lets you build partial indexes",
        summary="Amazon Aurora DSQL now lets you build an index over a specific subset of a table. Storing only"
        " qualifying rows improves query performance and lowers index storage cost.",
        topic_slug="databases",
        named_orgs=("Amazon Web Services",),
        citations=(Citation("tr-dat-003", "build an index over a specific subset of a table"),),
    )
    kept = one(draft)
    assert isinstance(kept, KeptTrend)
    assert kept.named_orgs == ("Amazon Web Services",)


def test_a_name_off_the_allowlist_passes_only_when_its_quote_names_it() -> None:
    gazette = dataclasses.replace(fakes.KENYA.draft(), named_orgs=("Kenya Gazette",))
    assert isinstance(one(gazette), KeptTrend)
    oracle = dataclasses.replace(fakes.KENYA.draft(), named_orgs=("Oracle",))
    assert one(oracle) == Discarded(Reason.NAMED_ORG_WITHOUT_OFFICIAL)


def test_a_vendor_named_only_in_the_card_text_fails_even_when_undeclared() -> None:
    draft = security(
        summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Apple"
        " developers in Kenya who publish npm packages should validate them.",
        named_orgs=(),
    )
    assert one(draft) == Discarded(Reason.NAMED_ORG_WITHOUT_OFFICIAL)


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("pgvector 0.8.7 is now available", None),  # as the quote writes it
        ("pgvector 0.8.7 fixes a buffer overflow", Reason.UNSUPPORTED_NUMBER),  # "7 fixes": not in the quote
        ("pgvector 0.8.8 is now available", Reason.UNSUPPORTED_NUMBER),
    ],
)
def test_a_version_number_needs_the_quotes_own_next_word(title: str, reason: Reason | None) -> None:
    result = one(dataclasses.replace(fakes.DATABASES.draft(), title=title))
    assert (result.reason if isinstance(result, Discarded) else None) == reason


def test_low_confidence_discards_under_a_stricter_policy() -> None:
    strict = dataclasses.replace(SCORING, discard_below=Decimal("0.90"))
    assert check_trend(fakes.SECURITY.draft(), SENT, ALLOWLIST, strict, WEEK) == Discarded(Reason.LOW_CONFIDENCE)


def test_an_older_source_scores_lower_freshness() -> None:
    later = date(2027, 6, 30)  # tr-ke-002 (2026-08-13) is stale after 6 months, archived after 12
    kept = check_trend(fakes.KENYA.draft(), SENT, ALLOWLIST, SCORING, later)
    assert isinstance(kept, KeptTrend)
    assert kept.confidence < Decimal("0.833")


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("One sentence only.", 1),
        ("One. Two.", 2),
        ("Go 1.27 brings generics. The release is out", 2),
        ("It works, e.g. on Linux. Then it ships.", 2),
        ("Python 3.15.0rc3 is out. It has 156 fixes! Try it? Yes.", 4),
        ("", 0),
    ],
)
def test_sentence_count(text: str, count: int) -> None:
    assert sentence_count(text) == count


@pytest.mark.parametrize(
    "summary",
    [
        "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Read more at"
        " https://evil.example/login today.",
        "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. See"
        " www.example.com for the steps.",
        "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Log in at"
        " evil.example/login to check.",
        "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Mirror them on"
        " npm-mirror.co.ke soon.",
    ],
)
def test_a_link_in_the_text_is_refused(summary: str) -> None:
    assert one(security(summary=summary)) == Discarded(Reason.LINK_IN_TEXT)
    assert one(security(title=summary.split(". ")[1][:100])) == Discarded(Reason.LINK_IN_TEXT)


def test_a_dotted_name_a_cited_quote_carries_is_not_a_link() -> None:
    quote = f"{SENT['tr-sec-001'].quote} Node.js maintainers should validate theirs."
    sent = {**SENT, "tr-sec-001": dataclasses.replace(SENT["tr-sec-001"], quote=quote)}
    draft = security(
        summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Node.js"
        " maintainers should validate theirs."
    )
    assert isinstance(check_trend(draft, sent, ALLOWLIST, SCORING, WEEK), KeptTrend)
    assert one(draft) == Discarded(Reason.LINK_IN_TEXT)  # the saved quote does not carry "Node.js"


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("IBM says npm trusted publishing configurations now expire", fakes.SECURITY.summary),  # review MAJOR 1
        (
            fakes.SECURITY.title,
            "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. According to"
            " Oracle, developers in Kenya should validate them.",
        ),
        (
            fakes.SECURITY.title,
            "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. OpenAI tools and"
            " developers in Kenya should validate them.",
        ),
    ],
)
def test_an_undeclared_name_off_the_allowlist_is_refused(title: str, summary: str) -> None:
    draft = security(title=title, summary=summary, named_orgs=("GitHub",))
    assert one(draft) == Discarded(Reason.NAMED_ORG_WITHOUT_OFFICIAL)


def test_ordinary_capitals_places_months_and_quoted_names_pass() -> None:
    kept = one(
        security(
            summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Since"
            " October, developers in Kenya and across East Africa who publish npm packages should validate them."
        )
    )
    assert isinstance(kept, KeptTrend)
    assert unsourced_capitalised("Amazon Aurora DSQL adds partial indexes", "Storing rows.", (), ALLOWLIST) == ()
    assert unsourced_capitalised("Kenya Gazette notice", "", (SENT["tr-ke-002"],), ALLOWLIST) == ()
    assert unsourced_capitalised("Kenya Gazette notice", "", (), ALLOWLIST) == ("Gazette",)


def test_the_residual_a_lower_case_or_sentence_initial_brand() -> None:
    """Documented residual: a lower-case brand off the allowlist, or a single-capital one opening a sentence, passes
    the code; the staff admin's approval of every card is the backstop."""
    assert unsourced_capitalised("Oracle says hello", "acme tools say so. Oracle agrees.", (), ALLOWLIST) == ()


def _summary_of(length: int) -> str:
    """Four plain sentences of exactly ``length`` characters that pass every other check."""
    head = (
        "Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Developers in Kenya"
        " who publish npm packages should validate each new setup soon after creating it. Teams should review the"
        " setups they still rely on. They should check "
    )
    pad = length - len(head) - len("now.")
    words = ("them again " * 100)[:pad]
    if words.endswith(" ") or words.endswith("n"):  # keep the text ending in a whole word
        words = words[:-1] + "s"
    return head + words + "now."


@pytest.mark.parametrize(("length", "kept"), [(600, True), (601, False)])
def test_the_summary_bound_is_600_characters(length: int, kept: bool) -> None:
    summary = _summary_of(length)
    assert (len(summary), sentence_count(summary)) == (length, 4)
    result = one(security(summary=summary))
    assert isinstance(result, KeptTrend) if kept else result == Discarded(Reason.TEXT_OUT_OF_BOUNDS)


@pytest.mark.parametrize(("length", "kept"), [(400, True), (401, False)])
def test_the_support_bound_is_400_characters(length: int, kept: bool) -> None:
    long_quote = f"{SENT['tr-sec-001'].quote} " + " ".join(f"word{i}" for i in range(120))
    sent = {**SENT, "tr-sec-001": dataclasses.replace(SENT["tr-sec-001"], quote=long_quote)}
    support = next(
        cut for start in range(50) if (cut := long_quote[start : start + length]) == cut.strip()
    )  # no space at either end, so collapsing keeps every character
    assert len(support) == length
    assert support in long_quote  # verbatim: only the bound decides
    draft = security(citations=(Citation("tr-sec-001", support),))
    result = check_trend(draft, sent, ALLOWLIST, SCORING, WEEK)
    assert isinstance(result, KeptTrend) if kept else result == Discarded(Reason.TEXT_OUT_OF_BOUNDS)


def test_a_declared_name_is_at_most_200_characters() -> None:
    name = "GitHub " + "x" * 194
    assert len(name) == 201
    assert one(security(named_orgs=(name,))) == Discarded(Reason.TEXT_OUT_OF_BOUNDS)
