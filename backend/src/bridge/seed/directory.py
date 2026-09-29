"""Provisional directory seed: ``backend/seed/ke_provisional.yaml`` into ``organizations`` and ``org_niches``
(REQ-DIR-02, D-21; docs/spec/06 6.2).

Public organisational data only: legal name, org type, niches, county, ``official_domains[]``, public-entity flag and
the source register, URL and retrieval date of every row. No contacts and no logos: the loader accepts only the
documented fields, so a ``logo`` or ``email`` field fails the whole file before anything is written.

Two rules are enforced here, in code:

- The seed loads only when ``APP_ENV`` is set explicitly (environment or ``backend/.env``, not the settings default)
  to ``dev`` or ``test`` (``ensure_loadable``); staging keeps its fixture organisations and gate G6 approves the
  production list.
- Every row is E0 (``unclaimed``). A row may name a higher ``verification`` (fixture organisations) only when
  ``APP_ENV`` is ``test`` or ``staging``; anywhere else the loader refuses.

Counties are stored as ISO 3166-2:KE codes (``organizations.county_code`` references ``regions.code``, e.g. ``KE-30``
for Nairobi City), which is what the YAML uses; the First-Schedule number (``regions.county_code``, ``047``) is a
different scheme and is refused.

Idempotent upsert keyed by ``slug``: running it twice leaves the same rows. A row (and its niches) is refreshed only
while it is still a seed organisation at E0 that is not delisted, so a claimed (E1/E2), self-signed-up or delisted
organisation keeps what it has (delisting and opt-outs are never undone). Rows removed from the file stay in the
database (tags may point at them).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import yaml
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge import clock
from bridge.config import BACKEND_DIR, Settings
from bridge.directory.models import Niche, OrgNiche, Region
from bridge.ids import uuid7
from bridge.models.enums import OrgKind, OrgSource, OrgVerification, RegionKind
from bridge.tenancy.models import Organization

DIRECTORY_FILE: Final = BACKEND_DIR / "seed" / "ke_provisional.yaml"
LOADABLE_ENVS: Final = frozenset({"dev", "test"})
VERIFIED_ROW_ENVS: Final = frozenset({"test", "staging"})  # where a row may be above unclaimed (fixture orgs)
REQUIRED_FIELDS: Final = frozenset(
    {
        "slug",
        "legal_name",
        "kind",
        "niches",
        "county",
        "official_domains",
        "public_entity",
        "source_register",
        "source_url",
        "source_retrieved_on",
    }
)
OPTIONAL_FIELDS: Final = frozenset({"verification"})
LISTED_LEVELS: Final = frozenset({OrgVerification.UNCLAIMED, OrgVerification.E1, OrgVerification.E2})
# Claims from these never pass E1 (docs/spec/06 6.2), so they are never an organisation's official domain.
FREE_MAIL_DOMAINS: Final = frozenset(
    {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "proton.me"}
)
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HOSTNAME = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_MAX_URL = 500  # organizations.source_url
_MAX_NAME = 200  # organizations.legal_name
_MAX_SLUG = 80


class DirectorySeedRefused(RuntimeError):
    """The environment does not allow this seed (or this row's verification level)."""


class DirectorySeedInvalid(ValueError):
    """The seed file breaks the policy or the schema; nothing was written."""


@dataclass(frozen=True, slots=True)
class SeedOrg:
    slug: str
    legal_name: str
    kind: OrgKind
    niches: tuple[str, ...]
    county: str | None  # ISO 3166-2:KE (regions.code)
    official_domains: tuple[str, ...]
    public_entity: bool
    source_register: str
    source_url: str
    source_retrieved_on: date
    verification: OrgVerification


def load_directory(path: Path = DIRECTORY_FILE) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def directory_refusal(settings: Settings) -> str | None:
    """Why the provisional directory does not load under ``settings``, or None when it does.

    ``APP_ENV`` must have been provided (environment or ``backend/.env``): the settings default is ``dev``, so a
    deployment that forgot to set it would otherwise load the directory."""
    if "app_env" not in settings.model_fields_set:
        return (
            "APP_ENV is not set; the provisional directory seed loads only when APP_ENV is set explicitly to dev or "
            "test (environment or backend/.env), never on the settings default"
        )
    if settings.app_env not in LOADABLE_ENVS:
        return (
            f"APP_ENV={settings.app_env}; the provisional directory seed loads only in dev or test (staging keeps its "
            "fixture organisations and gate G6 approves the production list)"
        )
    return None


def directory_loadable(settings: Settings) -> bool:
    return directory_refusal(settings) is None


def ensure_loadable(settings: Settings) -> None:
    reason = directory_refusal(settings)
    if reason is not None:
        raise DirectorySeedRefused(reason)


def _https_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > _MAX_URL:
        return False
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname)


