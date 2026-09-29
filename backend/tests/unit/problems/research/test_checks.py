"""REQ-RES-01: the checks in code that decide whether a drafted card becomes a candidate (docs/spec/06 6.5; AC-RES-1;
D-45). The model's draft is only input; each rule below discards a draft that breaks it, and a draft keeping every
rule gets the spec's confidence (discarded below 0.40)."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from bridge.problems.research import checks
from bridge.problems.research.checks import Accepted, Citation, Discarded, Draft
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import Excerpt, load_allowlist, load_catalogue

AS_OF = date(2026, 9, 29)
CATALOGUE = load_catalogue()
ALLOWLIST = load_allowlist("KE")
POLICY = get_research_policy()


def sent(niche: str) -> dict[str, Excerpt]:
    return {e.id: e for e in CATALOGUE.usable(niche, "KE", AS_OF, POLICY)}


def excerpt(excerpt_id: str) -> Excerpt:
    found = CATALOGUE.get(excerpt_id)
    assert found is not None
    return found


TELECOM = Draft(
    title="Smaller operators struggle with call termination charges",
    statement=(
        "Smaller mobile operators say the termination rate regime disadvantages them. The regulator's glide path"
        " takes the rate from Sh0.41 to Sh0.3 per minute by March 2029, while the market leader still held 89 percent"
        " of mobile money in December 2025."
    ),
    affected_group="Smaller mobile operators and their customers",
    named_orgs=(),
    citations=(
        Citation("ke-tel-001", "M-Pesa\u2019s share in the mobile money market had slimmed to 89 percent"),
        Citation("ke-tel-002", "decline from the previous Sh0.41 to Sh0.37"),
        Citation("ke-tel-004", "the current MTR regime disproportionately disadvantages smaller operators"),
    ),
)


def check(draft: Draft, niche: str = "networks-telecommunications", **policy: Any) -> checks.Verdict:
    return checks.check_draft(draft, sent(niche), ALLOWLIST, dataclasses.replace(POLICY, **policy), AS_OF)


def test_a_supported_draft_is_accepted_with_the_spec_confidence() -> None:
    verdict = check(TELECOM)
    assert isinstance(verdict, Accepted), verdict
    assert [e.id for e in verdict.sources] == ["ke-tel-001", "ke-tel-002", "ke-tel-004"]
    assert verdict.agreement == 1
    # 0.35 * 0.8 (news) + 0.25 * 2/3 (Business Daily, Capital FM) + 0.20 * 1 (fresh) + 0.20 * 1 (all verified)
    assert verdict.confidence == Decimal("0.846")
    assert verdict.text.named_orgs == ()


def test_whitespace_is_collapsed_before_anything_else() -> None:
    draft = dataclasses.replace(TELECOM, title="Smaller operators\n\tstruggle  with call charges", affected_group="")
    verdict = check(draft)
    assert isinstance(verdict, Accepted)
    assert verdict.text.title == "Smaller operators struggle with call charges"


@pytest.mark.parametrize("bad", ["\x00", "\x07", "\x1b", "\x7f", "\x9b"])
def test_a_control_character_left_after_collapsing_discards_the_draft(bad: str) -> None:
    assert check(dataclasses.replace(TELECOM, statement=TELECOM.statement + bad)) == Discarded("control_character")
    assert check(dataclasses.replace(TELECOM, named_orgs=(f"Org{bad}",))) == Discarded("control_character")


@pytest.mark.parametrize(
    "change",
    [
        {"title": "x" * 91},
        {"title": "   "},
        {"statement": "word " * 121},
        {"statement": "w" * 1501},
        {"affected_group": "g" * 201},
        {"named_orgs": tuple(f"Org {i}" for i in range(11))},
        {"named_orgs": ("o" * 201,)},
    ],
)
def test_text_out_of_bounds_discards_the_draft(change: dict[str, Any]) -> None:
    assert check(dataclasses.replace(TELECOM, **change)) == Discarded("text_out_of_bounds")


def test_a_draft_without_citations_is_discarded() -> None:
    assert check(dataclasses.replace(TELECOM, citations=())) == Discarded("no_citation")


@pytest.mark.parametrize("cited", ["ke-tel-999", "ke-tel-005", "ke-hlt-001"])
def test_a_cited_id_this_run_did_not_send_discards_the_whole_draft(cited: str) -> None:
    """An invented id, an archived excerpt (never sent) and another niche's excerpt are all unknown to the run."""
    citations = (*TELECOM.citations, Citation(cited, "In the latest review, the Authority has capped the MTRs"))
    assert check(dataclasses.replace(TELECOM, citations=citations)) == Discarded("unknown_excerpt")


