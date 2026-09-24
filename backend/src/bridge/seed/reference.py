"""Reference data upserts shared by ``python -m bridge.seed`` and the tests (X1-3: idempotent)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.admin.models import Holiday
from bridge.billing import plans
from bridge.billing.models import Plan
from bridge.config import BACKEND_DIR, Settings
from bridge.directory.models import Niche, Region
from bridge.ids import uuid7

REFERENCE_FILE = BACKEND_DIR / "seed" / "reference.yaml"
SEED_TABLES = ("regions", "niches", "holidays", "plans")


def load_reference(path: Path = REFERENCE_FILE) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


async def seed_regions(conn: AsyncConnection, rows: list[dict[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda r: r.get("parent") is not None)  # the country before its counties
    for row in ordered:
        stmt = insert(Region).values(
            code=row["code"],
            parent_code=row.get("parent"),
            kind=row["kind"],
            name=row["name"],
            county_code=row.get("county_code"),
        )
        await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[Region.code],
                set_={
                    "parent_code": stmt.excluded.parent_code,
                    "kind": stmt.excluded.kind,
                    "name": stmt.excluded.name,
                    "county_code": stmt.excluded.county_code,
                },
            )
        )


async def seed_niches(conn: AsyncConnection, rows: list[dict[str, Any]]) -> None:
    ids: dict[str, Any] = {}
    existing = await conn.execute(select(Niche.slug, Niche.id))
    ids.update(dict(existing.tuples().all()))
    for order, row in enumerate(sorted(rows, key=lambda r: r.get("parent") is not None)):
        parent = row.get("parent")
        stmt = insert(Niche).values(
            id=ids.get(row["slug"], uuid7()),
            slug=row["slug"],
            name_en=row["name_en"],
            isic_code=row.get("isic"),
            parent_id=ids[parent] if parent else None,
            sort_order=order,
        )
        result = await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[Niche.slug],
                set_={
                    "name_en": stmt.excluded.name_en,
                    "isic_code": stmt.excluded.isic_code,
                    "parent_id": stmt.excluded.parent_id,
                    "sort_order": stmt.excluded.sort_order,
                },
            ).returning(Niche.id)
        )
        ids[row["slug"]] = result.scalar_one()


async def seed_holidays(conn: AsyncConnection, rows: list[dict[str, Any]], country: str = "KE") -> None:
    for row in rows:
        on = date.fromisoformat(str(row["date"]))
        observed = date.fromisoformat(str(row.get("observed") or row["date"]))
        stmt = insert(Holiday).values(
            id=uuid7(),
            country=country,
            holiday_on=on,
            observed_on=observed,
            name=row["name"],
            provisional=bool(row.get("provisional", False)),
            source_url=row.get("source_url"),
        )
        await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[Holiday.country, Holiday.observed_on, Holiday.name],
                set_={
                    "holiday_on": stmt.excluded.holiday_on,
                    "provisional": stmt.excluded.provisional,
                    "source_url": stmt.excluded.source_url,
                },
            )
        )


async def seed_plans(conn: AsyncConnection, settings: Settings) -> None:
    catalog = plans.load(settings.plans_file)
    for spec in catalog.plans.values():
        stmt = insert(Plan).values(
            id=uuid7(),
            code=spec.code,
            side=spec.side,
            name=spec.name,
            price_kes_minor=spec.price_kes_minor,
            interval=spec.interval,
            limits=spec.limits,
            active=True,
            is_default=spec.default,
        )
        await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[Plan.code],
                set_={
                    "side": stmt.excluded.side,
                    "name": stmt.excluded.name,
                    "price_kes_minor": stmt.excluded.price_kes_minor,
                    "interval": stmt.excluded.interval,
                    "limits": stmt.excluded.limits,
                    "active": stmt.excluded.active,
                    "is_default": stmt.excluded.is_default,
                },
            )
        )


async def counts(conn: AsyncConnection) -> dict[str, int]:
    models = {"regions": Region, "niches": Niche, "holidays": Holiday, "plans": Plan}
    return {
        name: int((await conn.execute(select(func.count()).select_from(model))).scalar_one())
        for name, model in models.items()
    }


async def seed_all(
    conn: AsyncConnection, settings: Settings, reference: dict[str, Any] | None = None
) -> dict[str, int]:
    data = reference or load_reference()
    await seed_regions(conn, data["regions"])
    await seed_niches(conn, data["niches"])
    await seed_holidays(conn, data["holidays"])
    await seed_plans(conn, settings)
    return await counts(conn)
