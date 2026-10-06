"""REQ-DEV-02 (D-60; P22 card B): the trends' excerpt list loads only against the TECH allowlist.

Given the saved pair (``sources/tech.yaml``, ``seed/trend_excerpts.yaml``), when it loads, then its 24 excerpts in 8
topics load, every one official on an official TECH domain; the research catalogue is unchanged (19 KE excerpts).
Given a bad trend excerpt (a host off the list, a publisher that is not its domain's, a non-official source type, an
http URL, a URL over 400 characters, a long quote, an unknown publisher kind, a ``niche`` key, a country, a long topic
slug, a duplicate id), the whole file is refused. A TECH domain that is not official refuses the allowlist, and a
research excerpt cannot name the TECH allowlist.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.sources import (
    EXCERPTS_FILE,
    SOURCES_DIR,
    TECH,
    TREND_EXCERPTS_FILE,
    CatalogueKind,
    SourceError,
    get_catalogue,
    load_allowlist,
    load_catalogue,
    parse_allowlist,
    parse_excerpts,
)

TOPICS = ("ai", "cloud", "databases", "kenya-ict", "languages", "mobile", "security", "web")


def raw_trends() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(TREND_EXCERPTS_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def parse_one(**overrides: Any) -> None:
    data = raw_trends()
    data["excerpts"] = [data["excerpts"][0] | overrides]
    parse_excerpts(data, {TECH: load_allowlist(TECH)}, get_research_policy(), kind=CatalogueKind.TRENDS)


def test_the_tech_pair_loads_24_official_excerpts_in_8_topics() -> None:
    catalogue = load_catalogue(kind=CatalogueKind.TRENDS)
    assert len(catalogue.excerpts) == 24
    assert set(catalogue.allowlists) == {TECH}
    assert tuple(sorted({e.topic_slug for e in catalogue.excerpts})) == TOPICS
    assert all(e.official and e.source_type == "official" and e.country == TECH for e in catalogue.excerpts)
    assert {e.publisher_kind for e in catalogue.excerpts} == {"project", "vendor", "standards", "regulator"}
    assert all(e.quote == " ".join(e.quote.split()) for e in catalogue.excerpts)
    assert all(len(e.url) <= 400 and len(e.quote) <= 600 for e in catalogue.excerpts)
    assert get_catalogue(CatalogueKind.TRENDS).excerpts == catalogue.excerpts


def test_the_tech_allowlist_is_official_throughout_with_organisations() -> None:
    allowlist = load_allowlist(TECH)
    assert allowlist.country == TECH
    assert len(allowlist.domains) == 14
    assert all(d.official for d in allowlist.domains)
    names = {o.name for o in allowlist.organisations}
    assert {"GitHub", "Amazon Web Services", "Apple", "Microsoft", "PostgreSQL"} <= names
    go = next(o for o in allowlist.organisations if o.name == "The Go Project")
    assert any(a.text == "Go" and a.case_sensitive for a in go.aliases)  # a common word: as written or in capitals


def test_the_research_catalogue_is_unchanged() -> None:
    research = get_catalogue()
    assert len(research.excerpts) == 19
    assert set(research.allowlists) == {"KE"}
    assert all(e.publisher_kind is None for e in research.excerpts)
    assert load_catalogue(EXCERPTS_FILE).excerpts == research.excerpts


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"url": "https://docs.python.org/3/whatsnew/3.15.html"}, "not on the TECH source allowlist"),
        ({"url": "https://blog.python.org.example.com/x"}, "not on the TECH source allowlist"),
        ({"url": "http://blog.python.org/2026/10/x/"}, "https on a plain ASCII host"),
        ({"url": "https://blog.python.org/" + "x" * 400}, "https on a plain ASCII host"),
        ({"publisher": "Python"}, "the publisher of blog.python.org"),
        ({"source_type": "blog"}, "only an official allowlisted domain"),
        ({"quote": "word " * 61}, "at most 60 words"),
        ({"quote": "a quote naming Git​Hub"}, "without control codes"),
        ({"publisher_kind": "influencer"}, "publisher_kind must be one of"),
        ({"topic_slug": "Languages!"}, "topic_slug must be a topic slug"),
        ({"topic_slug": "x" * 41}, "at most 40 characters"),
        ({"country": "KE"}, "cannot name the KE allowlist"),
        ({"retrieved_at": "2026-01-01"}, "retrieved before it was published"),
        ({"extra": "x"}, "exactly"),
    ],
)
def test_a_bad_trend_excerpt_refuses_the_whole_file(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(SourceError, match=message):
        parse_one(**overrides)


def test_a_trend_excerpt_has_topic_slug_and_publisher_kind_not_niche() -> None:
    data = raw_trends()
    first = dict(data["excerpts"][0])
    first["niche"] = first.pop("topic_slug")
    data["excerpts"] = [first]
    with pytest.raises(SourceError, match="exactly"):
        parse_excerpts(data, {TECH: load_allowlist(TECH)}, get_research_policy(), kind=CatalogueKind.TRENDS)
    data["excerpts"] = [{k: v for k, v in raw_trends()["excerpts"][0].items() if k != "publisher_kind"}]
    with pytest.raises(SourceError, match="exactly"):
        parse_excerpts(data, {TECH: load_allowlist(TECH)}, get_research_policy(), kind=CatalogueKind.TRENDS)


def test_a_duplicate_trend_id_refuses_the_file() -> None:
    data = raw_trends()
    data["excerpts"] = [data["excerpts"][0], dict(data["excerpts"][0])]
    with pytest.raises(SourceError, match="used twice"):
        parse_excerpts(data, {TECH: load_allowlist(TECH)}, get_research_policy(), kind=CatalogueKind.TRENDS)


def test_a_tech_domain_must_be_official() -> None:
    data = yaml.safe_load((SOURCES_DIR / "tech.yaml").read_text(encoding="utf-8"))
    data["domains"][0] = data["domains"][0] | {"official": False}
    with pytest.raises(SourceError, match="must be official"):
        parse_allowlist(data)


def test_each_kind_reads_only_its_own_allowlists() -> None:
    research = yaml.safe_load(EXCERPTS_FILE.read_text(encoding="utf-8"))
    research["excerpts"] = [research["excerpts"][0] | {"country": TECH}]
    with pytest.raises(SourceError, match="cannot name the TECH allowlist"):
        parse_excerpts(research, {TECH: load_allowlist(TECH)}, get_research_policy())
    with pytest.raises(SourceError, match="no source allowlist for TECH"):
        parse_excerpts(raw_trends(), {"KE": load_allowlist("KE")}, get_research_policy(), kind=CatalogueKind.TRENDS)
