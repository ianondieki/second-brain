"""REQ-DEV-01 (D-59; P22 card A): the curated source list of Today's five and each day's sample of it."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

import pytest
import yaml

from bridge.problems.research.sources import url_host
from bridge.quiz.policy import get_quiz_policy
from bridge.quiz.sources import (
    SOURCES_FILE,
    QuizSourceError,
    SourceList,
    load_sources,
    parse_sources,
    sample_for_day,
)

DAY = date(2026, 10, 6)


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_list_loads_with_40_to_60_official_pages() -> None:
    sources = load_sources()
    assert 40 <= len(sources.sources) <= 60
    ids = [s.id for s in sources.sources]
    assert len(set(ids)) == len(ids)
    assert len({s.url for s in sources.sources}) == len(ids)
    assert all(s.host == url_host(s.url) for s in sources.sources)
    assert all(s.topic in sources.topics for s in sources.sources)
    assert set(sources.topics) == {s.topic for s in sources.sources}
    assert len(sources.topics) >= get_quiz_policy().sources_per_prompt  # a day's sample has one page per topic


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(version=2), "version 1"),
        (lambda d: d.update(topics=[]), "topics"),
        (lambda d: d.update(topics=["python", "python"]), "topics"),
        (lambda d: d.update(topics=["Python"]), "topics"),
        (lambda d: d.update(sources=[]), "non-empty list"),
        (lambda d: d["sources"][1].update(id=d["sources"][0]["id"]), "duplicate ids"),
        (lambda d: d["sources"][1].update(url=d["sources"][0]["url"], host=d["sources"][0]["host"]), "duplicate urls"),
        (lambda d: d["sources"][0].update(id="Bad_Id"), "an id is"),
        (lambda d: d["sources"][0].update(id="x" * 41), "an id is"),
        (lambda d: d["sources"][0].update(topic="gossip"), "unknown topic"),
        (lambda d: d["sources"][0].update(host="evil.example"), "host must be"),
        (lambda d: d["sources"][0].update(url="http://docs.python.org/3/"), "https"),
        (lambda d: d["sources"][0].update(url="https://user@docs.python.org/3/"), "https"),
        (lambda d: d["sources"][0].update(url="https://docs.python.org/" + "a" * 400), "400"),
        (lambda d: d["sources"][0].update(title=""), "title must be non-empty"),
        (lambda d: d["sources"][0].update(title="x" * 161), "160"),
        (lambda d: d["sources"][0].update(title="Python  data model"), "collapsed"),
        (lambda d: d["sources"][0].update(title="Python дata model"), "Latin"),
        (lambda d: d["sources"][0].update(title="Python​data"), "control"),
        (lambda d: d["sources"][0].update(colour="red"), "exactly"),
        (lambda d: d["topics"].append("unused"), "without a source"),
    ],
)
def test_a_bad_entry_refuses_the_whole_file(mutate: Any, message: str) -> None:
    data = raw()
    mutate(data)
    with pytest.raises(QuizSourceError, match=message):
        parse_sources(data)


def test_a_day_sample_is_deterministic_and_spread_over_topics() -> None:
    sources, count = load_sources(), get_quiz_policy().sources_per_prompt
    sample = sample_for_day(sources, DAY, count)
    assert sample == sample_for_day(sources, DAY, count)  # a retry and a re-run see the same pages
    assert len(sample) == count
    for offset in range(366):
        day_sample = sample_for_day(sources, DAY + timedelta(days=offset), count)
        assert len({s.id for s in day_sample}) == count
        assert len({s.topic for s in day_sample}) == count  # one page per topic (there are more topics than pages)


def test_days_rotate_and_every_page_comes_up() -> None:
    sources, count = load_sources(), get_quiz_policy().sources_per_prompt
    seen: set[str] = set()
    for offset in range(len(sources.sources)):
        today = sample_for_day(sources, DAY + timedelta(days=offset), count)
        tomorrow = sample_for_day(sources, DAY + timedelta(days=offset + 1), count)
        assert {s.id for s in today} != {s.id for s in tomorrow}
        seen |= {s.id for s in today}
    assert seen == {s.id for s in sources.sources}


def test_a_short_list_is_sent_whole() -> None:
    sources = load_sources()
    short = SourceList(sources.topics[:2], tuple(s for s in sources.sources if s.topic in sources.topics[:2]))
    assert sample_for_day(short, DAY, 100) == short.sources
