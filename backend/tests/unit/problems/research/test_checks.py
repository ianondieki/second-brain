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
from bridge.problems.research.text import collapse, has_control

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


@pytest.mark.parametrize(
    ("statement", "excerpt_id"),
    [
        ("The leader earned Sh89m.", "ke-tel-001"),  # the quote says 89 percent
        ("The leader earned Sh89B.", "ke-tel-001"),
        ("The leader earned Sh89 thousand.", "ke-tel-001"),
        ("The leader has 89k agents.", "ke-tel-001"),
        ("The leader earned 89 mn.", "ke-tel-001"),
        ("Share fell by 2 percentage points.", "ke-tel-001"),  # neither 2 nor percentage points in the quote
        ("Share slimmed to 89 percentage points.", "ke-tel-001"),
        ("Fraud cost Sh11m.", "ke-hlt-001"),  # the quote says Sh11 billion
        ("Fraud cost Sh11bn and 11 thousand claims.", "ke-hlt-001"),
        ("Coverage reached 89xyz.", "ke-tel-001"),  # an unknown glued suffix fails closed
        ("Sh89 was the fee.", "ke-tel-001"),  # a bare number needs a bare one
        ("Operators roll out 4G by 2029.", "ke-tel-002"),  # an unknown glued suffix: the quote's four is bare
    ],
)
def test_p11_major_1_a_number_carries_its_scale(statement: str, excerpt_id: str) -> None:
    """P11 review MAJOR 1: an unknown or abbreviated scale was read as a bare number, so "Sh89m" passed on a quote
    saying "89 percent". Letters glued to a number, or a scale word after a space, are its scale, which must match."""
    assert checks.unsupported_numbers([statement], [excerpt(excerpt_id).quote]), statement
    draft = dataclasses.replace(TELECOM, statement=statement)
    assert check(draft) == Discarded("unsupported_number")


@pytest.mark.parametrize(
    ("statement", "excerpt_id"),
    [
        ("Satellite providers pay a licence of at least Sh15m.", "ke-tel-003"),  # the quote says Sh15 million
        ("Satellite providers pay up to 0.4 per cent of turnover.", "ke-tel-003"),  # quote: 0.4 percent
        ("Fraud cost Sh11bn.", "ke-hlt-001"),
        ("Share slimmed to 89% from 91pc.", "ke-tel-001"),
    ],
)
def test_an_abbreviated_scale_matches_the_same_scale_in_words(statement: str, excerpt_id: str) -> None:
    assert checks.unsupported_numbers([statement], [excerpt(excerpt_id).quote]) == [], statement


AGRI = Draft(
    title="Drought losses squeeze grain farmers",
    statement="Farmers lost Sh90-million.",
    affected_group="Grain farmers",
    named_orgs=(),
    citations=(
        Citation("ke-agr-003", "farmers will access the fertiliser at KSh 2,000 per 50 kilogram bag"),
        Citation("ke-agr-002", "import 25 million 90-kilogramme bags of maize"),
    ),
)


@pytest.mark.parametrize(
    "statement",
    [
        "Farmers lost Sh90-million.",  # the reviewer's scenario: the quote's 90 is "90-kilogramme"
        "Farmers lost Sh90 millions.",
        "Farmers lost Sh90 mln.",
        "Farmers lost Sh90 (million).",
        "Farmers lost Sh90 [bn].",
        "Farmers lost Sh90 \u2014 million.",
        "Fertiliser costs Sh2,000 crore.",  # the quote's 2,000 is followed by "per": bare
        "Harvests fell 50 per-cent.",  # the quote's 50 is "50 kilogram"
        "Farmers lost Sh50 billions.",
        "Imports reach 25 billions.",  # the quote's 25 is 25 million
    ],
)
def test_p11_round_2_a_word_after_a_dash_space_or_bracket_is_a_scale(statement: str) -> None:
    """P11 re-review MAJOR: a scale after a hyphen, a space or a bracket was read as a bare number."""
    verdict = check(dataclasses.replace(AGRI, statement=statement), "agriculture")
    assert verdict == Discarded("unsupported_number"), statement


