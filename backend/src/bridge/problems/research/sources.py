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
class Organisation:
    name: str
    aliases: tuple[str, ...]


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
        return (*self.organisations, *(Organisation(p, (p,)) for p in publishers))


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
    if not isinstance(country, str) or not COUNTRY.fullmatch(country):
        raise SourceError(f"{where}: country must be an ISO 3166-1 alpha-2 code")
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
        if official and not name.endswith(f".go.{country.lower()}"):
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
        if not all(isinstance(a, str) and collapse(a) == a and a for a in aliases):
            raise SourceError(f"{where}: {name}'s aliases must be trimmed, non-empty text")
        organisations.append(Organisation(collapse(name), tuple(aliases)))
    return Allowlist(country, tuple(domains), tuple(organisations))


def load_allowlist(country: str, directory: Path = SOURCES_DIR) -> Allowlist:
    if not COUNTRY.fullmatch(country):
        raise SourceError(f"{country!r} is not a country code")
    path = directory / f"{country.lower()}.yaml"
    if not path.is_file():
        raise SourceError(f"no source allowlist for {country} ({path.name})")
    allowlist = parse_allowlist(yaml.safe_load(path.read_text(encoding="utf-8")), where=path.name)
    if allowlist.country != country:
        raise SourceError(f"{path.name} is the allowlist of {allowlist.country}, not {country}")
    return allowlist


# ------------------------------------------------------------------------------------------------------ excerpts


def _excerpt(raw: Any, allowlists: Mapping[str, Allowlist], policy: ResearchPolicy, index: int) -> Excerpt:
    if not isinstance(raw, Mapping) or set(raw) != _EXCERPT_KEYS:
        raise SourceError(f"excerpt {index}: exactly {sorted(_EXCERPT_KEYS)}")
    excerpt_id = raw["id"]
    if not isinstance(excerpt_id, str) or not EXCERPT_ID.fullmatch(excerpt_id):
        raise SourceError(f"excerpt {index}: id must be 1-24 characters from a-z 0-9 - starting with a letter")
    where = f"excerpt {excerpt_id}"
    niche, country = _text(raw, "niche", where), _text(raw, "country", where)
    if not NICHE_SLUG.fullmatch(niche):
        raise SourceError(f"{where}: niche must be a niche slug")
    allowlist = allowlists.get(country)
    if allowlist is None:
        raise SourceError(f"{where}: no source allowlist for {country}")
    url = _text(raw, "url", where)
    host = url_host(url)
    if host is None:
        raise SourceError(f"{where}: the URL must be https on a plain ASCII host (no user info, port or spaces)")
    domain = allowlist.domain_of(url)
    if domain is None:
        raise SourceError(f"{where}: {host} is not on the {country} source allowlist")
    publisher = collapse(_text(raw, "publisher", where))
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
    if has_control(quote) or len(quote) > MAX_QUOTE_CHARS or word_count(quote) > policy.max_quote_words:
        raise SourceError(f"{where}: the quote must be at most {policy.max_quote_words} words, without control codes")
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
    )


def parse_excerpts(data: Any, allowlists: Mapping[str, Allowlist], policy: ResearchPolicy) -> tuple[Excerpt, ...]:
    if not isinstance(data, Mapping) or set(data) != {"excerpts"} or not isinstance(data["excerpts"], list):
        raise SourceError("the excerpts file holds one list, excerpts")
    excerpts = tuple(_excerpt(raw, allowlists, policy, i) for i, raw in enumerate(data["excerpts"]))
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
    path: Path = EXCERPTS_FILE,
    *,
    sources_dir: Path = SOURCES_DIR,
    policy: ResearchPolicy | None = None,
    countries: Iterable[str] | None = None,
) -> Catalogue:
    """The saved excerpts checked against every allowlist they name (or ``countries``)."""
    policy = policy or get_research_policy()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if countries is None:
        raw = data.get("excerpts") if isinstance(data, Mapping) else None
        items = raw if isinstance(raw, list) else []
        countries = {str(item.get("country")) for item in items if isinstance(item, Mapping)}
    allowlists = {c: load_allowlist(c, sources_dir) for c in sorted(countries) if COUNTRY.fullmatch(c)}
    return Catalogue(parse_excerpts(data, allowlists, policy), allowlists)


@lru_cache(maxsize=1)
def get_catalogue() -> Catalogue:
    """The process-wide catalogue (read once; a bad file stops the first research request, never silently)."""
    return load_catalogue()
