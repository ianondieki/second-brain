"""The saved public excerpts and the source allowlists (REQ-RES-01, REQ-RES-02; docs/spec/06 6.5; D-38).

The research agent has no search and no fetch at runtime (PLAN §8 P11): it drafts from the short excerpts saved in
``backend/seed/research_excerpts.yaml``, each fetched once at build time with its URL, publisher and the date the page
states (``docs/platform/research/research-excerpts-2026-09.md``). ``load_catalogue`` reads them against the country's
allowlist (``bridge/problems/sources/<country>.yaml``) and refuses the whole file on the first bad excerpt, so a
mistake never reaches a model or a card:

- the URL is https on an ASCII host with no user info, port or whitespace (the ``app_create_research_candidate``
  rule), and the host is on the allowlist (the domain itself or a subdomain of it);
- the publisher is the allowlisted domain's, and the source type is ``official`` exactly when the domain is an
  official one (a government ``.go.ke`` host or a regulator): an excerpt never makes itself official;
- the dates are real ISO dates, retrieved on or after publication; the quote is whitespace-collapsed, non-empty,
  free of control characters and at most ``max_quote_words`` words; ids are unique and fit ``excerpt_ref``.

Only ``Excerpt`` objects made here are sent to a model as public platform data (``InputField(public=True)``, see
``bridge.problems.research.synthesis``). Freshness (docs/spec/06 6.5: stale at 12 months, auto-archive at 18, from
``policy.yaml``) is judged per run on the shared clock's date: an archived excerpt is never sent and never counts
(the saved fixtures ke-tel-005 and ke-agr-004 are archived on 2026-09-29).

A second pair (REQ-DEV-02; D-60; P22 card B, "Trends") is loaded the same way with ``kind=CatalogueKind.TRENDS``: the
technology publishers' allowlist ``sources/tech.yaml`` (``country: TECH``; every domain is the vendor's or the project's
own site, so every domain is ``official: true`` and nothing else is) and ``backend/seed/trend_excerpts.yaml`` (the same
shape with ``topic_slug`` in place of ``niche``, plus the researcher's ``publisher_kind``: project, vendor, standards or
regulator; ``Excerpt.niche`` then holds the topic slug, also readable as ``Excerpt.topic_slug``). Its bounds are
revision 0010's ``trend_card_sources`` columns (URL 400, publisher 160, quote 600 characters, a topic slug of 40). Each
kind reads only its own allowlists: a research excerpt naming ``TECH`` and a trend excerpt naming a country are refused.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import yaml

from bridge.config import BACKEND_DIR
from bridge.problems.research.policy import SOURCE_TYPES, ResearchPolicy, get_research_policy
from bridge.problems.research.text import collapse, has_control, word_count

EXCERPTS_FILE: Final = BACKEND_DIR / "seed" / "research_excerpts.yaml"
TREND_EXCERPTS_FILE: Final = BACKEND_DIR / "seed" / "trend_excerpts.yaml"
TECH: Final = "TECH"  # the technology publishers' allowlist (sources/tech.yaml), not a country
SOURCES_DIR: Final = Path(__file__).resolve().parents[1] / "sources"
EXCERPT_ID: Final = re.compile(r"[a-z][a-z0-9-]{0,23}")  # fits excerpt_ref (32) with the "example:" prefix
NICHE_SLUG: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
COUNTRY: Final = re.compile(r"[A-Z]{2}")
HOST: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_EXCERPT_KEYS: Final = frozenset(
    {"id", "niche", "country", "url", "publisher", "source_type", "published_date", "retrieved_at", "quote", "topic"}
)
MAX_URL_CHARS: Final = 1000
MAX_QUOTE_CHARS: Final = 2000
MAX_PUBLISHER_CHARS: Final = 200


class CatalogueKind(StrEnum):
    RESEARCH = "research"  # Kenyan problem excerpts by niche, against country allowlists
    TRENDS = "trends"  # technology trend excerpts by topic, against the TECH allowlist


@dataclass(frozen=True, slots=True)
class _Rules:
    file: Path
    group_key: str
    extra_keys: frozenset[str]
    max_url_chars: int
    max_publisher_chars: int
    max_quote_chars: int
    max_group_chars: int | None  # None: the niche slug's own rule only


_RULES: Final = {
    CatalogueKind.RESEARCH: _Rules(
        EXCERPTS_FILE, "niche", frozenset(), MAX_URL_CHARS, MAX_PUBLISHER_CHARS, MAX_QUOTE_CHARS, None
    ),
    CatalogueKind.TRENDS: _Rules(  # bounds: revision 0010's trend_card_sources and trend_cards.topic_slug
        TREND_EXCERPTS_FILE, "topic_slug", frozenset({"publisher_kind"}), 400, 160, 600, 40
    ),
}
PUBLISHER_KINDS: Final = ("project", "vendor", "standards", "regulator")  # a trend excerpt's publisher_kind


def _kind_admits(kind: CatalogueKind, country: str) -> bool:
    return country == TECH if kind is CatalogueKind.TRENDS else COUNTRY.fullmatch(country) is not None


class SourceError(ValueError):
    """The allowlist or the saved excerpts break a rule; nothing is loaded."""


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"  # older than stale_after_months: counts, with a lower freshness score
    ARCHIVED = "archived"  # older than archive_after_months: never sent, never counts


@dataclass(frozen=True, slots=True)
class Domain:
    domain: str
    publisher: str
    official: bool

    def matches(self, host: str) -> bool:
        return host == self.domain or host.endswith(f".{self.domain}")


@dataclass(frozen=True, slots=True)
class Alias:
    """One spelling of an organisation. ``case_sensitive``: matched only as written or in capitals (a common word
    such as "Treasury", which lower case must not trigger); otherwise in any case."""

    text: str
    case_sensitive: bool = False


@dataclass(frozen=True, slots=True)
class Organisation:
    name: str
    aliases: tuple[Alias, ...]


@dataclass(frozen=True, slots=True)
class Allowlist:
    country: str
    domains: tuple[Domain, ...]
    organisations: tuple[Organisation, ...]

    def domain_of(self, url: str) -> Domain | None:
        """The allowlisted domain of an https URL's host, or None (a malformed URL is never allowed)."""
        host = url_host(url)
        return None if host is None else next((d for d in self.domains if d.matches(host)), None)

    def named(self) -> tuple[Organisation, ...]:
        """The organisations a card may name: the listed ones and every publisher."""
        publishers = sorted({d.publisher for d in self.domains})
        return (*self.organisations, *(Organisation(p, (Alias(p),)) for p in publishers))


