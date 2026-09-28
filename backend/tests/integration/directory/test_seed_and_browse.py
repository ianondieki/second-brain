"""AC-DIR-5/a and the browse half of AC-DIR-6 (REQ-DIR-01, REQ-DIR-02; docs/spec/06 6.2), on the seeded database.

- ``python -m bridge.seed`` seeds the niches and org types and, in dev/test only, the provisional directory; the
  directory seed is idempotent and refuses staging and production (and verified rows outside test/staging).
- The directory groups listed organisations under two-level niche headings with org-type, county, niche and name
  filters and cursor pagination; Safaricom, Airtel and Telkom sit under ICT › Networks & Telecommunications.
- Cards carry no logo or contact; delisted, pending and unknown organisations are never shown (404 by id); signed-out
  callers get 401; the responsiveness score shows only for E2 with >= 10 eligible tags and 60 days after E2.
- A niche staff admin adds through ``POST /api/admin/niches`` is selectable in the niches endpoint and the directory
  at once (no deploy, no cache).

The NGO/PBO claim-to-E2 clause of AC-DIR-6 is T2.6b (``test_claims.py::test_ngo_e2``).
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.config import Settings, get_settings
from bridge.directory.responsiveness import FixtureResponsiveness, ResponsivenessStats
from bridge.ids import uuid7
from bridge.seed.directory import DirectorySeedRefused, load_directory, seed_directory
from bridge.seed.reference import seed_all
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as

BACKEND = Path(__file__).resolve().parents[3]
TELECOM = "ICT › Networks & Telecommunications"
E0_BADGE = "Listed from public information · not on the platform · not affiliated"
E1_BADGE = "Domain verified (pending legal verification)"
CARD_FIELDS = {"id", "slug", "name", "kind", "niches", "county", "badge", "responsiveness"}


@dataclass(frozen=True, slots=True)
class Seeded:
    counts: dict[str, int]
    slugs: frozenset[str]
    tag: str
    e2_old: UUID  # E2 for 61 days, 12 eligible tags
    e2_new: UUID  # E2 for 30 days, 12 eligible tags
    e2_few: UUID  # E2 for 61 days, 9 eligible tags
    e1: UUID
    delisted: UUID
    pending: UUID  # the signed-in user's own self-signup organisation (not listed)
    no_niche: UUID  # listed, without a niche
    user_id: UUID


async def _org(
    conn: AsyncConnection,
    tag: str,
    name: str,
    *,
    verification: str = "unclaimed",
    e2_days: int | None = None,
    delisted: bool = False,
    source: str = "admin",
    niche: str | None = "networks-telecommunications",
) -> UUID:
    org_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, county_code, e2_verified_at,"
            " delisted_at) VALUES (:id, 'sme', :name, :slug, CAST(:source AS org_source),"
            " CAST(:verification AS org_verification), 'KE-01',"
            " CASE WHEN CAST(:days AS integer) IS NULL THEN NULL ELSE now() - make_interval(days => :days) END,"
            " CASE WHEN :delisted THEN now() END)"
        ),
        {
            "id": org_id,
            "name": f"{name} {tag}",
            "slug": f"{name.lower().replace(' ', '-')}-{tag}",
            "source": source,
            "verification": verification,
            "days": e2_days,
            "delisted": delisted,
        },
    )
    if niche:
        await conn.execute(
            text("INSERT INTO org_niches (org_id, niche_id) SELECT :org, id FROM niches WHERE slug = :niche"),
            {"org": org_id, "niche": niche},
        )
    return org_id


@pytest.fixture(scope="module")
async def seeded(owner_engine: AsyncEngine) -> AsyncIterator[Seeded]:
    """The reference seed and the provisional directory (committed), plus fixture organisations of every other
    visibility; all removed at the end so later modules see a directory-free database."""
    settings = get_settings()
    tag = uuid4().hex[:8]
    async with owner_engine.begin() as conn:
        await seed_all(conn, settings)
        counts = await seed_directory(conn, settings)
        user_id = await w.add_user(conn, f"browser-{tag}@example.test", "Browser")
        fixtures = {
            "e2_old": await _org(conn, tag, "Old E2", verification="e2", e2_days=61),
            "e2_new": await _org(conn, tag, "New E2", verification="e2", e2_days=30),
            "e2_few": await _org(conn, tag, "Few E2", verification="e2", e2_days=61),
            "e1": await _org(conn, tag, "Claimed E1", verification="e1"),
            "delisted": await _org(conn, tag, "Delisted", delisted=True),
            "pending": await _org(conn, tag, "Pending", verification="pending", source="self_signup"),
            "no_niche": await _org(conn, tag, "Nicheless", niche=None),
        }
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, '{owner}')"),
            {"id": uuid7(), "org": fixtures["pending"], "user": user_id},
        )
    slugs = frozenset(str(row["slug"]) for row in load_directory()["orgs"])
    try:
        yield Seeded(counts=counts, slugs=slugs, tag=tag, user_id=user_id, **fixtures)
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM organizations WHERE (source = 'seed' AND slug = ANY(:slugs)) OR slug LIKE :mine"),
                {"slugs": sorted(slugs), "mine": f"%-{tag}"},
            )
            await conn.execute(text("DELETE FROM niches WHERE slug LIKE :mine"), {"mine": f"%-{tag}"})


@pytest.fixture
async def client(app_engine: AsyncEngine, seeded: Seeded) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine) as c:
        await sign_in_as(c, app_engine, seeded.user_id, mfa_verified=False)
        yield c


async def walk(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    """Every group of every page, in order (a heading split across pages appears once per page)."""
    groups: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(200):
        query = {**params, **({"cursor": cursor} if cursor else {})}
        response = await client.get("/api/directory/orgs", params=query)
        assert response.status_code == 200, response.text
        page = response.json()
        groups += page["groups"]
        cursor = page["next_cursor"]
        if cursor is None:
            return groups
    raise AssertionError("pagination did not end")


def pairs(groups: list[dict[str, Any]]) -> list[tuple[str | None, str]]:
    return [(g["niche"]["label"] if g["niche"] else None, card["slug"]) for g in groups for card in g["orgs"]]


def merged(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join a heading split across two pages back into one group."""
    out: list[dict[str, Any]] = []
    for group in groups:
        if out and out[-1]["niche"] == group["niche"]:
            out[-1] = {"niche": group["niche"], "orgs": out[-1]["orgs"] + group["orgs"]}
        else:
            out.append(group)
    return out