@pytest.mark.parametrize(
    ("statement", "ok"),
    [
        ("Farmers need 90-kilogramme bags of maize.", True),
        ("Farmers need 90 bags of maize.", False),  # "bags" is not what follows 90 in the quote
        ("Fertiliser sells at KSh 2,000 per 50 kilogram bag.", True),
        ("Fertiliser sells at KSh 2,000 for a 50 kilogram bag.", True),  # "for" is a function word
        ("Fertiliser sells at KSh 2,000 shillings a bag.", False),  # an unknown word: fail closed
        ("Imports reach 25 million bags.", True),
        ("Imports reach 25 millions of bags.", True),  # a plural is the same scale
    ],
)
def test_the_word_after_a_number_must_be_the_quotes_unless_it_is_a_function_word(statement: str, ok: bool) -> None:
    """The choice for a word the code does not know: it becomes the number's suffix, so the quote must carry the
    same word after the same number. A function word (a closed class, never a magnitude) leaves the number bare."""
    verdict = check(dataclasses.replace(AGRI, statement=statement), "agriculture")
    assert isinstance(verdict, Accepted) is ok, verdict


def test_numbers_read_every_separator_the_same_way() -> None:
    read = checks.numbers_in
    assert (
        read("Sh90-million")
        == read("Sh90 million")
        == read("Sh90m")
        == read("Sh90 (mln)")
        == {(Decimal(90), "million")}
    )
    assert read("2 percentage points") == {(Decimal(2), "percentage_points")}
    assert read("50 per-cent") == read("50 per cent") == read("50%") == {(Decimal(50), "percent")}
    assert read("a four-year path") == {(Decimal(4), "suffix:year")}
    assert read("Sh0.41 to Sh0.3 per minute by March 2029, while") == {
        (Decimal("0.41"), None),
        (Decimal("0.3"), None),
        (Decimal(2029), None),
    }
    assert read("2026\u20132029 contracting") == {(Decimal(2026), None), (Decimal(2029), "suffix:contracting")}


def test_numbers_in_named_organisations_are_checked_too() -> None:
    """Minor (e): a declared name is text on the card too, so its figures must be in a quote."""
    draft = dataclasses.replace(SACCO, named_orgs=("SACCO Societies Regulatory Authority 2030",))
    assert check(draft, "microfinance-saccos") == Discarded("unsupported_number")


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


def test_d45_detection_is_whole_word_any_case_and_any_dash() -> None:
    fields = ("Clinics shall share data; a CAse study; the treasury bills; M-PESA agents and airtel money users",)
    assert checks.named_organisations(fields, (), ALLOWLIST) == ("Safaricom", "Airtel")
    assert checks.named_organisations(("Business Daily reported it",), (), ALLOWLIST) == ("Business Daily",)
    assert checks.named_organisations(("no names here",), ("  Acme  Ltd ",), ALLOWLIST) == ("  Acme  Ltd ",)


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("the treasury bills fell", ()),  # lower case: a common word, not the organisation
        ("the Treasury said", ("National Treasury",)),
        ("THE TREASURY SAID", ("National Treasury",)),
        ("the Tre\u200basury said", ("National Treasury",)),  # nothing invisible hides it
        ("the national treasury said", ("National Treasury",)),  # the full name matches in any case
    ],
)
def test_a_case_sensitive_alias_matches_only_as_written_or_in_capitals(text: str, found: tuple[str, ...]) -> None:
    """P11 re-review MINOR 2: "Treasury" is back as a capitalised-only alias."""
    assert checks.named_organisations((text,), (), ALLOWLIST) == found