def _check_row(
    index: int,
    row: Any,
    *,
    niche_slugs: Collection[str],
    county_codes: Collection[str],
    today: date,
) -> list[str]:
    where = f"orgs[{index}]"
    if not isinstance(row, Mapping):
        return [f"{where}: not a mapping"]
    where = f"orgs[{index}] ({row.get('slug')!r})"
    problems = [f"{where}: unknown field {key!r}" for key in sorted(set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS)]
    problems += [f"{where}: missing field {key!r}" for key in sorted(REQUIRED_FIELDS - set(row))]
    if problems:
        return problems
    slug, name = row["slug"], row["legal_name"]
    if not isinstance(slug, str) or len(slug) > _MAX_SLUG or not _SLUG.fullmatch(slug):
        problems.append(f"{where}: slug must be lowercase words joined by hyphens")
    if not isinstance(name, str) or not name.strip() or len(name) > _MAX_NAME or name != name.strip():
        problems.append(f"{where}: legal_name must be 1-{_MAX_NAME} characters without surrounding spaces")
    if row["kind"] not in {k.value for k in OrgKind}:
        problems.append(f"{where}: unknown kind {row['kind']!r}")
    niches = row["niches"]
    if not isinstance(niches, list) or not niches:
        problems.append(f"{where}: needs at least one niche")
    else:
        problems += [f"{where}: unknown niche {n!r}" for n in niches if n not in niche_slugs]
        if len(set(map(str, niches))) != len(niches):
            problems.append(f"{where}: a niche is listed twice")
    if row["county"] is not None and row["county"] not in county_codes:
        problems.append(f"{where}: unknown county {row['county']!r} (use the ISO 3166-2:KE code, e.g. KE-30)")
    domains = row["official_domains"]
    if not isinstance(domains, list):
        problems.append(f"{where}: official_domains must be a list")
    else:
        for domain in domains:
            if not isinstance(domain, str) or not _HOSTNAME.fullmatch(domain):
                problems.append(f"{where}: official domain {domain!r} is not a lowercase hostname")
            elif domain in FREE_MAIL_DOMAINS:
                problems.append(f"{where}: official domain {domain!r} is a free-mail domain")
    if not isinstance(row["public_entity"], bool):
        problems.append(f"{where}: public_entity must be true or false")
    if not isinstance(row["source_register"], str) or not row["source_register"].strip():
        problems.append(f"{where}: source_register must name the public register")
    if not _https_url(row["source_url"]):
        problems.append(f"{where}: source_url must be an https URL with a host (at most {_MAX_URL} characters)")
    retrieved = row["source_retrieved_on"]
    if not isinstance(retrieved, date):
        problems.append(f"{where}: source_retrieved_on must be a date (YYYY-MM-DD, unquoted)")
    elif retrieved > today:
        problems.append(f"{where}: source_retrieved_on {retrieved.isoformat()} is in the future")
    level = row.get("verification", OrgVerification.UNCLAIMED.value)
    if level not in {v.value for v in LISTED_LEVELS}:
        problems.append(f"{where}: verification must be unclaimed, e1 or e2")
    return problems