def cards(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {card["slug"]: card for g in groups for card in g["orgs"]}


# --- the seed ---


async def test_the_directory_seed_is_idempotent(owner_engine: AsyncEngine, seeded: Seeded) -> None:
    assert seeded.counts == {"organizations": 85, "org_niches": 85}
    async with owner_engine.begin() as conn:
        again = await seed_directory(conn, get_settings())
    assert again == seeded.counts


async def test_seeded_rows_are_e0_with_their_source_and_iso_county(owner_engine: AsyncEngine, seeded: Seeded) -> None:
    async with owner_engine.connect() as conn:
        rows = {
            r.slug: r
            for r in await conn.execute(
                text(
                    "SELECT slug, verification::text AS verification, source_url, source_retrieved_on, county_code,"
                    " CAST(official_domains AS text[]) AS official_domains, public_entity, website, kind::text AS kind"
                    " FROM organizations"
                    " WHERE source = 'seed' AND slug = ANY(:slugs)"
                ),
                {"slugs": sorted(seeded.slugs)},
            )
        }
    assert set(rows) == seeded.slugs
    assert {r.verification for r in rows.values()} == {"unclaimed"}
    assert all(r.source_url.startswith("https://") and r.source_retrieved_on for r in rows.values())
    assert all(r.website is None for r in rows.values())  # no contact or logo data beyond the documented fields
    assert rows["safaricom-plc"].county_code == "KE-30"
    assert rows["safaricom-plc"].official_domains == []  # cited only to Wikipedia so far: no automatic E1
    assert rows["telkom-kenya"].official_domains == ["telkom.co.ke"]
    assert rows["county-government-mombasa"].county_code == "KE-28"
    assert rows["county-government-mombasa"].public_entity is True
    assert rows["amref-health-africa-in-kenya"].county_code is None


@pytest.mark.parametrize("app_env", ["staging", "production"])
async def test_the_directory_seed_refuses_staging_and_production(
    owner_engine: AsyncEngine, seeded: Seeded, app_env: str
) -> None:
    settings = get_settings().model_copy(update={"app_env": app_env})
    async with owner_engine.connect() as conn:
        with pytest.raises(DirectorySeedRefused, match=f"APP_ENV={app_env}"):
            await seed_directory(conn, settings)
        await conn.rollback()


async def test_the_directory_seed_refuses_the_settings_default(
    owner_engine: AsyncEngine, seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """APP_ENV defaults to dev; without an explicit APP_ENV the loader refuses before it writes anything."""
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    async with owner_engine.connect() as conn:
        with pytest.raises(DirectorySeedRefused, match="APP_ENV is not set"):
            await seed_directory(conn, settings)
        assert not conn.in_transaction()  # refused before the first statement


async def test_a_verified_row_is_refused_in_dev_and_loaded_in_test(owner_engine: AsyncEngine, seeded: Seeded) -> None:
    data = copy.deepcopy(load_directory())
    fixture = {**copy.deepcopy(data["orgs"][0]), "slug": f"telco-a-fixture-{seeded.tag}", "verification": "e2"}
    fixture["official_domains"] = []
    data["orgs"].append(fixture)
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            with pytest.raises(DirectorySeedRefused, match="verification 'e2'"):
                await seed_directory(conn, get_settings().model_copy(update={"app_env": "dev"}), data)
            await seed_directory(conn, get_settings(), data)  # APP_ENV=test
            row = (
                await conn.execute(
                    text("SELECT verification::text, e2_verified_at FROM organizations WHERE slug = :s"),
                    {"s": fixture["slug"]},
                )
            ).one()
            assert row[0] == "e2"
            assert row[1] is not None
        finally:
            await transaction.rollback()


async def test_a_claimed_seed_org_keeps_its_verification_when_the_seed_runs_again(
    owner_engine: AsyncEngine, seeded: Seeded
) -> None:
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(
                text("UPDATE organizations SET verification = 'e1', legal_name = 'Kept' WHERE slug = 'telkom-kenya'")
            )
            await conn.execute(
                text("DELETE FROM org_niches WHERE org_id = (SELECT id FROM organizations WHERE slug = 'telkom-kenya')")
            )
            await seed_directory(conn, get_settings())
            row = (
                await conn.execute(
                    text(
                        "SELECT o.verification::text, o.legal_name, count(n.niche_id) FROM organizations o"
                        " LEFT JOIN org_niches n ON n.org_id = o.id WHERE o.slug = 'telkom-kenya'"
                        " GROUP BY o.verification, o.legal_name"
                    )
                )
            ).one()
            assert tuple(row) == ("e1", "Kept", 0)
        finally:
            await transaction.rollback()


async def test_a_delisted_seed_org_is_not_refreshed_when_the_seed_runs_again(
    owner_engine: AsyncEngine, seeded: Seeded
) -> None:
    """Delisting is never undone and a delisted organisation keeps what it had: the upsert skips it, niches too."""
    data = copy.deepcopy(load_directory())
    row = next(r for r in data["orgs"] if r["slug"] == "mawingu-networks")
    row.update(legal_name="Mawingu Networks Renamed Limited", county="KE-30", niches=["higher-education"])
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(
                text(
                    "UPDATE organizations SET delisted_at = now(), legal_name = 'Kept' WHERE slug = 'mawingu-networks'"
                )
            )
            await seed_directory(conn, get_settings(), data)
            org = (
                await conn.execute(
                    text(
                        "SELECT o.legal_name, o.county_code, o.delisted_at IS NOT NULL AS delisted,"
                        " array_agg(n.slug ORDER BY n.slug) AS niches FROM organizations o"
                        " JOIN org_niches x ON x.org_id = o.id JOIN niches n ON n.id = x.niche_id"
                        " WHERE o.slug = 'mawingu-networks' GROUP BY o.id"
                    )
                )
            ).one()
            assert tuple(org) == ("Kept", "KE-20", True, ["networks-telecommunications"])
        finally:
            await transaction.rollback()


async def test_a_re_seed_drops_a_niche_the_file_no_longer_lists(owner_engine: AsyncEngine, seeded: Seeded) -> None:
    data = copy.deepcopy(load_directory())
    row = next(r for r in data["orgs"] if r["slug"] == "poa-internet-kenya")
    row["niches"] = ["higher-education"]
    query = text(
        "SELECT array_agg(n.slug ORDER BY n.slug) FROM org_niches x JOIN niches n ON n.id = x.niche_id"
        " WHERE x.org_id = (SELECT id FROM organizations WHERE slug = 'poa-internet-kenya')"
    )
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            assert (await conn.execute(query)).scalar_one() == ["networks-telecommunications"]
            await seed_directory(conn, get_settings(), data)
            assert (await conn.execute(query)).scalar_one() == ["higher-education"]
        finally:
            await transaction.rollback()


def _seed_command(database_url: URL, app_env: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "APP_ENV": app_env,
        "DATABASE_OWNER_URL": database_url.render_as_string(hide_password=False),
    }
    return subprocess.run(
        [sys.executable, "-m", "bridge.seed"], cwd=BACKEND, env=env, capture_output=True, text=True, check=False
    )


async def test_the_seed_command_loads_the_directory_in_test_only(database_url: URL, owner_engine: AsyncEngine) -> None:
    """The command commits; this test removes the organisations it created itself (none when the module's seed
    already holds them), so it leaves the database as it found it whatever ran before."""
    slugs = {str(row["slug"]) for row in load_directory()["orgs"]}
    async with owner_engine.connect() as conn:
        found = await conn.execute(text("SELECT slug FROM organizations WHERE slug = ANY(:s)"), {"s": sorted(slugs)})
        existing = set(found.scalars())
    try:
        first, second = _seed_command(database_url, "test"), _seed_command(database_url, "test")
        assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
        assert first.stdout == second.stdout
        assert "seed: organizations (provisional directory) = 85 rows" in first.stdout
        assert "seed: org_niches (provisional directory) = 85 rows" in first.stdout

        staging = _seed_command(database_url, "staging")
        assert staging.returncode == 0, staging.stderr
        assert "seed: regions = 48 rows" in staging.stdout
        assert "seed: provisional directory skipped (APP_ENV=staging" in staging.stdout
        assert "(provisional directory) =" not in staging.stdout
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM organizations WHERE source = 'seed' AND slug = ANY(:created)"),
                {"created": sorted(slugs - existing)},
            )


# --- AC-DIR-5/a: niches and org types ---


async def test_the_seeded_niches_and_org_types_exist(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    tree = (await client.get("/api/directory/niches")).json()
    labels = {n["label"] for n in tree} | {c["label"] for n in tree for c in n["children"]}
    names = {n["name"] for n in tree} | {c["name"] for n in tree for c in n["children"]}
    assert {
        "Microfinance & SACCOs",
        "Basic education",
        "Higher education",
        "National government",
        "County government",
        "Social/NGO",
    } <= names
    assert {
        "Financial services › Microfinance & SACCOs",
        "Education › Basic education",
        "Education › Higher education",
        "Public sector › National government",
        "Public sector › County government",
        "Social/NGO",
        TELECOM,
    } <= labels
    ict = next(n for n in tree if n["slug"] == "ict")
    assert [(c["slug"], c["isic_code"]) for c in ict["children"]] == [("networks-telecommunications", "61")]

    options = (await client.get("/api/directory/filter-options")).json()
    org_types = {o["label"]: o["value"] for o in options["org_types"]}
    assert {
        "School": "school",
        "University/TVET": "university_tvet",
        "National Govt": "national_govt",
        "County Govt": "county_govt",
        "NGO/PBO": "ngo_pbo",
    }.items() <= org_types.items()
    assert len(options["counties"]) == 47
    assert {"code": "KE-30", "name": "Nairobi City"} in options["counties"]
    async with owner_engine.connect() as conn:
        kinds = set((await conn.execute(text("SELECT unnest(enum_range(NULL::org_kind))::text"))).scalars())
    assert {"school", "university_tvet", "national_govt", "county_govt", "ngo_pbo"} <= kinds


async def test_an_admin_added_niche_is_selectable_at_once(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, seeded: Seeded
) -> None:
    """AC-DIR-5/a end to end: staff admin adds a niche through ``POST /api/admin/niches`` while the app runs; the
    niches endpoint offers it and the directory browses it on the next request (no deploy, no cache)."""
    slug = f"water-services-{seeded.tag}"
    before = (await client.get("/api/directory/niches")).json()
    assert slug not in {c["slug"] for n in before for c in n["children"]}
    async with owner_engine.begin() as conn:
        admin_id = await w.add_user(conn, f"niche-admin-{seeded.tag}@example.test", "Admin", staff_role="admin")
    async with make_client(app_engine) as admin:
        await sign_in_as(admin, app_engine, admin_id, mfa_verified=True)
        created = await admin.post(
            "/api/admin/niches",
            json={"slug": slug, "name": "Water services", "parent_slug": "public-sector", "isic_code": "3600"},
        )
    assert created.status_code == 201, created.text
    async with owner_engine.begin() as conn:  # tagging an organisation is the directory editor's job (later task)
        await conn.execute(
            text("INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)"),
            {"org": seeded.e1, "niche": created.json()["id"]},
        )
    tree = (await client.get("/api/directory/niches")).json()
    public = next(n for n in tree if n["slug"] == "public-sector")
    added = next(c for c in public["children"] if c["slug"] == slug)
    assert added["id"] == created.json()["id"]
    assert added["label"] == "Public sector › Water services"
    assert added["isic_code"] == "3600"
    groups = await walk(client, niche=slug)
    assert pairs(groups) == [("Public sector › Water services", f"claimed-e1-{seeded.tag}")]


# --- AC-DIR-6 (browse half) ---


async def test_the_directory_groups_orgs_under_niche_headings(client: httpx.AsyncClient, seeded: Seeded) -> None:
    groups = merged(await walk(client, limit=30))
    headings = [g["niche"]["label"] if g["niche"] else None for g in groups]
    assert len(headings) == len(set(headings))  # each heading once: its organisations are contiguous
    assert all(" › " in h for h in headings if h and h != "Social/NGO")
    by_heading = {g["niche"]["label"]: {c["slug"] for c in g["orgs"]} for g in groups if g["niche"]}
    assert {"safaricom-plc", "airtel-networks-kenya", "telkom-kenya"} <= by_heading[TELECOM]
    assert len({s for s in by_heading["Public sector › County government"] if s in seeded.slugs}) == 47
    assert "amref-health-africa-in-kenya" in by_heading["Social/NGO"]
    assert groups[-1]["niche"] is None  # organisations without a niche come last
    assert f"nicheless-{seeded.tag}" in {c["slug"] for c in groups[-1]["orgs"]}
    found = cards(groups)
    assert seeded.slugs <= set(found)
    for card in found.values():
        assert set(card) == CARD_FIELDS
    assert found["safaricom-plc"]["badge"] == {"level": "e0", "text": E0_BADGE}
    assert found[f"claimed-e1-{seeded.tag}"]["badge"] == {"level": "e1", "text": E1_BADGE}


async def test_org_type_county_niche_and_name_filters(client: httpx.AsyncClient, seeded: Seeded) -> None:
    counties = cards(await walk(client, kind="county_govt"))
    assert {c["kind"] for c in counties.values()} == {"county_govt"}
    assert len(set(counties) & seeded.slugs) == 47

    nairobi_companies = pairs(await walk(client, kind="company", county="KE-30"))
    slugs = {slug for _, slug in nairobi_companies}
    assert {"safaricom-plc", "airtel-networks-kenya", "telkom-kenya", "jamii-telecommunications"} <= slugs
    assert "mawingu-networks" not in slugs  # Laikipia (KE-20)
    assert {heading for heading, _ in nairobi_companies} == {TELECOM}

    two_types = cards(await walk(client, kind=["national_govt", "ngo_pbo"]))
    assert {c["kind"] for c in two_types.values()} == {"national_govt", "ngo_pbo"}

    parent = pairs(await walk(client, niche="ict"))
    assert {heading for heading, _ in parent} == {TELECOM}
    assert "safaricom-plc" in {slug for _, slug in parent}

    assert [slug for _, slug in pairs(await walk(client, q="safaricom"))] == ["safaricom-plc"]
    assert pairs(await walk(client, q="100%")) == []  # LIKE wildcards are literal
    mombasa = cards(await walk(client, county="KE-28"))
    assert mombasa["county-government-mombasa"]["county"] == {"code": "KE-28", "name": "Mombasa"}


@pytest.mark.parametrize("q", ["%", "_", "\\"])
async def test_like_wildcards_in_the_name_search_match_only_themselves(client: httpx.AsyncClient, q: str) -> None:
    """No legal name contains %, _ or a backslash, so each finds nothing (unescaped, % and _ would match every name)."""
    assert pairs(await walk(client, q=q)) == []


async def test_pagination_walks_every_pair_exactly_once(client: httpx.AsyncClient) -> None:
    whole = pairs(await walk(client, limit=100))
    paged = pairs(await walk(client, limit=7))
    assert paged == whole
    assert len(paged) == len(set(paged))
    bad = await client.get("/api/directory/orgs", params={"cursor": "not-a-cursor"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "invalid_cursor"
    assert (await client.get("/api/directory/orgs", params={"limit": 101})).status_code == 422
    assert (await client.get("/api/directory/orgs", params={"county": "030"})).status_code == 422
    too_many = await client.get("/api/directory/orgs", params={"niche": [f"n-{i}" for i in range(51)]})
    assert too_many.status_code == 422
    assert too_many.json()["detail"]["code"] == "too_many_filter_values"


async def test_delisted_pending_and_unknown_orgs_are_never_shown(client: httpx.AsyncClient, seeded: Seeded) -> None:
    found = cards(await walk(client, limit=100))
    assert f"delisted-{seeded.tag}" not in found
    assert f"pending-{seeded.tag}" not in found  # the caller's own organisation, but not listed
    for org_id in (seeded.delisted, seeded.pending, uuid7()):
        response = await client.get(f"/api/directory/orgs/{org_id}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"


async def test_one_card_by_id(client: httpx.AsyncClient, seeded: Seeded) -> None:
    safaricom = cards(await walk(client, q="Safaricom"))["safaricom-plc"]
    card = (await client.get(f"/api/directory/orgs/{safaricom['id']}")).json()
    assert card == safaricom
    assert card["name"] == "Safaricom PLC"
    assert card["kind"] == "company"
    assert card["niches"] == [{"id": card["niches"][0]["id"], "slug": "networks-telecommunications", "label": TELECOM}]
    assert card["county"] == {"code": "KE-30", "name": "Nairobi City"}
    assert card["responsiveness"] is None


async def test_signed_out_callers_get_401(app_engine: AsyncEngine, seeded: Seeded) -> None:
    async with make_client(app_engine) as anonymous:
        for path in ("/api/directory/orgs", "/api/directory/niches", "/api/directory/filter-options"):
            assert (await anonymous.get(path)).status_code == 401
        assert (await anonymous.get(f"/api/directory/orgs/{seeded.e1}")).status_code == 401


async def test_responsiveness_shows_only_for_e2_after_60_days_with_10_eligible_tags(
    client: httpx.AsyncClient, seeded: Seeded
) -> None:
    ten = ResponsivenessStats(eligible_tags=12, median_response_days=3.4, answered_share=0.8)
    client.app.state.responsiveness = FixtureResponsiveness(  # type: ignore[attr-defined]
        {
            seeded.e2_old: ten,
            seeded.e2_new: ten,
            seeded.e2_few: ResponsivenessStats(eligible_tags=9, median_response_days=1, answered_share=1),
            seeded.e1: ten,
        }
    )
    shown = {
        org_id: (await client.get(f"/api/directory/orgs/{org_id}")).json()
        for org_id in (seeded.e2_old, seeded.e2_new, seeded.e2_few, seeded.e1)
    }
    assert shown[seeded.e2_old]["responsiveness"] == {
        "median_days": 3,
        "answered_pct": 80,
        "text": "Responds in a median of 3 days · 80% answered",
    }
    assert shown[seeded.e2_old]["badge"]["level"] == "e2"
    assert shown[seeded.e2_new]["responsiveness"] is None  # 30 days after E2
    assert shown[seeded.e2_few]["responsiveness"] is None  # 9 eligible tags
    assert shown[seeded.e1]["responsiveness"] is None  # E1
    in_list = cards(await walk(client, q=f"E2 {seeded.tag}"))
    assert in_list[f"old-e2-{seeded.tag}"]["responsiveness"] == shown[seeded.e2_old]["responsiveness"]
    assert in_list[f"new-e2-{seeded.tag}"]["responsiveness"] is None
