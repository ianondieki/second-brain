"""X1-3: ``python -m bridge.seed`` is idempotent (run twice, same row counts); reference data matches the spec."""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.seed.reference import SEED_TABLES, seed_all, seed_test_clock

DRAFT_HEADER = "DRAFT — NOT LEGAL ADVICE — MUST BE REVIEWED BY A KENYAN ADVOCATE BEFORE USE"
# A seeded body is the header, a blank line and marker lines only: no legal wording (REQ-REPO-01 T2.1).
PLACEHOLDER_BODY = re.compile(re.escape(DRAFT_HEADER) + r"\n\n(\[\[LEGAL-PLACEHOLDER:[a-z0-9-]+\]\]\n)+")


async def _organisations(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text("SELECT count(*) FROM organizations"))).scalar_one())


async def test_seed_twice_gives_the_same_counts(owner_engine: AsyncEngine) -> None:
    organisations = await _organisations(owner_engine)  # whatever earlier tests left behind
    async with owner_engine.begin() as conn:
        first = await seed_all(conn, get_settings())
    async with owner_engine.begin() as conn:
        second = await seed_all(conn, get_settings())
    assert first == second
    assert set(first) == set(SEED_TABLES)
    async with owner_engine.connect() as conn:
        counties = (await conn.execute(text("SELECT count(*) FROM regions WHERE kind = 'county'"))).scalar_one()
        kenya = (await conn.execute(text("SELECT count(*) FROM regions WHERE code = 'KE'"))).scalar_one()
        plans = (
            await conn.execute(text("SELECT count(*) FROM plans WHERE code LIKE 'dev_%' OR code LIKE 'org_%'"))
        ).scalar_one()
        legal = (await conn.execute(text("SELECT count(*) FROM legal_templates WHERE version = 'v1'"))).scalar_one()
        ndas = (await conn.execute(text("SELECT count(*) FROM nda_templates WHERE version = 'v1'"))).scalar_one()
    assert (counties, kenya) == (47, 1)
    assert plans == 9
    # The reference seed never creates organisations: the provisional directory is bridge.seed.directory (dev/test).
    assert await _organisations(owner_engine) == organisations
    assert (legal, ndas) == (5, 2)


async def test_holidays_include_gazetted_2026_dates(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())
        rows = (await conn.execute(text("SELECT observed_on::text FROM holidays WHERE country = 'KE'"))).scalars().all()
    for day in ("2026-06-01", "2026-10-20", "2026-12-12", "2026-12-25"):
        assert day in rows


async def test_legal_templates_are_hashed_placeholders_only(owner_engine: AsyncEngine) -> None:
    """Master Enterprise Terms, Evaluation NDA, mutual NDA, ToS and AUP v1 exist as DRAFT placeholders; sha256 is the
    SHA-256 of the UTF-8 body; each NDA template points at its legal body and carries the same hash."""
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())
        templates = (
            await conn.execute(
                text(
                    "SELECT id, kind::text AS kind, body, sha256, is_placeholder FROM legal_templates"
                    " WHERE version = 'v1'"
                )
            )
        ).all()
        ndas = (
            await conn.execute(
                text(
                    "SELECT n.kind::text AS kind, l.kind::text AS legal_kind, n.sha256 = l.sha256 AS same_hash"
                    " FROM nda_templates n JOIN legal_templates l ON l.id = n.legal_template_id WHERE n.version = 'v1'"
                )
            )
        ).all()
    assert {t.kind for t in templates} == {"master_enterprise_terms", "evaluation_nda", "mutual_nda", "tos", "aup"}
    for template in templates:
        assert PLACEHOLDER_BODY.fullmatch(template.body), template.kind
        assert template.sha256 == hashlib.sha256(template.body.encode("utf-8")).digest()
        assert template.is_placeholder
    assert {(n.kind, n.legal_kind, n.same_hash) for n in ndas} == {
        ("evaluation", "evaluation_nda", True),
        ("mutual", "mutual_nda", True),
    }


async def test_the_seed_enables_the_test_clock_outside_production_only(owner_engine: AsyncEngine) -> None:
    """Revision 0003: the dev/test clock moves only where the owner enabled it; the seed (the owner) enables it in dev,
    test and staging and disables it in production, keeping its offset either way."""
    enabled = text("SELECT enabled FROM test_clock")
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()  # rolled back: the session database keeps its clock as it was
        try:
            await seed_all(conn, get_settings())  # APP_ENV=test
            assert (await conn.execute(enabled)).scalar_one() is True
            await conn.execute(text("UPDATE test_clock SET clock_offset = interval '3 days'"))
            for app_env, expected in (("production", False), ("staging", True), ("dev", True), ("production", False)):
                await seed_test_clock(conn, get_settings().model_copy(update={"app_env": app_env}))
                assert (await conn.execute(enabled)).scalar_one() is expected
            offset = (await conn.execute(text("SELECT extract(day FROM clock_offset) FROM test_clock"))).scalar_one()
            assert offset == 3
        finally:
            await transaction.rollback()
