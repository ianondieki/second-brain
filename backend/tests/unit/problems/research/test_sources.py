"""REQ-RES-01 / REQ-RES-02: the saved excerpts load only against the country's allowlist (docs/spec/06 6.5; D-38).

Given the saved file, when it loads, then its 19 excerpts in 4 niches load, the two background fixtures are archived
on 2026-09-29 and never offered to a run, and a run gets 3-5 excerpts per niche. Given a bad excerpt (a host off the
allowlist, a publisher that is not its domain's, a news page claiming to be official, an http URL, a user-info or port
URL, a long or control-character quote, a retrieval before publication, a duplicate id), the whole file is refused.
A second country's allowlist (``tests/fixtures/sources/ug.yaml``) loads on its own.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import (
    EXCERPTS_FILE,
    SOURCES_DIR,
    Freshness,
    SourceError,
    add_months,
    freshness,
    freshness_score,
    load_allowlist,
    load_catalogue,
    parse_allowlist,
    parse_excerpts,
    url_host,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "sources"
RETRIEVED = date(2026, 9, 29)
ALLOWLIST_DOMAINS = {
    "capitalfm.co.ke",
    "capitalfm.africa",
    "kilimo.go.ke",
    "www.sasra.go.ke",
    "www.ca.go.ke",
    "businessdailyafrica.com",
    "standardmedia.co.ke",
    "the-star.co.ke",
}


def raw_excerpts() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(EXCERPTS_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def parse_one(**overrides: Any) -> None:
    data = raw_excerpts()
    data["excerpts"] = [data["excerpts"][0] | overrides]
    parse_excerpts(data, {"KE": load_allowlist("KE")}, get_research_policy())


def test_the_saved_file_loads_19_excerpts_in_4_niches() -> None:
    catalogue = load_catalogue()
    assert len(catalogue.excerpts) == 19
    assert catalogue.niches("KE") == ("agriculture", "health", "microfinance-saccos", "networks-telecommunications")
    assert set(catalogue.allowlists) == {"KE"}
    official = {e.id for e in catalogue.excerpts if e.official}
    assert official == {"ke-tel-005", "ke-agr-003", "ke-agr-004", "ke-sac-003", "ke-sac-004", "ke-sac-005"}
    assert all(e.quote == " ".join(e.quote.split()) for e in catalogue.excerpts)


def test_the_allowlist_is_the_researchers_list_with_three_official_domains() -> None:
    allowlist = load_allowlist("KE")
    assert {d.domain for d in allowlist.domains} == ALLOWLIST_DOMAINS
    assert {d.domain for d in allowlist.domains if d.official} == {"kilimo.go.ke", "www.sasra.go.ke", "www.ca.go.ke"}
    capital = {d.publisher for d in allowlist.domains if d.domain.startswith("capitalfm")}
    assert capital == {"Capital FM Kenya"}  # one publisher on two domains: never two independent publishers


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.businessdailyafrica.com/bd/x", True),  # a subdomain of an allowlisted domain
        ("https://businessdailyafrica.com/bd/x", True),
        ("https://kilimo.go.ke/x/", True),
        ("https://sasra.go.ke/x", False),  # only www.sasra.go.ke is listed
        ("https://evilbusinessdailyafrica.com/x", False),  # a suffix is not a subdomain
        ("https://businessdailyafrica.com.evil.example/x", False),
        ("https://nation.africa/kenya/x", False),  # not on the prototype list (403 to non-browser clients)
        ("http://kilimo.go.ke/x", False),  # https only
        ("https://user@kilimo.go.ke/x", False),
        ("https://kilimo.go.ke:8443/x", False),
        ("https://kilimo.go.ke/a b", False),
        ("https://kilimo.go.ke/a\x07b", False),
    ],
)
def test_a_url_is_allowed_only_on_an_allowlisted_https_host(url: str, allowed: bool) -> None:
    assert (load_allowlist("KE").domain_of(url) is not None) is allowed


def test_url_host_is_the_lower_case_ascii_host_or_nothing() -> None:
    assert url_host("https://WWW.CA.GO.KE/page") == "www.ca.go.ke"
    assert url_host("https://xn--example.ke/") == "xn--example.ke"
    assert url_host("https://exämple.ke/") is None
    assert url_host("ftp://www.ca.go.ke/") is None
    assert url_host("https://" + "a" * 1000 + ".ke/") is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"url": "https://nation.africa/kenya/news-5570014"}, "not on the KE source allowlist"),
        ({"url": "https://www.ca.go.ke.example.com/x"}, "not on the KE source allowlist"),
        ({"url": "http://www.businessdailyafrica.com/bd/x"}, "https on a plain ASCII host"),
        ({"url": "https://www.businessdailyafrica.com:444/bd/x"}, "https on a plain ASCII host"),
        ({"publisher": "Nation"}, "the publisher of businessdailyafrica.com"),
        ({"source_type": "official"}, "only an official allowlisted domain"),
        ({"source_type": "rumour"}, "source_type must be one of"),
        ({"quote": "word " * 61}, "at most 60 words"),
        ({"quote": "a quote with a \x00 null"}, "without control codes"),
        ({"quote": "   "}, "quote must be non-empty"),
        ({"published_date": "2026-13-01"}, "published_date must be an ISO date"),
        ({"retrieved_at": "2026-01-01"}, "retrieved before it was published"),
        ({"id": "KE TEL 1"}, "id must be"),
        ({"id": "ke-" + "x" * 30}, "id must be"),
        ({"niche": "Networks!"}, "niche must be a niche slug"),
        ({"country": "UG"}, "no source allowlist for UG"),
        ({"extra": "x"}, "exactly"),
    ],
)
def test_a_bad_excerpt_refuses_the_whole_file(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(SourceError, match=message):
        parse_one(**overrides)


def test_an_official_domain_excerpt_must_say_official() -> None:
    data = raw_excerpts()
    official = next(e for e in data["excerpts"] if e["id"] == "ke-agr-003")
    data["excerpts"] = [official | {"source_type": "news"}]
    with pytest.raises(SourceError, match="only an official allowlisted domain"):
        parse_excerpts(data, {"KE": load_allowlist("KE")}, get_research_policy())


def test_a_duplicate_id_refuses_the_file() -> None:
    data = raw_excerpts()
    data["excerpts"] = [data["excerpts"][0], dict(data["excerpts"][0])]
    with pytest.raises(SourceError, match="used twice"):
        parse_excerpts(data, {"KE": load_allowlist("KE")}, get_research_policy())


def test_whitespace_in_a_quote_is_collapsed_not_folded() -> None:
    data = raw_excerpts()
    first = data["excerpts"][0]
    data["excerpts"] = [first | {"quote": "As of\n December\t2025,  M-Pesa’s share – slimmed."}]
    [excerpt] = parse_excerpts(data, {"KE": load_allowlist("KE")}, get_research_policy())
    assert excerpt.quote == "As of December 2025, M-Pesa’s share – slimmed."  # curly apostrophe and en dash kept


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"domains": [{"domain": "nation.africa", "publisher": "Nation", "official": True}]}, "only a government"),
        ({"domains": [{"domain": "Nation.Africa", "publisher": "Nation", "official": False}]}, "lower-case host"),
        ({"domains": [{"domain": "a.ke", "publisher": " ", "official": False}]}, "needs a publisher"),
        ({"domains": []}, "non-empty list"),
        ({"country": "Kenya"}, "alpha-2"),
        ({"organisations": [{"name": "X", "aliases": []}]}, "at least one alias"),
        ({"organisations": [{"name": "X", "aliases": [" X "]}]}, "trimmed"),
        ({"version": 2}, "version 1"),
    ],
)
def test_a_malformed_allowlist_is_refused(change: dict[str, Any], message: str) -> None:
    data = yaml.safe_load((SOURCES_DIR / "ke.yaml").read_text(encoding="utf-8")) | change
    with pytest.raises(SourceError, match=message):
        parse_allowlist(data)


def test_a_second_country_allowlist_loads_from_its_own_file() -> None:
    allowlist = load_allowlist("UG", FIXTURES)
    assert allowlist.country == "UG"
    assert allowlist.domain_of("https://www.ubos.go.ug/stats") is not None
    assert allowlist.domain_of("https://www.ca.go.ke/x") is None  # Kenya's domains are not Uganda's
    with pytest.raises(SourceError, match="no source allowlist for TZ"):
        load_allowlist("TZ", FIXTURES)
    with pytest.raises(SourceError, match="not a country code"):
        load_allowlist("../ke")


def test_the_stale_fixtures_are_archived_and_never_offered_to_a_run() -> None:
    catalogue, policy = load_catalogue(), get_research_policy()
    states = {e.id: freshness(e, RETRIEVED, policy) for e in catalogue.excerpts}
    assert {i for i, s in states.items() if s is Freshness.ARCHIVED} == {"ke-tel-005", "ke-agr-004"}
    offered = {n: [e.id for e in catalogue.usable(n, "KE", RETRIEVED, policy)] for n in catalogue.niches("KE")}
    assert offered == {
        "agriculture": ["ke-agr-003", "ke-agr-001", "ke-agr-002"],
        "health": ["ke-hlt-004", "ke-hlt-003", "ke-hlt-005", "ke-hlt-002", "ke-hlt-001"],
        "microfinance-saccos": ["ke-sac-001", "ke-sac-003", "ke-sac-005", "ke-sac-004", "ke-sac-002"],
        "networks-telecommunications": ["ke-tel-003", "ke-tel-001", "ke-tel-002", "ke-tel-004"],
    }
    assert all(policy.min_excerpts <= len(ids) <= policy.max_excerpts for ids in offered.values())


def test_freshness_is_one_until_12_months_and_zero_from_18() -> None:
    catalogue, policy = load_catalogue(), get_research_policy()
    excerpt = catalogue.get("ke-tel-001")
    assert excerpt is not None and excerpt.published_date == date(2026, 4, 3)
    assert freshness_score(excerpt, date(2027, 4, 2), policy) == 1
    assert freshness(excerpt, date(2027, 4, 3), policy) is Freshness.STALE
    assert freshness_score(excerpt, date(2027, 4, 3), policy) == 1  # the stale day itself: the slope starts here
    assert 0 < freshness_score(excerpt, date(2027, 7, 3), policy) < 1
    assert freshness(excerpt, date(2027, 10, 3), policy) is Freshness.ARCHIVED
    assert freshness_score(excerpt, date(2027, 10, 3), policy) == 0
    assert add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