@dataclass(frozen=True, slots=True)
class Excerpt:
    """One saved excerpt. ``official`` comes from the allowlisted domain, never from the file alone."""

    id: str
    niche: str
    country: str
    url: str
    host: str
    publisher: str
    source_type: str
    official: bool
    published_date: date
    retrieved_at: date
    quote: str
    topic: str
    publisher_kind: str | None = None  # trends only: one of PUBLISHER_KINDS (the researcher's record of who published)

    @property
    def topic_slug(self) -> str:
        """A trend excerpt's topic slug (stored in ``niche``, see the module docstring)."""
        return self.niche


def url_host(url: str) -> str | None:
    """The lower-case host of an https URL that ``app_create_research_candidate`` accepts, else None: no user info,
    no port, no whitespace or control character, at most 1000 characters."""
    if len(url) > MAX_URL_CHARS or has_control(url) or any(c.isspace() for c in url) or not url.isascii():
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or "@" in parts.netloc or ":" in parts.netloc:
        return None
    host = parts.netloc.lower()
    return host if HOST.fullmatch(host) else None


def _text(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not collapse(value):
        raise SourceError(f"{where}: {key} must be non-empty text")
    return value


def _date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise SourceError(f"{where} must be an ISO date (YYYY-MM-DD)")


# ------------------------------------------------------------------------------------------------------ allowlist


def parse_allowlist(data: Any, *, where: str = "allowlist") -> Allowlist:
    if (
        not isinstance(data, Mapping)
        or data.get("version") != 1
        or set(data)
        != {
            "version",
            "country",
            "domains",
            "organisations",
        }
    ):
        raise SourceError(f"{where}: version 1 with exactly country, domains and organisations")
    country = data["country"]
    if not isinstance(country, str) or not (country == TECH or COUNTRY.fullmatch(country)):
        raise SourceError(f"{where}: country must be an ISO 3166-1 alpha-2 code (or {TECH})")
    raw_domains = data["domains"]
    if not isinstance(raw_domains, list) or not raw_domains:
        raise SourceError(f"{where}: domains must be a non-empty list")
    domains: list[Domain] = []
    for raw in raw_domains:
        if not isinstance(raw, Mapping) or set(raw) != {"domain", "publisher", "official"}:
            raise SourceError(f"{where}: each domain has exactly domain, publisher and official")
        name, publisher, official = raw["domain"], raw["publisher"], raw["official"]
        if not isinstance(name, str) or not HOST.fullmatch(name):
            raise SourceError(f"{where}: {name!r} is not a lower-case host name")
        if not isinstance(publisher, str) or not collapse(publisher) or has_control(publisher):
            raise SourceError(f"{where}: {name} needs a publisher")
        if not isinstance(official, bool):
            raise SourceError(f"{where}: {name}.official must be true or false")
        if country == TECH and not official:
            raise SourceError(f"{where}: {name} must be official: every {TECH} domain is a publisher's own site")
        if official and country != TECH and not name.endswith(f".go.{country.lower()}"):
            raise SourceError(f"{where}: {name} is official, but only a government host (.go.{country.lower()}) is")
        domains.append(Domain(name, collapse(publisher), official))
    if len({d.domain for d in domains}) != len(domains):
        raise SourceError(f"{where}: a domain is listed twice")
    raw_orgs = data["organisations"]
    if not isinstance(raw_orgs, list):
        raise SourceError(f"{where}: organisations must be a list")
    organisations: list[Organisation] = []
    for raw in raw_orgs:
        if not isinstance(raw, Mapping) or set(raw) != {"name", "aliases"}:
            raise SourceError(f"{where}: each organisation has exactly name and aliases")
        name, aliases = raw["name"], raw["aliases"]
        if not isinstance(name, str) or not collapse(name) or not isinstance(aliases, list) or not aliases:
            raise SourceError(f"{where}: an organisation needs a name and at least one alias")
        organisations.append(Organisation(collapse(name), tuple(_alias(a, f"{where}: {name}") for a in aliases)))
    return Allowlist(country, tuple(domains), tuple(organisations))


def _alias(raw: Any, where: str) -> Alias:
    """An alias is text, or ``{text: ..., case_sensitive: true}``."""
    if isinstance(raw, Mapping):
        if set(raw) != {"text", "case_sensitive"} or not isinstance(raw["case_sensitive"], bool):
            raise SourceError(f"{where}: an alias mapping has exactly text and case_sensitive (true or false)")
        text, case_sensitive = raw["text"], raw["case_sensitive"]
    else:
        text, case_sensitive = raw, False
    if not isinstance(text, str) or not text or collapse(text) != text:
        raise SourceError(f"{where}'s aliases must be trimmed, non-empty text")
    return Alias(text, case_sensitive)


def load_allowlist(country: str, directory: Path = SOURCES_DIR) -> Allowlist:
    if not (country == TECH or COUNTRY.fullmatch(country)):
        raise SourceError(f"{country!r} is not a country code")
    path = directory / f"{country.lower()}.yaml"
    if not path.is_file():
        raise SourceError(f"no source allowlist for {country} ({path.name})")
    allowlist = parse_allowlist(yaml.safe_load(path.read_text(encoding="utf-8")), where=path.name)
    if allowlist.country != country:
        raise SourceError(f"{path.name} is the allowlist of {allowlist.country}, not {country}")
    return allowlist


# ------------------------------------------------------------------------------------------------------ excerpts


def _excerpt(
    raw: Any, allowlists: Mapping[str, Allowlist], policy: ResearchPolicy, index: int, kind: CatalogueKind
) -> Excerpt:
    rules = _RULES[kind]
    keys = _EXCERPT_KEYS - {"niche"} | {rules.group_key} | rules.extra_keys
    if not isinstance(raw, Mapping) or set(raw) != keys:
        raise SourceError(f"excerpt {index}: exactly {sorted(keys)}")
    excerpt_id = raw["id"]
    if not isinstance(excerpt_id, str) or not EXCERPT_ID.fullmatch(excerpt_id):
        raise SourceError(f"excerpt {index}: id must be 1-24 characters from a-z 0-9 - starting with a letter")
    where = f"excerpt {excerpt_id}"
    niche, country = _text(raw, rules.group_key, where), _text(raw, "country", where)
    limit = rules.max_group_chars
    if not NICHE_SLUG.fullmatch(niche) or (limit is not None and len(niche) > limit):
        noun = rules.group_key.removesuffix("_slug")
        bound = f" of at most {limit} characters" if limit is not None else ""
        raise SourceError(f"{where}: {rules.group_key} must be a {noun} slug{bound}")
    if not _kind_admits(kind, country):
        raise SourceError(f"{where}: a {kind.value} excerpt cannot name the {country} allowlist")
    allowlist = allowlists.get(country)
    if allowlist is None:
        raise SourceError(f"{where}: no source allowlist for {country}")
    url = _text(raw, "url", where)
    host = url_host(url)
    if host is None or len(url) > rules.max_url_chars:
        raise SourceError(f"{where}: the URL must be https on a plain ASCII host (no user info, port or spaces)")
    domain = allowlist.domain_of(url)
    if domain is None:
        raise SourceError(f"{where}: {host} is not on the {country} source allowlist")
    publisher = collapse(_text(raw, "publisher", where))
    if len(publisher) > rules.max_publisher_chars:
        raise SourceError(f"{where}: the publisher is longer than {rules.max_publisher_chars} characters")
    if publisher != domain.publisher:
        raise SourceError(f"{where}: the publisher of {domain.domain} is {domain.publisher!r}, not {publisher!r}")
    source_type = raw["source_type"]
    if source_type not in SOURCE_TYPES:
        raise SourceError(f"{where}: source_type must be one of {list(SOURCE_TYPES)}")
    if (source_type == "official") != domain.official:
        raise SourceError(f"{where}: only an official allowlisted domain is an official source ({domain.domain})")
    published = _date(raw["published_date"], f"{where}: published_date")
    retrieved = _date(raw["retrieved_at"], f"{where}: retrieved_at")
    if retrieved < published:
        raise SourceError(f"{where}: retrieved before it was published")
    quote = collapse(_text(raw, "quote", where))
    if has_control(quote) or len(quote) > rules.max_quote_chars or word_count(quote) > policy.max_quote_words:
        raise SourceError(f"{where}: the quote must be at most {policy.max_quote_words} words, without control codes")
    publisher_kind = raw.get("publisher_kind")
    if "publisher_kind" in rules.extra_keys and publisher_kind not in PUBLISHER_KINDS:
        raise SourceError(f"{where}: publisher_kind must be one of {list(PUBLISHER_KINDS)}")
    return Excerpt(
        id=excerpt_id,
        niche=niche,
        country=country,
        url=url,
        host=host,
        publisher=publisher,
        source_type=source_type,
        official=domain.official,
        published_date=published,
        retrieved_at=retrieved,
        quote=quote,
        topic=collapse(_text(raw, "topic", where)),
        publisher_kind=publisher_kind,
    )


def parse_excerpts(
    data: Any,
    allowlists: Mapping[str, Allowlist],
    policy: ResearchPolicy,
    *,
    kind: CatalogueKind = CatalogueKind.RESEARCH,
) -> tuple[Excerpt, ...]:
    if not isinstance(data, Mapping) or set(data) != {"excerpts"} or not isinstance(data["excerpts"], list):
        raise SourceError("the excerpts file holds one list, excerpts")
    excerpts = tuple(_excerpt(raw, allowlists, policy, i, kind) for i, raw in enumerate(data["excerpts"]))
    ids = [e.id for e in excerpts]
    if len(set(ids)) != len(ids):
        raise SourceError("an excerpt id is used twice")
    return excerpts


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def freshness(excerpt: Excerpt, as_of: date, policy: ResearchPolicy) -> Freshness:
    if as_of >= add_months(excerpt.published_date, policy.archive_after_months):
        return Freshness.ARCHIVED
    if as_of >= add_months(excerpt.published_date, policy.stale_after_months):
        return Freshness.STALE
    return Freshness.FRESH


def freshness_score(excerpt: Excerpt, as_of: date, policy: ResearchPolicy) -> Decimal:
    """1 until the stale date, 0 from the archive date, falling linearly (by day) in between."""
    stale = add_months(excerpt.published_date, policy.stale_after_months)
    archive = add_months(excerpt.published_date, policy.archive_after_months)
    if as_of < stale:
        return Decimal(1)
    if as_of >= archive:
        return Decimal(0)
    return Decimal((archive - as_of).days) / Decimal((archive - stale).days)


@dataclass(frozen=True)
class Catalogue:
    excerpts: tuple[Excerpt, ...]
    allowlists: Mapping[str, Allowlist]

    def get(self, excerpt_id: str) -> Excerpt | None:
        return next((e for e in self.excerpts if e.id == excerpt_id), None)

    def of(self, niche: str, country: str) -> tuple[Excerpt, ...]:
        return tuple(e for e in self.excerpts if e.niche == niche and e.country == country)

    def usable(self, niche: str, country: str, as_of: date, policy: ResearchPolicy) -> tuple[Excerpt, ...]:
        """What a run sends: the niche's excerpts that are not archived, newest first, at most ``max_excerpts``."""
        live = [e for e in self.of(niche, country) if freshness(e, as_of, policy) is not Freshness.ARCHIVED]
        live.sort(key=lambda e: (e.published_date, e.id), reverse=True)
        return tuple(live[: policy.max_excerpts])

    def niches(self, country: str) -> tuple[str, ...]:
        return tuple(sorted({e.niche for e in self.excerpts if e.country == country}))


def load_catalogue(
    path: Path | None = None,
    *,
    sources_dir: Path = SOURCES_DIR,
    policy: ResearchPolicy | None = None,
    countries: Iterable[str] | None = None,
    kind: CatalogueKind = CatalogueKind.RESEARCH,
) -> Catalogue:
    """The saved excerpts of ``kind`` (its file unless ``path`` is given) checked against every allowlist they name
    (or ``countries``) that the kind may read."""
    policy = policy or get_research_policy()
    data = yaml.safe_load((path or _RULES[kind].file).read_text(encoding="utf-8"))
    if countries is None:
        raw = data.get("excerpts") if isinstance(data, Mapping) else None
        items = raw if isinstance(raw, list) else []
        countries = {str(item.get("country")) for item in items if isinstance(item, Mapping)}
    allowlists = {c: load_allowlist(c, sources_dir) for c in sorted(countries) if _kind_admits(kind, c)}
    return Catalogue(parse_excerpts(data, allowlists, policy, kind=kind), allowlists)


@lru_cache(maxsize=2)
def get_catalogue(kind: CatalogueKind = CatalogueKind.RESEARCH) -> Catalogue:
    """The process-wide catalogue of ``kind`` (read once; a bad file stops the first request, never silently)."""
    return load_catalogue(kind=kind)