def parse_rows(
    data: Any,
    *,
    niche_slugs: Collection[str],
    county_codes: Collection[str],
    app_env: str,
    today: date,
) -> list[SeedOrg]:
    """Validate the whole file and return its rows; raise before anything is written.

    ``DirectorySeedInvalid`` lists every schema problem; ``DirectorySeedRefused`` names a row above ``unclaimed``
    outside test/staging."""
    if not isinstance(data, Mapping) or not isinstance(data.get("orgs"), list):
        raise DirectorySeedInvalid("the directory seed needs a top-level 'orgs' list")
    rows: list[Any] = data["orgs"]
    problems: list[str] = []
    for index, row in enumerate(rows):
        problems += _check_row(index, row, niche_slugs=niche_slugs, county_codes=county_codes, today=today)
    slugs: set[str] = set()
    owners: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        slug = str(row.get("slug"))
        if slug in slugs:
            problems.append(f"duplicate slug {slug!r}")
        slugs.add(slug)
        for domain in row.get("official_domains") or []:
            if str(domain) in owners and owners[str(domain)] != slug:
                problems.append(f"official domain {domain!r} is listed twice ({owners[str(domain)]}, {slug})")
            owners.setdefault(str(domain), slug)
    if problems:
        raise DirectorySeedInvalid("; ".join(problems))
    parsed = [
        SeedOrg(
            slug=row["slug"],
            legal_name=row["legal_name"],
            kind=OrgKind(row["kind"]),
            niches=tuple(row["niches"]),
            county=row["county"],
            official_domains=tuple(row["official_domains"]),
            public_entity=row["public_entity"],
            source_register=row["source_register"],
            source_url=row["source_url"],
            source_retrieved_on=row["source_retrieved_on"],
            verification=OrgVerification(row.get("verification", OrgVerification.UNCLAIMED.value)),
        )
        for row in rows
    ]
    if app_env not in VERIFIED_ROW_ENVS:
        for org in parsed:
            if org.verification != OrgVerification.UNCLAIMED:
                raise DirectorySeedRefused(
                    f"{org.slug}: verification {org.verification.value!r} is above unclaimed; seeded organisations "
                    f"may be verified only with APP_ENV test or staging (APP_ENV={app_env})"
                )
    return parsed


async def directory_counts(conn: AsyncConnection) -> dict[str, int]:
    seeded = select(Organization.id).where(Organization.source == OrgSource.SEED)
    orgs = (await conn.execute(select(func.count()).select_from(seeded.subquery()))).scalar_one()
    niches = (
        await conn.execute(select(func.count()).select_from(OrgNiche).where(OrgNiche.org_id.in_(seeded)))
    ).scalar_one()
    return {"organizations": int(orgs), "org_niches": int(niches)}


async def _upsert(conn: AsyncConnection, org: SeedOrg) -> Any:
    """Insert the organisation, or refresh it while it is still a listed seed organisation at E0 (not delisted); its
    id, or None when it was left as it is."""
    stmt = insert(Organization).values(
        id=uuid7(),
        kind=org.kind,
        legal_name=org.legal_name,
        slug=org.slug,
        country="KE",
        verification=org.verification,
        public_entity=org.public_entity,
        source=OrgSource.SEED,
        official_domains=list(org.official_domains),
        source_url=org.source_url,
        source_retrieved_on=org.source_retrieved_on,
        county_code=org.county,
        e2_verified_at=func.now() if org.verification == OrgVerification.E2 else None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Organization.slug],
        set_={
            "kind": stmt.excluded.kind,
            "legal_name": stmt.excluded.legal_name,
            "public_entity": stmt.excluded.public_entity,
            "official_domains": stmt.excluded.official_domains,
            "source_url": stmt.excluded.source_url,
            "source_retrieved_on": stmt.excluded.source_retrieved_on,
            "county_code": stmt.excluded.county_code,
            "updated_at": func.now(),
        },
        where=(Organization.source == OrgSource.SEED)
        & (Organization.verification == OrgVerification.UNCLAIMED)
        & Organization.delisted_at.is_(None),
    )
    return (await conn.execute(stmt.returning(Organization.id))).scalar_one_or_none()


async def seed_directory(
    conn: AsyncConnection, settings: Settings, data: dict[str, Any] | None = None
) -> dict[str, int]:
    """Load the provisional directory (after the reference seed: niches and regions must exist); return its counts."""
    ensure_loadable(settings)
    niche_ids: dict[str, Any] = dict((await conn.execute(select(Niche.slug, Niche.id))).tuples().all())
    counties = set((await conn.execute(select(Region.code).where(Region.kind == RegionKind.COUNTY))).scalars())
    rows = parse_rows(
        load_directory() if data is None else data,
        niche_slugs=set(niche_ids),
        county_codes=counties,
        app_env=settings.app_env,
        today=clock.utcnow().date(),
    )
    for org in rows:
        org_id = await _upsert(conn, org)
        if org_id is None:
            continue  # claimed (E1/E2), delisted or not a seed organisation: left as it is
        wanted = [niche_ids[slug] for slug in org.niches]
        await conn.execute(delete(OrgNiche).where(OrgNiche.org_id == org_id, OrgNiche.niche_id.not_in(wanted)))
        await conn.execute(
            insert(OrgNiche).values([{"org_id": org_id, "niche_id": n} for n in wanted]).on_conflict_do_nothing()
        )
    return await directory_counts(conn)