def test_an_unverified_citation_is_dropped_and_lowers_the_agreement() -> None:
    citations = (
        TELECOM.citations[0],
        Citation("ke-tel-002", "rates fall from Sh0.41 to Sh0.37"),  # paraphrased: not verbatim
        TELECOM.citations[2],
        Citation("ke-tel-003", "Satellite"),  # verbatim, but shorter than min_support_words
    )
    statement = "Smaller operators say the regime disadvantages them; the leader held 89 percent in December 2025."
    draft = dataclasses.replace(TELECOM, statement=statement, citations=citations)
    verdict = check(draft)
    assert isinstance(verdict, Accepted), verdict
    assert [e.id for e in verdict.sources] == ["ke-tel-001", "ke-tel-004"]
    assert verdict.agreement == Decimal("0.5")
    assert check(dataclasses.replace(draft, citations=(citations[1], citations[3]))) == Discarded(
        "no_verified_citation"
    )
    # the dropped citation's quote no longer supports a number: Sh0.41 is only in ke-tel-002
    assert check(dataclasses.replace(draft, statement="Rates start at Sh0.41.")) == Discarded("unsupported_number")


def test_supporting_text_is_compared_unicode_exact_after_collapsing() -> None:
    straight = Citation("ke-tel-001", "M-Pesa's share in the mobile money market")  # straight apostrophe
    curly = Citation("ke-tel-001", "M-Pesa\u2019s   share in the\nmobile money market")
    assert not checks.verified(straight, excerpt("ke-tel-001"), POLICY)
    assert checks.verified(curly, excerpt("ke-tel-001"), POLICY)


@pytest.mark.parametrize(
    ("statement", "ok"),
    [
        ("The rate falls from Sh0.41 to Sh0.3 per minute by March 2029.", True),
        ("The rate falls from Sh0.41 to Sh0.35 per minute by March 2029.", False),  # 0.35 is in no quote
        ("The rate falls by about 27 percent by March 2029.", False),  # a figure from the URL, not a quote
        ("Mobile money share slimmed to 89 percent.", True),
        ("Mobile money share slimmed to 89 billion.", False),  # the scale must match
        ("Mobile money share fell by 2 percent.", False),  # 91 - 89 computed: never in a quote
        ("A four-year glide path cuts termination rates.", True),  # number words count as numbers
        ("A five-year glide path cuts termination rates.", False),
        ("Rates fall to Sh0.3 by 2030.", False),
    ],
)
def test_every_number_must_be_inside_a_cited_quote(statement: str, ok: bool) -> None:
    verdict = check(dataclasses.replace(TELECOM, statement=statement))
    assert isinstance(verdict, Accepted) is ok, verdict
    if not ok:
        assert verdict == Discarded("unsupported_number")


def test_numbers_in_the_title_and_affected_group_are_checked_too() -> None:
    assert check(dataclasses.replace(TELECOM, title="Rates fall 40 percent")) == Discarded("unsupported_number")
    assert check(dataclasses.replace(TELECOM, affected_group="About 3 operators")) == Discarded("unsupported_number")


HEALTH = Draft(
    title="Fraudulent health insurance claims drain the national scheme",
    statement="An audit found Kenya lost Sh11 billion through fraudulent claims to the national health insurer.",
    affected_group="Patients and honest healthcare providers",
    named_orgs=(),
    citations=(
        Citation("ke-hlt-001", "Kenya lost Sh11 billion through fraudulent claims"),
        Citation("ke-hlt-002", "rejected fraudulent health insurance claims amounting to Sh11.6 billion"),
    ),
)


@pytest.mark.parametrize(
    ("figure", "ok"),
    [("Sh11 billion", True), ("Sh11.6 billion", True), ("Sh11.3 billion", False), ("Sh12 billion", False)],
)
def test_the_two_sha_figures_are_never_merged(figure: str, ok: bool) -> None:
    """ke-hlt-001 (Sh11 billion lost) and ke-hlt-002 (Sh11.6 billion rejected) stay apart: an average, a rounding or a
    sum is in neither quote."""
    draft = dataclasses.replace(HEALTH, statement=HEALTH.statement.replace("Sh11 billion", figure))
    verdict = check(draft, "health")
    assert isinstance(verdict, Accepted) is ok, verdict


def test_a_figure_needs_the_quote_that_carries_it() -> None:
    only_first = dataclasses.replace(
        HEALTH, statement=HEALTH.statement.replace("Sh11 billion", "Sh11.6 billion"), citations=HEALTH.citations[:1]
    )
    assert check(only_first, "health") == Discarded("unsupported_number")


