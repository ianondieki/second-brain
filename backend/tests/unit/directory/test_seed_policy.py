"""AC-DIR-3 (backend half) and the REQ-DIR-02 seed policy: ``backend/seed/ke_provisional.yaml`` holds public
organisational data only (no logos, no contacts), every row is E0 with an https source URL and a real retrieval date,
niches and counties are known reference codes (ISO 3166-2:KE, as ``organizations.county_code`` stores them), and the
loader refuses to run outside ``APP_ENV`` dev/test or to set any verification above ``unclaimed`` outside
test/staging. The directory card has no logo or contact field and the badge copy is exact."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest

from bridge.directory.schemas import OrgCard
from bridge.directory.service import badge_for
from bridge.models.enums import OrgKind, OrgVerification
from bridge.seed.directory import (
    REQUIRED_FIELDS,
    DirectorySeedInvalid,
    DirectorySeedRefused,
    SeedOrg,
    ensure_loadable,
    load_directory,
    parse_rows,
)
from bridge.seed.reference import load_reference

E0_BADGE = "Listed from public information · not on the platform · not affiliated"
E1_BADGE = "Domain verified (pending legal verification)"
# Key fragments that would carry a logo or a contact (docs/spec/06 6.2: no personal emails, no logos).
FORBIDDEN_KEY_PARTS = ("logo", "image", "icon", "photo", "avatar", "email", "phone", "mobile", "contact", "person")
PHONE = re.compile(r"(?:\+?254|\b0)[17]\d{8}\b")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "proton.me"}
HOSTNAME = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def today() -> date:
    return datetime.now(UTC).date()


@pytest.fixture(scope="module")
def reference() -> dict[str, Any]:
    return load_reference()


@pytest.fixture(scope="module")
def niche_slugs(reference: dict[str, Any]) -> set[str]:
    return {str(n["slug"]) for n in reference["niches"]}


@pytest.fixture(scope="module")
def counties(reference: dict[str, Any]) -> dict[str, str]:
    """ISO 3166-2:KE code -> county name (``regions.code``, the key ``organizations.county_code`` references)."""
    return {str(r["code"]): str(r["name"]) for r in reference["regions"] if r["kind"] == "county"}


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    return load_directory()


def parse(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str], *, app_env: str = "test"
) -> list[SeedOrg]:
    return parse_rows(data, niche_slugs=niche_slugs, county_codes=set(counties), app_env=app_env, today=today())


def walk(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Every (key path, leaf value) of a YAML document."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield f"{path}.{key}", None
            yield from walk(inner, f"{path}.{key}")
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from walk(inner, f"{path}[{index}]")
    else:
        yield path, value


def test_every_row_passes_the_loader_checks(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str]
) -> None:
    rows = parse(data, niche_slugs, counties)
    assert len(rows) == len(data["orgs"]) == 85
    assert len({r.slug for r in rows}) == len(rows)


def test_rows_carry_only_the_documented_fields(data: dict[str, Any]) -> None:
    assert set(data) == {"version", "status", "orgs"}
    for row in data["orgs"]:
        assert set(row) == REQUIRED_FIELDS, row["slug"]


def test_no_logo_or_contact_anywhere_in_the_file(data: dict[str, Any]) -> None:
    for path, value in walk(data):
        key = path.rsplit(".", 1)[-1].lower()
        assert not any(part in key for part in FORBIDDEN_KEY_PARTS), path
        if isinstance(value, str):
            assert "@" not in value, path  # no email address of any kind
            assert not PHONE.search(value.replace(" ", "")), path
            assert not value.lower().endswith(IMAGE_SUFFIXES), path


def test_every_row_is_e0(data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str]) -> None:
    assert all("verification" not in row for row in data["orgs"])
    assert {r.verification for r in parse(data, niche_slugs, counties)} == {OrgVerification.UNCLAIMED}


def test_niches_and_counties_are_known_reference_codes(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str]
) -> None:
    for row in data["orgs"]:
        assert row["niches"], row["slug"]
        assert set(row["niches"]) <= niche_slugs, row["slug"]
        assert row["county"] is None or row["county"] in counties, row["slug"]
        assert OrgKind(row["kind"])


def test_county_governments_map_to_their_own_iso_county(data: dict[str, Any], counties: dict[str, str]) -> None:
    """The 47 county governments each sit in their own county by ISO 3166-2:KE code (not the First-Schedule number,
    which does not align: Mombasa is KE-28 but county 001)."""
    governments = [r for r in data["orgs"] if r["kind"] == "county_govt"]
    assert len(governments) == 47
    assert {r["county"] for r in governments} == set(counties)
    for row in governments:
        assert row["legal_name"] == f"County Government of {counties[row['county']]}", row["slug"]
        assert row["niches"] == ["county-government"]
        assert row["public_entity"] is True
    mombasa = next(r for r in governments if r["slug"] == "county-government-mombasa")
    assert mombasa["county"] == "KE-28"


def test_source_urls_are_https_and_dates_are_real(data: dict[str, Any]) -> None:
    for row in data["orgs"]:
        url = urlsplit(row["source_url"])
        assert url.scheme == "https", row["slug"]
        assert url.hostname, row["slug"]
        assert isinstance(row["source_retrieved_on"], date), row["slug"]
        assert date(2020, 1, 1) <= row["source_retrieved_on"] <= today(), row["slug"]
        assert row["source_register"].strip(), row["slug"]


def test_official_domains_are_bare_hostnames_never_free_mail(data: dict[str, Any]) -> None:
    seen: set[str] = set()
    for row in data["orgs"]:
        for domain in row["official_domains"]:
            assert HOSTNAME.fullmatch(domain), (row["slug"], domain)
            assert domain not in FREE_MAIL, row["slug"]
            assert domain not in seen, domain  # one organisation per official domain
            seen.add(domain)


def test_safaricom_airtel_and_telkom_sit_under_networks_and_telecommunications(data: dict[str, Any]) -> None:
    """AC-DIR-6 (seed half)."""
    telcos = {r["slug"]: r for r in data["orgs"] if "networks-telecommunications" in r["niches"]}
    assert {"safaricom-plc", "airtel-networks-kenya", "telkom-kenya"} <= set(telcos)
    assert telcos["safaricom-plc"]["official_domains"] == ["safaricom.co.ke"]


# --- the loader's own checks (negative cases) ---


def _with(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    changed = copy.deepcopy(data)
    changed["orgs"][0].update(changes)
    return changed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"logo": "https://example.com/logo.png"}, "unknown field 'logo'"),
        ({"email": "info@example.co.ke"}, "unknown field 'email'"),
        ({"niches": ["telecoms"]}, "unknown niche 'telecoms'"),
        ({"niches": []}, "at least one niche"),
        ({"county": "047"}, "unknown county '047'"),  # a First-Schedule number is not how counties are stored
        ({"county": "Nairobi"}, "unknown county 'Nairobi'"),
        ({"source_url": "http://example.com/register"}, "https"),
        ({"source_url": "https:///no-host"}, "https"),
        ({"source_retrieved_on": "2026-09-27"}, "date"),
        ({"source_retrieved_on": date(2999, 1, 1)}, "future"),
        ({"official_domains": ["info@safaricom.co.ke"]}, "hostname"),
        ({"official_domains": ["Safaricom.co.ke"]}, "hostname"),
        ({"official_domains": ["gmail.com"]}, "free-mail"),
        ({"kind": "bank"}, "kind"),
        ({"slug": "Not A Slug"}, "slug"),
        ({"legal_name": " "}, "legal_name"),
        ({"public_entity": "yes"}, "public_entity"),
        ({"source_register": ""}, "source_register"),
        ({"verification": "pending"}, "verification"),
    ],
)
def test_the_loader_rejects_invalid_rows(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str], changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(DirectorySeedInvalid, match=re.escape(message)):
        parse(_with(data, **changes), niche_slugs, counties)


def test_the_loader_rejects_missing_fields_and_duplicate_slugs(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str]
) -> None:
    missing = copy.deepcopy(data)
    del missing["orgs"][0]["source_url"]
    with pytest.raises(DirectorySeedInvalid, match="missing field 'source_url'"):
        parse(missing, niche_slugs, counties)
    duplicate = copy.deepcopy(data)
    duplicate["orgs"].append(copy.deepcopy(duplicate["orgs"][0]))
    with pytest.raises(DirectorySeedInvalid, match="duplicate slug 'safaricom-plc'"):
        parse(duplicate, niche_slugs, counties)
    shared = _with(data, official_domains=["airtelkenya.com"])
    with pytest.raises(DirectorySeedInvalid, match="listed twice"):
        parse(shared, niche_slugs, counties)
    with pytest.raises(DirectorySeedInvalid, match="orgs"):
        parse({"version": 1}, niche_slugs, counties)


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_the_loader_runs_in_dev_and_test(app_env: str) -> None:
    ensure_loadable(app_env)


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_the_loader_refuses_every_other_environment(app_env: str) -> None:
    with pytest.raises(DirectorySeedRefused, match=f"APP_ENV={app_env}.*dev or test.*G6"):
        ensure_loadable(app_env)


@pytest.mark.parametrize("level", ["e1", "e2"])
@pytest.mark.parametrize("app_env", ["dev", "production"])
def test_verification_above_unclaimed_is_refused_outside_test_and_staging(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str], level: str, app_env: str
) -> None:
    with pytest.raises(DirectorySeedRefused, match=f"verification '{level}'.*test or staging"):
        parse(_with(data, verification=level), niche_slugs, counties, app_env=app_env)


@pytest.mark.parametrize("app_env", ["test", "staging"])
def test_verified_fixture_rows_are_allowed_in_test_and_staging(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str], app_env: str
) -> None:
    rows = parse(_with(data, verification="e2"), niche_slugs, counties, app_env=app_env)
    assert rows[0].verification == OrgVerification.E2
    assert rows[1].verification == OrgVerification.UNCLAIMED


def test_a_retrieval_date_of_today_is_accepted(
    data: dict[str, Any], niche_slugs: set[str], counties: dict[str, str]
) -> None:
    rows = parse(_with(data, source_retrieved_on=today()), niche_slugs, counties)
    assert rows[0].source_retrieved_on == today()
    with pytest.raises(DirectorySeedInvalid, match="future"):
        parse(_with(data, source_retrieved_on=today() + timedelta(days=1)), niche_slugs, counties)


# --- AC-DIR-3: the card renders no logo or contact, and the badge copy is exact ---


def _property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for definition in [schema, *schema.get("$defs", {}).values()]:
        names |= set(definition.get("properties", {}))
    return names


def test_directory_cards_have_no_logo_or_contact_field() -> None:
    names = _property_names(OrgCard.model_json_schema())
    assert {"name", "kind", "niches", "county", "badge"} <= names
    for name in names:
        assert not any(part in name.lower() for part in (*FORBIDDEN_KEY_PARTS, "website", "domain", "url")), name


def test_badge_copy_is_exact() -> None:
    assert badge_for(OrgVerification.UNCLAIMED).text == E0_BADGE
    assert badge_for(OrgVerification.E1).text == E1_BADGE
    assert badge_for(OrgVerification.E2).text.strip()
    assert [badge_for(v).level for v in (OrgVerification.UNCLAIMED, OrgVerification.E1, OrgVerification.E2)] == [
        "e0",
        "e1",
        "e2",
    ]


@pytest.mark.parametrize("level", [OrgVerification.PENDING, OrgVerification.REJECTED])
def test_unlisted_levels_have_no_badge(level: OrgVerification) -> None:
    with pytest.raises(ValueError, match="not listed"):
        badge_for(level)
