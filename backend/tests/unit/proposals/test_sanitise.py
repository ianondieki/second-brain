"""REQ-PROP-02 / AC-PROP-6 (reject half): the Tier-1 sanitiser keeps teaser fields plain text and rejects URLs, bare
domains, email addresses, phone numbers (E.164, 07xx/01xx, spaced and dotted variants) and till/paybill numbers, each
with the field and a plain reason; the summary is at most 150 words. Plain code decides (docs/spec/04 principle 1)."""

from __future__ import annotations

import pytest

from bridge.proposals.sanitise import (
    MAX_SUMMARY_WORDS,
    FieldError,
    check_field,
    contact_findings,
    plain_text,
    sanitise,
    word_count,
)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("<p>Milk <b>spoils</b> before chilling.</p>", "Milk spoils before chilling."),
        ("Line one<br>line two", "Line one line two"),
        ("<script>alert(1)</script>Cold chain", "Cold chain"),
        ("<style>p {color: red}</style>Cold chain", "Cold chain"),
        ("Cold <!-- hidden --> chain", "Cold chain"),
        ("&lt;b&gt;bold&lt;/b&gt; &amp; plain", "bold & plain"),
        ("a < b and c > d", "a < b and c > d"),
        ("zero\u200bwidth\u2060joined", "zerowidthjoined"),
        ("\uff46\uff55\uff4c\uff4c\uff57\uff49\uff44\uff54\uff48", "fullwidth"),
        ("tabs\tand   spaces", "tabs and spaces"),
        ("  first\r\n\r\n\r\n\r\nsecond  ", "first\n\nsecond"),
        ("bell\x07 char", "bell char"),
    ],
)
def test_plain_text_strips_html_and_invisible_characters(raw: str, clean: str) -> None:
    assert plain_text(raw) == clean


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("See https://example.test/demo for more", "contains_url"),
        ("see http://10.0.0.1/app", "contains_url"),
        ("visit www.coldchain.io today", "contains_url"),
        ("ftp://files.example.org", "contains_url"),
        ("mailto:me", "contains_url"),
        ("Try coldchain.co.ke now", "contains_domain"),
        ("our site is COLDCHAIN.COM", "contains_domain"),
        ("coldchain.africa", "contains_domain"),
        ("coldchain [dot] com", "contains_domain"),
        ("coldchain dot co dot ke", "contains_domain"),
        ("write to jane.doe@example.com", "contains_email"),
        ("jane (at) example (dot) com", "contains_email"),
        ("jane [at] gmail", "contains_email"),
        ("call 0712345678", "contains_phone"),
        ("call 0712 345 678 anytime", "contains_phone"),
        ("call 0712.345.678", "contains_phone"),
        ("call 0712-345-678", "contains_phone"),
        ("call 0112 345 678", "contains_phone"),
        ("call +254712345678", "contains_phone"),
        ("call +254 712 345 678", "contains_phone"),
        ("call 254712345678", "contains_phone"),
        ("call (+254) 712-345-678", "contains_phone"),
        ("call 07 12 34 56 78", "contains_phone"),
        ("call +1 (555) 123-4567", "contains_phone"),
        ("call +44 20 7946 0958", "contains_phone"),
        ("Pay via till 123456", "contains_payment_number"),
        ("Paybill: 400200, account 55", "contains_payment_number"),
        ("pay bill no. 247 247", "contains_payment_number"),
        ("Buy Goods number 5123456", "contains_payment_number"),
    ],
)
def test_contact_details_are_found(text: str, code: str) -> None:
    assert code in contact_findings(text)


@pytest.mark.parametrize(
    "text",
    [
        "Milk spoils before it reaches the cooler in 3 of 5 farms.",
        "Saves KES 1,500,000 a year for a SACCO of 12,000 members.",
        "Built with Node.js and Vue.js; see the README.md in Tier 2.",
        "Works offline, e.g. in Turkana, i.e. without data.",
        "Between 2019 2020 and 2021 the losses doubled.",
        "Ph.D. researchers at St. Paul's and Co. op members",
        "Serves 47 counties and 1200 schools.",
        "We look at the dot com era with some humility.",
        "A 10-digit batch id 1234567890 is printed on each crate.",
        "Model number 0712 of the sensor",
        "The till is the shop counter where people pay.",
        "M-Pesa payments reconcile nightly.",
    ],
)
def test_ordinary_teaser_text_passes(text: str) -> None:
    assert contact_findings(text) == []


def test_the_summary_is_at_most_150_words() -> None:
    assert MAX_SUMMARY_WORDS == 150
    words = " ".join(["word"] * MAX_SUMMARY_WORDS)
    assert word_count(words) == MAX_SUMMARY_WORDS
    assert check_field("summary", words) == []
    [error] = check_field("summary", words + " more")
    assert error == FieldError("summary", "too_many_words", "Keep the summary to 150 words or fewer (it has 151 now).")


def test_the_word_limit_applies_only_to_the_summary() -> None:
    long_text = " ".join(["word"] * 400)
    assert check_field("problem_statement", long_text) == []


def test_each_finding_names_the_field_and_a_plain_reason() -> None:
    errors = check_field("title", "Mail jane@example.com or call 0712 345 678")
    assert [(e.field, e.code) for e in errors] == [("title", "contains_email"), ("title", "contains_phone")]
    for error in errors:
        assert error.message
        assert "jane" not in error.message
        assert "0712" not in error.message


def test_a_link_hidden_in_html_is_still_rejected() -> None:
    errors = check_field("summary", '<a href="https://example.test/x">our demo</a> shows it')
    assert [e.code for e in errors] == ["contains_url"]


def test_an_entity_encoded_domain_is_rejected() -> None:
    assert [e.code for e in check_field("summary", "visit coldchain&#46;co&#46;ke")] == ["contains_domain"]


def test_sanitise_cleans_every_field_and_collects_every_error() -> None:
    cleaned, errors = sanitise(
        {
            "title": "<b>Cold-chain alerts</b>",
            "problem_statement": "Milk spoils. Call 0712 345 678.",
            "impact_claims": None,
            "summary": "SMS when a cooler warms. See coldchain.io",
        }
    )
    assert cleaned == {
        "title": "Cold-chain alerts",
        "problem_statement": "Milk spoils. Call 0712 345 678.",
        "impact_claims": None,
        "summary": "SMS when a cooler warms. See coldchain.io",
    }
    assert [(e.field, e.code) for e in errors] == [
        ("problem_statement", "contains_phone"),
        ("summary", "contains_domain"),
    ]


def test_blank_values_become_none() -> None:
    cleaned, errors = sanitise({"title": "  <p> </p> ", "summary": ""})
    assert cleaned == {"title": None, "summary": None}
    assert errors == []