@pytest.mark.parametrize(
    ("statement", "declared"),
    [
        ("The Social Health Authority lost money to fraudulent claims.", ()),
        ("SHA lost money to fraudulent claims.", ()),
        ("SHA's losses to fraudulent claims keep growing.", ()),
        ("The national insurer lost money to fraudulent claims.", ("Social Health Authority",)),  # declared only
    ],
)
def test_d45_a_card_naming_an_organisation_needs_an_official_source(statement: str, declared: tuple[str, ...]) -> None:
    """Health has no official excerpt: a card naming anyone is discarded (D-45 default (a))."""
    draft = dataclasses.replace(HEALTH, statement=statement, named_orgs=declared)
    assert check(draft, "health") == Discarded("named_org_without_official")


def test_d45_detection_is_whole_word_and_case_sensitive() -> None:
    fields = ("Clinics shall share data; a CAse study; the treasury bills; M-PESA agents and Airtel Money users",)
    assert checks.named_organisations(fields, (), ALLOWLIST) == ("Safaricom", "Airtel")
    assert checks.named_organisations(("Business Daily reported it",), (), ALLOWLIST) == ("Business Daily",)
    assert checks.named_organisations(("no names here",), ("  Acme  Ltd ",), ALLOWLIST) == ("  Acme  Ltd ",)


SACCO = Draft(
    title="SACCOs need affordable cyber security and reporting tools",
    statement=(
        "Regulated SACCOs held Sh1.21 trillion in assets after a 12.5 percent increase. Talks between SASRA and"
        " deposit-taking SACCOs focused on cybersecurity, quality of regulatory data and financial reporting."
    ),
    affected_group="Deposit-taking SACCOs and their members",
    named_orgs=("SACCO Societies Regulatory Authority",),
    citations=(
        Citation("ke-sac-001", "total assets held by regulated Saccos to Sh1.21 trillion"),
        Citation("ke-sac-004", "cybersecurity, responsible use of technology"),
    ),
)


def test_d45_an_official_cited_source_allows_a_named_organisation() -> None:
    verdict = check(SACCO, "microfinance-saccos")
    assert isinstance(verdict, Accepted), verdict
    assert verdict.text.named_orgs == ("SACCO Societies Regulatory Authority",)  # detected SASRA, declared, once
    without_official = dataclasses.replace(SACCO, citations=SACCO.citations[:1])
    assert check(without_official, "microfinance-saccos") == Discarded("named_org_without_official")


def test_ac_res_1_one_publisher_twice_is_not_enough() -> None:
    """Two Business Daily excerpts are one publisher; Capital FM's two domains would be one too."""
    draft = dataclasses.replace(
        TELECOM,
        statement="The rate falls from Sh0.41 to Sh0.3 by March 2029, and the leader held 89 percent of mobile money.",
        citations=TELECOM.citations[:2],
    )
    assert check(draft) == Discarded("needs_official_or_two_publishers")
    assert not checks.meets_source_rule([excerpt("ke-hlt-001"), excerpt("ke-sac-001")])  # capitalfm .co.ke, .africa
    assert checks.meets_source_rule([excerpt("ke-agr-003")])  # one official source is enough
    assert checks.meets_source_rule([excerpt("ke-agr-001"), excerpt("ke-agr-002")])


def test_the_confidence_formula_and_the_discard_threshold() -> None:
    official = [excerpt("ke-agr-003")]
    # 0.35 * 1.0 + 0.25 * 1/3 + 0.20 * 1 + 0.20 * 1 = 0.8333... rounded down
    assert checks.confidence(official, Decimal(1), AS_OF, POLICY) == Decimal("0.833")
    # a year later the excerpt is 12 months old (freshness 1) and 18 months later archived (0)
    assert checks.confidence(official, Decimal(0), date(2028, 3, 8), POLICY) == Decimal("0.433")
    assert checks.confidence(official, Decimal("0.5"), AS_OF, POLICY) == Decimal("0.733")
    low = dataclasses.replace(POLICY, discard_below=Decimal("0.85"))
    assert checks.check_draft(TELECOM, sent("networks-telecommunications"), ALLOWLIST, low, AS_OF) == Discarded(
        "low_confidence"
    )
    at = dataclasses.replace(POLICY, discard_below=Decimal("0.846"))
    assert isinstance(checks.check_draft(TELECOM, sent("networks-telecommunications"), ALLOWLIST, at, AS_OF), Accepted)


def test_rule_violation_checks_numbers_then_names_then_sources() -> None:
    text = checks.CardText("t", "Sh0.41 per minute", "", ("Safaricom",))
    assert checks.rule_violation(text, [excerpt("ke-tel-001")]) == "unsupported_number"
    assert checks.rule_violation(text, [excerpt("ke-tel-002")]) == "named_org_without_official"
    plain = dataclasses.replace(text, named_orgs=())
    assert checks.rule_violation(plain, [excerpt("ke-tel-002")]) == "needs_official_or_two_publishers"
    assert checks.rule_violation(plain, [excerpt("ke-tel-002"), excerpt("ke-tel-004")]) is None
