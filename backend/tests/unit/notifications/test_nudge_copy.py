"""REQ-NOT-05 (AC-MAIL-5's rule for P28's notices): EM5, EM6 (both versions), the escalations, the milestone reminder
and the procurement route's notice are fixed copy in English and Kiswahili, with escaped, unlinkable fields: a
proposal title or an organisation's name holding a domain, an address, a link or markup reaches neither part of the
email in a form a mail client links or renders, and the only link is the platform's tracker."""

from __future__ import annotations

import re
import string
from datetime import date
from uuid import UUID

import pytest

from bridge.models.enums import ProcurementRoute
from bridge.notifications import nudge_copy as nc

ENGAGEMENT = UUID("01900000-0000-7000-8000-00000000000b")
HOSTILE = nc.Values(
    org='Evil Org <script>alert("x")</script> evil.example',
    title="Visit http://phish.example/now or mail boss@evil.example\nnext line",
    on=date(2026, 10, 9),
    days=3,
    expires=date(2026, 10, 19),
    route=ProcurementRoute.RFQ_TENDER,
    seq=2,
)


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_notice_has_both_languages_with_the_same_placeholders() -> None:
    allowed = {"org", "title", "date", "days", "expires", "route", "seq"}
    for name, by_locale in nc.COPY.items():
        assert set(by_locale) == set(nc.LOCALES), name
        en, sw = by_locale["en"], by_locale["sw"]
        for part in ("title", "body", "subject"):
            assert placeholders(getattr(en, part)) == placeholders(getattr(sw, part)), (name, part)
        assert {p for text in en.paragraphs for p in placeholders(text)} == {
            p for text in sw.paragraphs for p in placeholders(text)
        }, name
        assert bool(en.subject) == bool(en.paragraphs) == bool(sw.subject) == bool(sw.paragraphs), name
        everything = [en.title, en.body, en.subject, *en.paragraphs, sw.title, sw.body, sw.subject, *sw.paragraphs]
        assert {p for text in everything for p in placeholders(text)} <= allowed, name
        for text in everything:  # no statute is cited (P28 card: no citations in the copy)
            assert not re.search(r"(?i)\b(PPADA|PPP Act|section|s\.\s?\d|Act,? \d{4})", text), (name, text)
    assert set(nc.ROUTES["en"]) == set(nc.ROUTES["sw"]) == set(ProcurementRoute)


def test_dates_and_languages() -> None:
    assert nc.date_text(date(2026, 10, 9), "en") == "9 Oct 2026"
    assert nc.date_text(date(2026, 10, 9), "sw") == "9 Oktoba 2026"
    assert nc.date_text(date(2026, 1, 31), "sw") == "31 Januari 2026"
    assert (nc.locale_of("sw"), nc.locale_of("en"), nc.locale_of(None), nc.locale_of("fr")) == ("sw", "en", "en", "en")


def test_the_wording_fills_its_values_in_the_readers_language() -> None:
    values = nc.Values(org="County C", title="Market fees", on=date(2026, 10, 20), route=ProcurementRoute.DIRECT)
    en = nc.wording("route_chosen", "en", values)
    assert en.body == (
        'County C chose how it will buy "Market fees": direct procurement. Its contact will reach you by 20 Oct 2026.'
    )
    sw = nc.wording("route_chosen", "sw", values)
    assert sw.title == "Njia ya ununuzi imechaguliwa"
    assert "ununuzi wa moja kwa moja" in sw.body
    assert "20 Oktoba 2026" in sw.body
    escalation = nc.wording(
        "contact_escalation", "en", nc.Values(org="Telco A", title="T", on=date(2026, 10, 9), days=3)
    )
    assert "3 business days" in escalation.body
    assert "(non-binding)" in escalation.body  # every "approved" carries its qualifier


@pytest.mark.parametrize("locale", nc.LOCALES)
@pytest.mark.parametrize("name", [name for name, copy in nc.COPY.items() if copy["en"].subject])
def test_fields_are_escaped_and_unlinkable_in_both_parts(locale: nc.Locale, name: str) -> None:
    words = nc.wording(name, locale, HOSTILE)
    for line in (words.title, words.body, words.subject):
        assert "\n" not in line
    rendered = nc.render(
        words,
        locale,
        engagement_id=ENGAGEMENT,
        path=f"/dev/engagements/{ENGAGEMENT}",
        base_url="https://app.example/",
        product="Wazo",
    )
    assert "<script>" not in rendered.html  # markup is escaped in the HTML part (the text part is text)
    for part in (rendered.subject, rendered.text, rendered.html):
        assert "http://phish" not in part
        assert "phish.example" not in part
        assert "boss@evil" not in part
        assert "evil.example" not in part
    if "{org}" in "".join((nc.COPY[name][locale].subject, *nc.COPY[name][locale].paragraphs)):
        assert "&lt;script&gt;" in rendered.html  # the HTML part escapes the organisation's markup
    links = re.findall(r'href="([^"]+)"', rendered.html)
    assert links
    assert all(link.startswith("https://app.example/") for link in links)
    urls = re.findall(r"https?://\S+", rendered.text)
    assert urls
    assert all(url.startswith("https://app.example/") for url in urls)
    assert f'lang="{locale}"' in rendered.html
    chrome = nc.CHROME[locale]
    assert chrome["cta"] in rendered.text
    assert chrome["cta"] in rendered.html
    assert f"{chrome['ref']} {ENGAGEMENT}" in rendered.text
    assert chrome["manage"] in rendered.html


def test_render_refuses_a_link_off_the_platform_and_a_notice_without_an_email() -> None:
    words = nc.wording("contact_overdue_org", "en", HOSTILE)
    for path in ("https://evil.example/x", "//evil.example/x", "dev/engagements"):
        with pytest.raises(ValueError, match="platform path"):
            nc.render(words, "en", engagement_id=ENGAGEMENT, path=path, base_url="https://app.example", product="W")
    in_app = nc.wording("milestone_reminder", "en", HOSTILE)
    assert (in_app.subject, in_app.paragraphs) == ("", ())
    with pytest.raises(ValueError, match="no email"):
        nc.render(in_app, "en", engagement_id=ENGAGEMENT, path="/org/engagements/x", base_url="https://a", product="W")


def test_em5_and_em6_say_what_the_matrix_asks() -> None:
    """EM6 tells both sides the date missed and when the engagement expires; EM5 asks for the signature by its date."""
    values = nc.Values(org="Telco A", title="Alerts", on=date(2026, 10, 9), expires=date(2026, 10, 19))
    org = nc.wording("contact_overdue_org", "en", values)
    developer = nc.wording("contact_overdue_developer", "en", values)
    assert org.subject == developer.subject == 'Contact overdue: "Alerts"'
    assert "was 9 Oct 2026" in org.paragraphs[0]
    assert "expires on 19 Oct 2026" in org.paragraphs[1]
    assert "expires on 19 Oct 2026" in developer.paragraphs[1]
    assert "Telco A said its contact would reach you" in developer.body
    em5 = nc.wording("nda_reminder_developer", "sw", values)
    assert em5.subject.startswith("Sahihi inahitajika")
    assert "9 Oktoba 2026" in em5.body
