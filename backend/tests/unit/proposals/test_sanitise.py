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


# --- review round 1 (MAJOR 1, MAJOR 2): "@" before a domain, and Unicode evasions ---------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Write to janedoe @gmail.com for a demo",
        "Write to janedoe@ gmail.com for a demo",
        "Write to janedoe @ gmail.co.ke",
        "Reach us @gmail.com",
        "jane<b></b>@gmail.com",
        "jane<span>@</span>gmail.com",
    ],
)
def test_an_at_sign_before_a_domain_is_an_email(text: str) -> None:
    assert "contains_email" in [e.code for e in check_field("summary", text)]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("mail janedoe@gm\u0430il.com", "contains_email"),  # Cyrillic a
        ("see ex\u0430mple.com", "contains_domain"),  # Cyrillic a
        ("see example.c\u043em", "contains_domain"),  # Cyrillic o
        ("see \u0435x\u0430mpl\u0435.\u03bfrg", "contains_domain"),  # Cyrillic e/a, Greek omicron
        ("see coldchain\u3164.com", "contains_domain"),  # Hangul filler
        ("see coldchain.\u2800com", "contains_domain"),  # Braille blank
        ("see cold\u115fchain.co\u1160.ke", "contains_domain"),  # Hangul fillers
        ("see coldchain\uffa0.com", "contains_domain"),  # halfwidth Hangul filler
        ("see coldchain\u3002com", "contains_domain"),  # ideographic full stop
        ("see coldchain\uff61co\uff61ke", "contains_domain"),  # halfwidth ideographic full stop
        ("call \u0660\u0667\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668", "contains_phone"),  # Arabic-Indic
        ("call \u06f0\u06f7\u06f1\u06f2 \u06f3\u06f4\u06f5 \u06f6\u06f7\u06f8", "contains_phone"),  # Persian
        ("call \u0966\u096d\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e", "contains_phone"),  # Devanagari
        ("mail jane@gma\u0301il.com", "contains_email"),  # a combining accent
    ],
)
def test_unicode_evasions_are_seen_through(text: str, code: str) -> None:
    assert code in [e.code for e in check_field("summary", text)]


def test_the_cleaned_text_is_kept_as_written() -> None:
    cleaned, errors = sanitise(
        {"summary": "Serves \u0441\u0435\u043b\u043e villages"}
    )  # Cyrillic "\u0441\u0435\u043b\u043e"
    assert errors == []
    assert cleaned == {"summary": "Serves \u0441\u0435\u043b\u043e villages"}


def test_an_at_sign_with_a_number_is_not_an_email() -> None:
    assert check_field("summary", "Pumps run @ 3.5 bar and cost KES 50 @ 10%") == []


# --- review round 1 MINORs --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("call 0712/345/678", "contains_phone"),
        ("call 0712,345,678", "contains_phone"),
        ("call 0712_345_678", "contains_phone"),
        ("Use 123456 till", "contains_payment_number"),
        ("send to 400200 (paybill)", "contains_payment_number"),
        ("see coldchain[.]co[.]ke", "contains_domain"),
        ("see coldchain (.) com", "contains_domain"),
        ("see coldchain . com", "contains_domain"),
        ("mail jane (at) example [dot] com", "contains_email"),
    ],
)
def test_more_separators_and_defanged_forms(text: str, code: str) -> None:
    assert code in [e.code for e in check_field("summary", text)]


@pytest.mark.parametrize(
    "text",
    ["10000 farmers till the land", "Scores rose from 2019 till 2021", "It ends here . Then it starts again"],
)
def test_ordinary_text_with_the_new_rules_passes(text: str) -> None:
    assert check_field("summary", text) == []


def test_words_count_across_punctuation_and_blank_fillers() -> None:
    assert word_count("don't stop well-known") == 3
    assert word_count("a,b,c,d") == 4
    assert word_count("word\u3164word\u2800word") == 3
    assert word_count("- -- ---") == 0
    joined = ",".join(["w"] * 151)
    assert [e.code for e in check_field("summary", joined)] == ["too_many_words"]


def test_the_length_is_checked_after_cleaning() -> None:
    title = "\ufdfa" * 10  # 10 characters; NFKC makes each one 18
    [error] = check_field("title", title)
    assert (error.field, error.code) == ("title", "too_long")
    assert check_field("title", "x" * 120) == []
    assert [e.code for e in check_field("new_problem.title", "y" * 91)] == ["too_long"]
