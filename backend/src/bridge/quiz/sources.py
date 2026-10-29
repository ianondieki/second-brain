"""The curated source list of Today's five and each day's sample of it (REQ-DEV-01; D-59).

``backend/ai/quiz_sources.yaml`` lists official documentation pages (project, standards-body or regulator docs; never
a news site or a vendor blog), each with a short stable ``id``, a ``topic``, its ``host``, ``url`` and ``title``.
``load_sources`` refuses the whole file on the first bad entry, so a mistake never reaches a model or a question:

- ``version`` 1, a non-empty ``topics`` list of distinct slugs, and at least one source;
- an id is 2 to 40 characters from a-z, 0-9 and dashes, starting with a letter (it fits ``quiz_questions.source_id``),
  and unique;
- the URL is https on an ASCII host with no user info, port or whitespace (the research agent's rule,
  ``bridge.problems.research.sources.url_host``), at most 400 characters, and unique; ``host`` is its host exactly;
- the topic is one of ``topics``, and every topic has a source;
- the title is non-empty after whitespace collapsing, at most 160 characters, free of control characters and written
  in Latin letters and ASCII digits (``bridge.problems.research.text``), so a copied title passes the question rules.

``sample_for_day`` picks the pages one call sees (``policy.yaml`` ``quiz.sources_per_prompt``). Picture an endless
sequence that takes the topics in turn (file order) and, at each topic's k-th turn, its k-th page (by id, cycling):
day ``d`` takes ``count`` pages from position ``d.toordinal() * count`` of it, skipping a page already taken. So a
day's pages come from ``count`` different topics while there are at least that many topics, consecutive days start
where the previous day stopped, and every page comes up in turn. The result depends on the date and the file only (no
clock, no randomness), so a retried call and a re-run see the same sample.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.config import BACKEND_DIR
from bridge.problems.research.sources import url_host
from bridge.problems.research.text import collapse, has_control, non_latin

SOURCES_FILE: Final = BACKEND_DIR / "ai" / "quiz_sources.yaml"
SOURCE_ID: Final = re.compile(r"[a-z][a-z0-9-]{1,39}")
TOPIC: Final = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
MAX_URL_CHARS: Final = 400  # quiz_questions.source_url
MAX_TITLE_CHARS: Final = 160  # quiz_questions.source_title
MAX_TOPIC_CHARS: Final = 60  # quiz_questions.topic
_KEYS: Final = frozenset({"id", "topic", "host", "url", "title"})


class QuizSourceError(ValueError):
    """The source list breaks a rule; nothing is loaded."""


@dataclass(frozen=True, slots=True)
class QuizSource:
    """One curated page. Only objects made by ``load_sources`` are sent to a model as public fields."""

    id: str
    topic: str
    host: str
    url: str
    title: str


@dataclass(frozen=True, slots=True)
class SourceList:
    topics: tuple[str, ...]
    sources: tuple[QuizSource, ...]

    def by_id(self) -> dict[str, QuizSource]:
        return {s.id: s for s in self.sources}

    def groups(self) -> tuple[tuple[QuizSource, ...], ...]:
        """Each topic's pages by id, topics in file order (every topic has one: ``parse_sources``)."""
        return tuple(tuple(sorted((s for s in self.sources if s.topic == t), key=lambda s: s.id)) for t in self.topics)


def _text(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not collapse(value):
        raise QuizSourceError(f"{where}: {key} must be non-empty text")
    return value


def _source(raw: Any, index: int, topics: tuple[str, ...]) -> QuizSource:
    where = f"quiz_sources.yaml source {index}"
    if not isinstance(raw, Mapping) or set(raw) != _KEYS:
        raise QuizSourceError(f"{where}: must have exactly {sorted(_KEYS)}")
    source_id = _text(raw, "id", where)
    where = f"quiz_sources.yaml source {source_id!r}"
    if not SOURCE_ID.fullmatch(source_id):
        raise QuizSourceError(f"{where}: an id is 2-40 characters from a-z 0-9 - and starts with a letter")
    topic = _text(raw, "topic", where)
    if topic not in topics:
        raise QuizSourceError(f"{where}: unknown topic {topic!r}")
    url = _text(raw, "url", where)
    host = url_host(url)
    if host is None or len(url) > MAX_URL_CHARS:
        raise QuizSourceError(f"{where}: the url must be https on a plain host, at most {MAX_URL_CHARS} characters")
    if _text(raw, "host", where) != host:
        raise QuizSourceError(f"{where}: host must be the url's host ({host})")
    title = _text(raw, "title", where)
    if title != collapse(title) or len(title) > MAX_TITLE_CHARS or has_control(title) or non_latin(title):
        raise QuizSourceError(
            f"{where}: a title is collapsed Latin text of at most {MAX_TITLE_CHARS} characters, no control characters"
        )
    return QuizSource(source_id, topic, host, url, title)


def parse_sources(data: Any) -> SourceList:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise QuizSourceError("quiz_sources.yaml: version 1 expected")
    raw_topics = data.get("topics")
    if (
        not isinstance(raw_topics, list)
        or not raw_topics
        or not all(isinstance(t, str) and TOPIC.fullmatch(t) and len(t) <= MAX_TOPIC_CHARS for t in raw_topics)
        or len(set(raw_topics)) != len(raw_topics)
    ):
        raise QuizSourceError("quiz_sources.yaml: topics must be a non-empty list of distinct slugs")
    topics = tuple(raw_topics)
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise QuizSourceError("quiz_sources.yaml: sources must be a non-empty list")
    sources = tuple(_source(raw, index, topics) for index, raw in enumerate(raw_sources, start=1))
    for key in ("id", "url"):
        values = [getattr(s, key) for s in sources]
        duplicates = sorted({v for v in values if values.count(v) > 1})
        if duplicates:
            raise QuizSourceError(f"quiz_sources.yaml: duplicate {key}s {duplicates}")
    empty = [t for t in topics if not any(s.topic == t for s in sources)]
    if empty:
        raise QuizSourceError(f"quiz_sources.yaml: topics without a source {empty}")
    return SourceList(topics, sources)


def load_sources(path: Path = SOURCES_FILE) -> SourceList:
    return parse_sources(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_sources() -> SourceList:
    """The process-wide source list (read once; a bad file stops the first job that needs it)."""
    return load_sources()


def sample_for_day(sources: SourceList, day: date, count: int) -> tuple[QuizSource, ...]:
    """The ``count`` pages one call for ``day`` sees (see the module docstring); every page when the list is shorter."""
    if count >= len(sources.sources):
        return sources.sources
    groups = sources.groups()
    picked: dict[str, QuizSource] = {}
    position = day.toordinal() * count
    while len(picked) < count:  # ends: each topic cycles through all its pages, and count < the number of pages
        group = groups[position % len(groups)]
        page = group[(position // len(groups)) % len(group)]
        picked.setdefault(page.id, page)
        position += 1
    return tuple(picked.values())