@pytest.mark.parametrize(
    "hidden",
    [
        "M\u2011Pesa",  # non-breaking hyphen (NFKC: U+2010)
        "M\u2010Pesa",
        "M\u2014Pesa",  # em dash
        "M\u2212Pesa",  # minus sign
        "M Pesa",
        "MPESA",
        "safaricom",  # lower case
        "SAFARICOM",
        "\uff33\uff41\uff46\uff41\uff52\uff49\uff43\uff4f\uff4d",  # full-width letters (NFKC: ASCII)
        "Safari\u200bcom",  # zero-width space
        "Safari\u00adcom",  # soft hyphen
        "Safari\u200dcom",  # zero-width joiner
        "Safari\u034fcom",  # combining grapheme joiner (Mn, default-ignorable)
        "Safari\ufe0fcom",  # variation selector
        "Safari\u115fcom",  # Hangul choseong filler (Lo)
        "Safari\u1160com",  # Hangul jungseong filler
        "Safari\u3164com",  # Hangul filler
        "Safari\u2800com",  # braille pattern blank
        "Safari\U000e0041com",  # a tag character
    ],
)
def test_d45_a_hidden_name_is_still_found(hidden: str) -> None:
    """P11 review MAJOR 2: none of these spellings may slip a company past D-45 with ``named_orgs=()``."""
    assert checks.named_organisations((f"{hidden} agents keep most customers",), (), ALLOWLIST) == ("Safaricom",)
    draft = dataclasses.replace(TELECOM, statement=f"{hidden} agents keep most customers.", named_orgs=())
    verdict = check(draft)
    assert isinstance(verdict, Discarded), verdict  # never accepted with the name unchecked
    invisible = any(
        ord(c) in (0x200B, 0x00AD, 0x200D, 0x034F, 0xFE0F, 0x115F, 0x1160, 0x3164, 0x2800, 0xE0041) for c in hidden
    )
    assert verdict.reason == ("control_character" if invisible else "named_org_without_official")


@pytest.mark.parametrize("bidi", ["\u202e", "\u202d", "\u2066", "\u2067", "\u2068", "\u2069", "\u200e", "\ufeff"])
def test_a_bidi_or_format_character_in_any_field_is_refused(bidi: str) -> None:
    """A right-to-left override in a title would be stored and served reordered: refused, never repaired."""
    for field in ("title", "statement", "affected_group"):
        value = f"Operators{bidi} struggle"
        changes: dict[str, Any] = {field: value}
        assert check(dataclasses.replace(TELECOM, **changes)) == Discarded("control_character"), field
    assert check(dataclasses.replace(TELECOM, named_orgs=(f"Acme{bidi}",))) == Discarded("control_character")


@pytest.mark.parametrize(
    "lookalike",
    [
        "S\u0430faricom",  # Cyrillic a
        "Safari\u0441om",  # Cyrillic es
        "\u0405afaricom",  # Cyrillic dze
        "Saf\u03b1ricom",  # Greek alpha
        "Airtel \u0661\u0662",  # Arabic-Indic digits
    ],
)
def test_a_look_alike_from_another_script_is_refused(lookalike: str) -> None:
    """P11 re-review MINOR 1: "S\u0430faricom" (U+0430) is not "Safaricom" to the detection, so letters outside the
    Latin script (and non-ASCII digits, combining marks) are refused in a card's title, statement and group."""
    for field in ("title", "statement", "affected_group"):
        changes: dict[str, Any] = {field: f"{lookalike} agents keep most customers"}
        assert check(dataclasses.replace(TELECOM, **changes)) == Discarded("non_latin_text"), field
    latin = dataclasses.replace(TELECOM, statement="Caf\u00e9 owners and na\u00efve \u00fcsers pay KSh 2,000.")
    assert checks.clean_text(latin.title, latin.statement, "", ()) != "non_latin_text"  # Latin accents pass


def test_nfkc_never_creates_a_control_or_format_character() -> None:
    """Why ``has_control`` may check the text as given: no code point's NFKC form holds a C0/C1 control or a Cf
    character unless the code point is one."""
    import sys
    import unicodedata

    def hidden(text: str) -> bool:
        return any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or unicodedata.category(c) == "Cf" for c in text)

    created = [
        cp for cp in range(sys.maxunicode + 1) if not hidden(chr(cp)) and hidden(unicodedata.normalize("NFKC", chr(cp)))
    ]
    assert created == []


def test_collapse_normalises_nfkc_and_keeps_curly_quotes() -> None:
    assert collapse("M\u2011Pesa\u00a0agents\u3000now") == "M\u2010Pesa agents now"
    assert collapse("M-Pesa\u2019s share \u2013 slimmed") == "M-Pesa\u2019s share \u2013 slimmed"
    for hidden in ("a\u00adb", "a\u202eb", "a\x9bb", "a\x00b"):
        assert has_control(hidden), repr(hidden)
    assert not has_control("M-Pesa\u2019s share \u2013 Sh0.41")


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
